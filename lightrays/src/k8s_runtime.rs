//! Kubernetes-native session runtime.
//!
//! Replaces the Docker daemon with the cluster API: Lightrays runs as a
//! Pod with a ServiceAccount, the SA has RBAC to create Pods in a
//! dedicated namespace, and each session spawns one session Pod. There
//! is no host Docker socket; the cluster API is the boundary.
//!
//! The session Pod still needs SYS_ADMIN inside its own filesystem (the
//! gow entrypoint performs internal bind mounts), but Lightrays' own pod
//! does not — see the Helm chart's `lightrays.securityContext`.

use crate::config::ServerConfig;
use crate::docker::{
    build_container_env, sanitize_title, ContainerConfig, ContainerSession, ContainerStats,
};
use crate::runtime::Runtime;

use anyhow::{Context, Result};
use async_trait::async_trait;
use k8s_openapi::api::core::v1::{
    Capabilities, Container, EnvVar, HostPathVolumeSource, Pod, PodSecurityContext, PodSpec,
    SecurityContext, Volume, VolumeMount,
};
use k8s_openapi::apimachinery::pkg::apis::meta::v1::ObjectMeta;
use kube::api::{Api, DeleteParams, ListParams, LogParams, PostParams};
use kube::Client;
use std::collections::BTreeMap;
use std::time::Duration;

/// Capabilities the gow container image needs to bind-mount inside its
/// own tree. Mirrors the docker base_create_json HostConfig.CapAdd.
const SESSION_CAPABILITIES: &[&str] = &[
    "SYS_ADMIN",
    "SYS_NICE",
    "SYS_PTRACE",
    "NET_RAW",
    "MKNOD",
    "NET_ADMIN",
];

/// Pre-K8s gow image binds `/dev/dri` from the host; the matching cgroup
/// rules go on the Pod via the device plugin or hostPath. We use hostPath
/// for parity with the Docker setup since production deployments are
/// already pinning to a GPU node.
///
/// S-H3: the physical host `/dev/input` is intentionally NOT mounted —
/// GOW injects input by *creating* virtual devices through `/dev/uinput`,
/// so we expose only that node and never the host's real input devices.
const HOST_DRI_PATH: &str = "/dev/dri";
const HOST_UINPUT_PATH: &str = "/dev/uinput";

#[derive(Clone)]
pub struct KubernetesRunner {
    client: Client,
    namespace: String,
    node_selector: BTreeMap<String, String>,
    /// Host path the wayland socket lives on (same hostPath that
    /// Lightrays mounts at `XDG_RUNTIME_DIR`). Defaults to whatever the
    /// `LIGHTRAYS_HOST_XDG_RUNTIME_DIR` env var resolves to.
    host_xdg: String,
    /// Persistent state root on the host. Used for the `apps_state/<id>`
    /// per-app directory. Mirrors `LIGHTRAYS_HOST_STATE_DIR` from the
    /// Docker path.
    host_state_dir: String,
}

impl KubernetesRunner {
    pub async fn new() -> Result<Self> {
        Self::with_config(&ServerConfig::default_for_k8s()).await
    }

    /// Construct a runner from explicit config — used by tests and the
    /// production wiring in [`crate::server::run_server`].
    pub async fn with_config(config: &ServerConfig) -> Result<Self> {
        // `infer` tries in-cluster first, then falls back to kubeconfig
        // — the local-dev story is `kubectl proxy && kubectl config use`.
        let client = Client::try_default()
            .await
            .context("kube client init failed (no in-cluster config and no kubeconfig)")?;

        let node_selector = parse_node_selector(&config.k8s_session_node_selector);
        let host_xdg = std::env::var("LIGHTRAYS_HOST_XDG_RUNTIME_DIR")
            .unwrap_or_else(|_| "/tmp/lightrays-runtime".into());
        let host_state_dir = std::env::var("LIGHTRAYS_HOST_STATE_DIR").unwrap_or_else(|_| {
            std::env::var("LIGHTRAYS_STATE_DIR").unwrap_or_else(|_| "/etc/lightrays".into())
        });

        Ok(Self {
            client,
            namespace: config.k8s_session_namespace.clone(),
            node_selector,
            host_xdg,
            host_state_dir,
        })
    }

    fn pods(&self) -> Api<Pod> {
        Api::namespaced(self.client.clone(), &self.namespace)
    }

    fn build_pod(&self, app: &ContainerConfig, session: &ContainerSession) -> Pod {
        let name = format!("lightrays-{}", session.session_id);
        let app_key = app
            .app_id
            .as_ref()
            .map(|s| sanitize_title(s))
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| sanitize_title(&app.title));

        // Namespace the persistent state under the sanitized owner subject
        // so a user cannot mount another user's home by guessing the
        // app_id/title (S-M1).
        let owner_key = {
            let k = sanitize_title(&app.owner_sub);
            if k.is_empty() {
                "anonymous".to_string()
            } else {
                k
            }
        };
        let host_app_state = format!(
            "{}/apps_state/{}/{}",
            self.host_state_dir, owner_key, app_key
        );
        let container_xdg = "/tmp/sockets";

        let env: Vec<EnvVar> = build_container_env(app, session, container_xdg)
            .into_iter()
            .filter_map(|kv| {
                kv.split_once('=').map(|(k, v)| EnvVar {
                    name: k.to_string(),
                    value: Some(v.to_string()),
                    ..Default::default()
                })
            })
            .collect();

        let volumes = vec![
            // Wayland sockets — shared with the lightrays pod via hostPath.
            // Requires the pods to co-locate on the same node; the chart
            // pins both via nodeSelector.
            Volume {
                name: "wayland".into(),
                host_path: Some(HostPathVolumeSource {
                    path: self.host_xdg.clone(),
                    type_: Some("Directory".into()),
                }),
                ..Default::default()
            },
            Volume {
                name: "app-state".into(),
                host_path: Some(HostPathVolumeSource {
                    path: host_app_state.clone(),
                    type_: Some("DirectoryOrCreate".into()),
                }),
                ..Default::default()
            },
            Volume {
                name: "dri".into(),
                host_path: Some(HostPathVolumeSource {
                    path: HOST_DRI_PATH.into(),
                    type_: Some("Directory".into()),
                }),
                ..Default::default()
            },
            // uinput lets GOW create its own virtual input devices without
            // exposing the host's physical /dev/input (S-H3).
            Volume {
                name: "uinput".into(),
                host_path: Some(HostPathVolumeSource {
                    path: HOST_UINPUT_PATH.into(),
                    type_: Some("CharDevice".into()),
                }),
                ..Default::default()
            },
        ];

        let volume_mounts = vec![
            VolumeMount {
                name: "wayland".into(),
                mount_path: container_xdg.into(),
                ..Default::default()
            },
            VolumeMount {
                name: "app-state".into(),
                mount_path: "/home/retro".into(),
                ..Default::default()
            },
            VolumeMount {
                name: "dri".into(),
                mount_path: HOST_DRI_PATH.into(),
                ..Default::default()
            },
            VolumeMount {
                name: "uinput".into(),
                mount_path: HOST_UINPUT_PATH.into(),
                ..Default::default()
            },
        ];

        let security_context = SecurityContext {
            capabilities: Some(Capabilities {
                add: Some(SESSION_CAPABILITIES.iter().map(|s| s.to_string()).collect()),
                drop: None,
            }),
            ..Default::default()
        };

        let container = Container {
            name: "app".into(),
            image: Some(app.image.clone()),
            env: Some(env),
            volume_mounts: Some(volume_mounts),
            security_context: Some(security_context),
            ..Default::default()
        };

        let mut labels = BTreeMap::new();
        labels.insert("app.kubernetes.io/name".into(), "lightrays-session".into());
        labels.insert("lightrays.session-id".into(), session.session_id.clone());

        Pod {
            metadata: ObjectMeta {
                name: Some(name),
                namespace: Some(self.namespace.clone()),
                labels: Some(labels),
                ..Default::default()
            },
            spec: Some(PodSpec {
                containers: vec![container],
                volumes: Some(volumes),
                restart_policy: Some("Never".into()),
                node_selector: if self.node_selector.is_empty() {
                    None
                } else {
                    Some(self.node_selector.clone())
                },
                // Pin the session pod to the same uid/gid range as the
                // lightrays pod so the shared hostPath wayland sockets
                // are readable. 1000 matches the GOW image's `retro` user.
                security_context: Some(PodSecurityContext {
                    fs_group: Some(1000),
                    run_as_user: Some(1000),
                    run_as_group: Some(1000),
                    ..Default::default()
                }),
                ..Default::default()
            }),
            ..Default::default()
        }
    }

    async fn wait_for_running(&self, name: &str) -> Result<()> {
        let deadline = std::time::Instant::now() + Duration::from_secs(30);
        while std::time::Instant::now() < deadline {
            let pod = self.pods().get(name).await.context("Pod fetch failed")?;
            if let Some(phase) = pod.status.as_ref().and_then(|s| s.phase.as_deref()) {
                if phase == "Running" {
                    return Ok(());
                }
                if phase == "Failed" {
                    anyhow::bail!("Pod {} entered Failed phase", name);
                }
            }
            tokio::time::sleep(Duration::from_millis(500)).await;
        }
        anyhow::bail!("Pod {} did not become Running within 30s", name);
    }
}

#[async_trait]
impl Runtime for KubernetesRunner {
    async fn ping(&self) -> Result<()> {
        // Lightweight check: list pods with limit=1. Fails fast if the
        // SA doesn't have permission or the API is unreachable.
        self.pods()
            .list(&ListParams::default().limit(1))
            .await
            .context("kube list-pods ping failed")?;
        Ok(())
    }

    async fn start(&self, config: &ContainerConfig, session: &ContainerSession) -> Result<String> {
        let pod = self.build_pod(config, session);
        let name = pod
            .metadata
            .name
            .clone()
            .expect("pod name set in build_pod");
        let pods = self.pods();

        // Best-effort delete of any leftover pod with the same name.
        let _ = pods.delete(&name, &DeleteParams::default()).await;

        pods.create(&PostParams::default(), &pod)
            .await
            .with_context(|| format!("create pod {name}"))?;
        log::info!("Created session pod: {}/{}", self.namespace, name);

        self.wait_for_running(&name).await?;
        log::info!("Session pod Running: {}/{}", self.namespace, name);
        Ok(name)
    }

    async fn wait_for_exit(&self, name: &str) -> i64 {
        let pods = self.pods();
        loop {
            match pods.get(name).await {
                Ok(pod) => {
                    if let Some(status) = pod.status.as_ref() {
                        if let Some(phase) = status.phase.as_deref() {
                            if phase == "Succeeded" {
                                return 0;
                            }
                            if phase == "Failed" {
                                let code = status
                                    .container_statuses
                                    .as_ref()
                                    .and_then(|cs| cs.first())
                                    .and_then(|cs| cs.state.as_ref())
                                    .and_then(|s| s.terminated.as_ref())
                                    .map(|t| i64::from(t.exit_code))
                                    .unwrap_or(137);
                                return code;
                            }
                        }
                    }
                }
                Err(kube::Error::Api(e)) if e.code == 404 => {
                    // Pod was deleted out from under us (operator action,
                    // GC). Treat as a SIGKILL exit.
                    return 137;
                }
                Err(e) => {
                    log::warn!("wait_for_exit poll error for {}: {}", name, e);
                }
            }
            tokio::time::sleep(Duration::from_secs(2)).await;
        }
    }

    async fn dump_logs(&self, name: &str, tail_lines: usize) {
        let enabled = std::env::var("LIGHTRAYS_DUMP_CONTAINER_LOGS")
            .map(|v| v.eq_ignore_ascii_case("true") || v == "1")
            .unwrap_or(false);
        if !enabled {
            log::info!(
                "Pod {} exited; log dump suppressed (set LIGHTRAYS_DUMP_CONTAINER_LOGS=true to enable)",
                name
            );
            return;
        }

        let params = LogParams {
            tail_lines: Some(tail_lines as i64),
            ..Default::default()
        };
        match self.pods().logs(name, &params).await {
            Ok(body) => {
                for line in body.lines() {
                    log::warn!("[{name}] {}", line);
                }
            }
            Err(e) => {
                log::warn!("Failed to dump logs for {}: {}", name, e);
            }
        }
    }

    async fn stop(&self, name: &str) -> Result<()> {
        let params = DeleteParams::default().grace_period(10);
        match self.pods().delete(name, &params).await {
            Ok(_) => {
                log::info!("Deleted session pod: {}/{}", self.namespace, name);
                Ok(())
            }
            Err(kube::Error::Api(e)) if e.code == 404 => Ok(()),
            Err(e) => Err(anyhow::Error::new(e)).context("delete pod"),
        }
    }

    async fn stats(&self, _name: &str) -> Result<ContainerStats> {
        // Pod-level CPU/memory stats require the metrics-server API
        // (metrics.k8s.io/v1beta1), which isn't always installed. Return
        // a zeroed snapshot so the API contract still works; operators
        // who want real numbers should scrape the per-pod cgroup
        // metrics through Prometheus on the node.
        Ok(ContainerStats {
            cpu_percent: 0.0,
            mem_used: 0,
            mem_limit: 0,
        })
    }
}

fn parse_node_selector(raw: &str) -> BTreeMap<String, String> {
    let mut selector = BTreeMap::new();
    if raw.trim().is_empty() {
        return selector;
    }
    if let Ok(parsed) = serde_json::from_str::<BTreeMap<String, String>>(raw) {
        return parsed;
    }
    // Fallback: comma-separated key=value pairs so simple deployments
    // don't need to write JSON in env strings.
    for piece in raw.split(',') {
        if let Some((k, v)) = piece.split_once('=') {
            selector.insert(k.trim().to_string(), v.trim().to_string());
        }
    }
    selector
}

impl ServerConfig {
    /// Construct the minimum ServerConfig the Kubernetes runtime needs
    /// during its own `new()` bootstrap. Used internally so we don't
    /// have to pass the whole config in; production callers go through
    /// [`KubernetesRunner::with_config`].
    fn default_for_k8s() -> Self {
        Self {
            runtime_backend: crate::config::RuntimeBackend::Kubernetes,
            k8s_session_namespace: std::env::var("LIGHTRAYS_K8S_SESSION_NAMESPACE")
                .unwrap_or_else(|_| "lightrays-sessions".into()),
            k8s_session_node_selector: std::env::var("LIGHTRAYS_K8S_SESSION_NODE_SELECTOR")
                .unwrap_or_default(),
            hostname: "lightrays".into(),
            api_bind_addr: "0.0.0.0".into(),
            api_port: 8080,
            streaming_bind_addr: "0.0.0.0".into(),
            streaming_port: 8081,
            metrics_bind_addr: "127.0.0.1".into(),
            metrics_port: 9090,
            stun_server: String::new(),
            turn_server: String::new(),
            turn_username: String::new(),
            turn_password: String::new(),
            cors_origins: vec!["*".into()],
            jwt_secret: String::new(),
            session_timeout_secs: 3600,
            reconnect_grace_secs: 30,
            ws_ticket_ttl_secs: 120,
            gow_image: "ghcr.io/games-on-whales/steam:edge".into(),
            gow_compositor: "gamescope".into(),
            allowed_registries: vec![],
            allowed_mount_prefixes: vec![],
            jwt_audience: String::new(),
            max_sessions_global: 0,
            max_sessions_per_user: 0,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_json_node_selector() {
        let selector = parse_node_selector(r#"{"node-role":"gpu","zone":"eu-west"}"#);
        assert_eq!(selector.get("node-role").map(String::as_str), Some("gpu"));
        assert_eq!(selector.get("zone").map(String::as_str), Some("eu-west"));
    }

    #[test]
    fn parses_kv_node_selector() {
        let selector = parse_node_selector("node-role=gpu, zone=eu-west");
        assert_eq!(selector.get("node-role").map(String::as_str), Some("gpu"));
        assert_eq!(selector.get("zone").map(String::as_str), Some("eu-west"));
    }

    #[test]
    fn empty_selector_parses_to_empty_map() {
        assert!(parse_node_selector("").is_empty());
        assert!(parse_node_selector("   ").is_empty());
    }
}
