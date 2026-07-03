//! Docker container runner for lightrays.
//!
//! Manages GOW (Games on Whales) application containers using the bollard
//! Docker API.

use crate::runtime::Runtime;

use anyhow::{Context, Result};
use async_trait::async_trait;
use bollard::container::{
    Config, CreateContainerOptions, ListContainersOptions, LogsOptions, RemoveContainerOptions,
    StatsOptions, StopContainerOptions,
};
use bollard::image::CreateImageOptions;
use bollard::models::{DeviceMapping, HostConfig};
use bollard::Docker;
use futures::StreamExt;
use std::collections::{HashMap, HashSet};
use std::os::unix::fs::FileTypeExt;

/// Reserved name prefix for every container Lightrays spawns
/// (`lightrays-<session_id>`). The reconciliation sweep only ever touches
/// containers whose name starts with this prefix, so co-located foreign
/// containers are never affected.
pub const CONTAINER_PREFIX: &str = "lightrays-";

// ─────────────────────────────────────────────────────────────────────────────
// Docker runner
// ─────────────────────────────────────────────────────────────────────────────

#[derive(Clone)]
pub struct DockerRunner {
    docker: Docker,
}

/// Server-side container configuration resolved from an allowlisted runtime
/// profile. This must not contain raw host config supplied by a browser.
pub struct ContainerConfig {
    pub title: String,
    pub image: String,
    pub env: Vec<String>,
    pub devices: Vec<String>,
    pub mounts: Vec<String>,
    pub base_create_json: String,
    /// Optional stable identifier used to derive per-app persistent state
    /// (`apps_state/<app_id>`). Falls back to `sanitize_title(title)` when
    /// unset. Callers use this to scope state per user (e.g.
    /// `<user_guid>-<game_guid>`) so concurrent users don't share
    /// `/home/retro` between sessions.
    pub app_id: Option<String>,
}

/// Information needed by the Docker runner to set up a container.
pub struct ContainerSession {
    pub session_id: String,
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    pub wayland_display: Option<String>,
    pub xdg_runtime_dir: String,
    pub audio_sink: Option<String>,
}

impl DockerRunner {
    pub fn new() -> Result<Self> {
        let socket = std::env::var("LIGHTRAYS_DOCKER_SOCKET")
            .unwrap_or_else(|_| "/var/run/docker.sock".to_string());
        let docker = Docker::connect_with_unix(&socket, 120, bollard::API_DEFAULT_VERSION)
            .context("Failed to connect to Docker")?;
        Ok(Self { docker })
    }

    /// Start an application container with Wayland, PulseAudio, and GPU passthrough.
    pub async fn start_container(
        &self,
        app: &ContainerConfig,
        session: &ContainerSession,
    ) -> Result<String> {
        let container_name = format!("{}{}", CONTAINER_PREFIX, session.session_id);

        log::info!(
            "Starting container: {} (image: {})",
            container_name,
            app.image
        );

        // Resolve host/container paths
        let host_xdg = std::env::var("LIGHTRAYS_HOST_XDG_RUNTIME_DIR")
            .unwrap_or_else(|_| session.xdg_runtime_dir.clone());
        let host_state_dir = std::env::var("LIGHTRAYS_HOST_STATE_DIR").unwrap_or_else(|_| {
            std::env::var("LIGHTRAYS_STATE_DIR").unwrap_or_else(|_| "/etc/lightrays".to_string())
        });
        let container_xdg = "/tmp/sockets";

        // Per-app state key — caller-supplied `app_id` takes precedence so
        // different users can run the same title without sharing
        // `/home/retro`. Falls back to the sanitized title for backwards
        // compatibility with clients that don't set app_id.
        let app_key = app
            .app_id
            .as_ref()
            .map(|s| sanitize_title(s))
            .filter(|s| !s.is_empty())
            .unwrap_or_else(|| sanitize_title(&app.title));
        let host_app_state = format!("{}/apps_state/{}", host_state_dir, app_key);

        let local_state_dir =
            std::env::var("LIGHTRAYS_STATE_DIR").unwrap_or_else(|_| "/etc/lightrays".to_string());
        let local_app_state = format!("{}/apps_state/{}", local_state_dir, app_key);
        tokio::fs::create_dir_all(&local_app_state).await?;
        tokio::fs::create_dir_all(&session.xdg_runtime_dir).await?;

        // Clean stale X11 sockets from previous sessions to prevent
        // "X server already running on display :0" errors
        let x11_dir = format!("{}/.X11-unix", session.xdg_runtime_dir);
        if tokio::fs::metadata(&x11_dir).await.is_ok() {
            let _ = tokio::fs::remove_dir_all(&x11_dir).await;
            log::info!("Cleaned stale X11 socket directory: {}", x11_dir);
        }
        for i in 0..10 {
            let lock = format!("{}/.X{}-lock", session.xdg_runtime_dir, i);
            let _ = tokio::fs::remove_file(&lock).await;
        }

        let env = build_container_env(app, session, container_xdg);
        let binds = build_volume_binds(&host_xdg, container_xdg, &host_app_state, &app.mounts);
        let devices = build_device_mappings(&app.devices);
        let (cap_add, security_opt, device_cgroup_rules, ipc_mode) =
            parse_host_config_overrides(&app.base_create_json);

        log::debug!("Container '{}' binds: {:?}", container_name, binds);
        log::debug!(
            "Container '{}' devices: {} entries",
            container_name,
            devices.len()
        );
        log::debug!(
            "Container '{}' cap_add: {:?}, security_opt: {:?}",
            container_name,
            cap_add,
            security_opt
        );

        // Ensure image is available
        self.ensure_image(&app.image).await?;

        // Remove stale container in the reserved lightrays namespace only.
        if let Err(e) = self
            .docker
            .remove_container(
                &container_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await
        {
            log::debug!(
                "Stale reserved container removal (expected if not present): {}",
                e
            );
        }

        // Create and start
        let host_config = HostConfig {
            binds: Some(binds),
            devices: if devices.is_empty() {
                None
            } else {
                Some(devices)
            },
            cap_add: if cap_add.is_empty() {
                None
            } else {
                Some(cap_add)
            },
            security_opt: if security_opt.is_empty() {
                None
            } else {
                Some(security_opt)
            },
            device_cgroup_rules: if device_cgroup_rules.is_empty() {
                None
            } else {
                Some(device_cgroup_rules)
            },
            ipc_mode,
            ..Default::default()
        };

        let config = Config {
            image: Some(app.image.clone()),
            env: Some(env),
            host_config: Some(host_config),
            ..Default::default()
        };

        self.docker
            .create_container(
                Some(CreateContainerOptions {
                    name: container_name.as_str(),
                    platform: None,
                }),
                config,
            )
            .await
            .map_err(|e| {
                log::error!("Docker create_container '{}' error: {e}", container_name);
                e
            })
            .context("Failed to create container")?;

        self.docker
            .start_container::<String>(&container_name, None)
            .await
            .context("Failed to start container")?;

        log::info!("Container started: {}", container_name);

        Ok(container_name)
    }

    /// Ensure a Docker image is available locally, pulling it if necessary.
    async fn ensure_image(&self, image: &str) -> Result<()> {
        if self.docker.inspect_image(image).await.is_ok() {
            return Ok(());
        }

        log::info!("Pulling image: {} (not found locally)", image);
        let (repo, tag) = if let Some((r, t)) = image.rsplit_once(':') {
            (r.to_string(), t.to_string())
        } else {
            (image.to_string(), "latest".to_string())
        };
        let options = CreateImageOptions {
            from_image: repo.as_str(),
            tag: tag.as_str(),
            ..Default::default()
        };
        let mut stream = self.docker.create_image(Some(options), None, None);
        while let Some(result) = stream.next().await {
            match result {
                Ok(info) => {
                    if let Some(status) = info.status {
                        log::debug!("Pull: {}", status);
                    }
                }
                Err(e) => {
                    log::error!("Failed to pull image '{}': {e}", image);
                    anyhow::bail!("Failed to pull image '{}': {e}", image);
                }
            }
        }
        log::info!("Image pulled successfully: {}", image);
        Ok(())
    }

    /// Wait for a container to exit and return its exit code.
    pub async fn wait_for_exit(&self, container_name: &str) -> i64 {
        let mut stream = self.docker.wait_container::<String>(container_name, None);
        if let Some(result) = stream.next().await {
            match result {
                Ok(r) => {
                    log::info!(
                        "Container {} exited with code {}",
                        container_name,
                        r.status_code
                    );
                    r.status_code
                }
                Err(e) => {
                    log::warn!(
                        "wait_container error for {}: {} (container may have been removed)",
                        container_name,
                        e
                    );
                    -1
                }
            }
        } else {
            log::warn!(
                "wait_container stream ended without result for {}",
                container_name
            );
            -1
        }
    }

    /// Capture and log the last N lines from a container's logs.
    pub async fn dump_container_logs(&self, container_name: &str, tail_lines: usize) {
        let enabled = std::env::var("LIGHTRAYS_DUMP_CONTAINER_LOGS")
            .map(|v| v.eq_ignore_ascii_case("true") || v == "1")
            .unwrap_or(false);
        if !enabled {
            log::warn!(
                "Container {} exited; log dump suppressed (set LIGHTRAYS_DUMP_CONTAINER_LOGS=true to enable)",
                container_name
            );
            return;
        }

        let options = LogsOptions::<String> {
            stdout: true,
            stderr: true,
            tail: tail_lines.to_string(),
            ..Default::default()
        };
        let mut stream = self.docker.logs(container_name, Some(options));
        let mut lines = Vec::new();
        while let Some(Ok(chunk)) = stream.next().await {
            lines.push(chunk.to_string());
        }
        if lines.is_empty() {
            log::warn!("Container {} produced no logs", container_name);
        } else {
            log::warn!(
                "=== Last {} log lines from container {} ===",
                lines.len(),
                container_name
            );
            for line in &lines {
                log::warn!("  {}: {}", container_name, redact_log_line(line.trim_end()));
            }
            log::warn!("=== End container logs ===");
        }
    }

    /// Stop and remove a container.
    pub async fn stop_container(&self, container_name: &str) -> Result<()> {
        if let Err(e) = self
            .docker
            .stop_container(container_name, Some(StopContainerOptions { t: 10 }))
            .await
        {
            log::warn!(
                "Failed to stop container {}: {} (may already be stopped)",
                container_name,
                e
            );
        }
        if let Err(e) = self
            .docker
            .remove_container(
                container_name,
                Some(RemoveContainerOptions {
                    force: true,
                    ..Default::default()
                }),
            )
            .await
        {
            log::warn!("Failed to remove container {}: {}", container_name, e);
        }
        log::info!("Container stopped: {}", container_name);
        Ok(())
    }

    /// Get a single stats snapshot for a container (CPU + memory).
    pub async fn get_container_stats(&self, container_name: &str) -> Result<ContainerStats> {
        let options = StatsOptions {
            stream: false, // single snapshot
            one_shot: true,
        };
        let mut stream = self.docker.stats(container_name, Some(options));

        if let Some(result) = stream.next().await {
            let stats = result.context("Failed to get container stats")?;

            // Memory
            let mem_usage = stats.memory_stats.usage.unwrap_or(0);
            let mem_limit = stats.memory_stats.limit.unwrap_or(0);
            // Subtract cache from usage for a more accurate "working set" value
            let cache = stats
                .memory_stats
                .stats
                .as_ref()
                .map(|s| match s {
                    bollard::container::MemoryStatsStats::V1(v1) => v1.cache,
                    bollard::container::MemoryStatsStats::V2(v2) => v2.inactive_file,
                })
                .unwrap_or(0);
            let mem_used = mem_usage.saturating_sub(cache);

            // CPU — delta calculation
            let cpu_delta = stats
                .cpu_stats
                .cpu_usage
                .total_usage
                .saturating_sub(stats.precpu_stats.cpu_usage.total_usage);
            let system_delta = stats
                .cpu_stats
                .system_cpu_usage
                .unwrap_or(0)
                .saturating_sub(stats.precpu_stats.system_cpu_usage.unwrap_or(0));
            let num_cpus = stats.cpu_stats.online_cpus.unwrap_or(1);

            let cpu_percent = if system_delta > 0 {
                (cpu_delta as f64 / system_delta as f64) * num_cpus as f64 * 100.0
            } else {
                0.0
            };

            Ok(ContainerStats {
                cpu_percent,
                mem_used,
                mem_limit,
            })
        } else {
            anyhow::bail!("No stats received for container {}", container_name)
        }
    }

    /// Stop and remove orphaned Lightrays containers.
    ///
    /// Lists every container (running or stopped) whose name matches the
    /// reserved [`CONTAINER_PREFIX`] and removes the ones that are *not* in
    /// `active`. `active` is the set of container names owned by live
    /// in-memory sessions. On a fresh start this set is empty, so every
    /// `lightrays-*` container left behind by a crashed previous process is
    /// reaped.
    ///
    /// `min_age_secs` protects against racing a concurrent launch: when
    /// greater than zero, containers created more recently than that are
    /// left alone (a container is created a fraction of a second before it
    /// is registered in the session map). Pass `0` at startup, where no
    /// launches can be in flight yet.
    ///
    /// Best-effort: a failure to list or remove is logged and swallowed so
    /// the caller (startup path or reaper) never aborts. Returns the number
    /// of orphaned containers removed.
    pub async fn sweep_orphan_containers(&self, active: &HashSet<String>, min_age_secs: i64) -> usize {
        let options = ListContainersOptions::<String> {
            all: true,
            ..Default::default()
        };
        let containers = match self.docker.list_containers(Some(options)).await {
            Ok(c) => c,
            Err(e) => {
                log::warn!("Orphan sweep: failed to list containers: {e:#}");
                return 0;
            }
        };

        let now = std::time::SystemTime::now()
            .duration_since(std::time::UNIX_EPOCH)
            .map(|d| d.as_secs() as i64)
            .unwrap_or(0);

        let mut removed = 0;
        for c in containers {
            // Docker returns names with a leading '/'. Only consider names
            // in the reserved lightrays namespace.
            let name = match c.names.as_ref().and_then(|names| {
                names.iter().find_map(|n| {
                    let n = n.strip_prefix('/').unwrap_or(n);
                    if n.starts_with(CONTAINER_PREFIX) {
                        Some(n.to_string())
                    } else {
                        None
                    }
                })
            }) {
                Some(n) => n,
                None => continue,
            };

            if active.contains(&name) {
                continue;
            }

            if min_age_secs > 0 {
                if let Some(created) = c.created {
                    let age = now.saturating_sub(created);
                    if age < min_age_secs {
                        log::debug!(
                            "Orphan sweep: skipping recently-created container {name} (age {age}s)"
                        );
                        continue;
                    }
                }
            }

            log::warn!("Orphan sweep: removing orphaned lightrays container {name}");
            let _ = self.stop_container(&name).await;
            removed += 1;
        }
        removed
    }
}

/// Snapshot of container resource usage.
#[derive(serde::Serialize)]
pub struct ContainerStats {
    /// CPU usage as a percentage (e.g. 25.3 means 25.3% of all cores).
    pub cpu_percent: f64,
    /// Memory currently used in bytes (excluding cache).
    pub mem_used: u64,
    /// Memory limit in bytes.
    pub mem_limit: u64,
}

#[async_trait]
impl Runtime for DockerRunner {
    async fn ping(&self) -> Result<()> {
        self.docker.ping().await.context("Docker ping failed")?;
        Ok(())
    }

    async fn start(&self, config: &ContainerConfig, session: &ContainerSession) -> Result<String> {
        self.start_container(config, session).await
    }

    async fn wait_for_exit(&self, name: &str) -> i64 {
        DockerRunner::wait_for_exit(self, name).await
    }

    async fn dump_logs(&self, name: &str, tail_lines: usize) {
        self.dump_container_logs(name, tail_lines).await;
    }

    async fn stop(&self, name: &str) -> Result<()> {
        self.stop_container(name).await
    }

    async fn stats(&self, name: &str) -> Result<ContainerStats> {
        self.get_container_stats(name).await
    }

    async fn reconcile_orphans(&self, active: &HashSet<String>, min_age_secs: i64) -> usize {
        self.sweep_orphan_containers(active, min_age_secs).await
    }
}

/// Sanitize a title for use as a filesystem directory name.
pub(crate) fn sanitize_title(title: &str) -> String {
    title
        .chars()
        .map(|c| {
            if c.is_alphanumeric() || c == '-' || c == '_' {
                c
            } else {
                '_'
            }
        })
        .collect()
}

/// Build the container environment variables map.
pub(crate) fn build_container_env(
    app: &ContainerConfig,
    session: &ContainerSession,
    container_xdg: &str,
) -> Vec<String> {
    let mut environment: HashMap<String, String> = HashMap::new();
    for item in &app.env {
        if let Some((k, v)) = item.split_once('=') {
            environment.insert(k.to_string(), v.to_string());
        }
    }

    environment.insert("XDG_RUNTIME_DIR".into(), container_xdg.into());
    environment.insert("PUID".into(), "1000".into());
    environment.insert("PGID".into(), "1000".into());

    if let Some(ref wl) = session.wayland_display {
        environment.insert("WAYLAND_DISPLAY".into(), wl.clone());
        environment.insert("REAL_WAYLAND_DISPLAY".into(), wl.clone());
    }

    environment.insert("GAMESCOPE_WIDTH".into(), session.width.to_string());
    environment.insert("GAMESCOPE_HEIGHT".into(), session.height.to_string());
    environment.insert("GAMESCOPE_REFRESH".into(), session.fps.to_string());

    environment
        .entry("DISPLAY".into())
        .or_insert_with(|| ":99".into());
    environment.insert(
        "RESOLUTION".into(),
        format!("{}x{}x24", session.width, session.height),
    );
    environment
        .entry("VNC_PORT".into())
        .or_insert_with(|| "5900".into());

    if let Some(ref audio_sink) = session.audio_sink {
        environment.insert("PULSE_SINK".into(), audio_sink.clone());
        environment.insert("PULSE_SOURCE".into(), format!("{}.monitor", audio_sink));
        let pulse_server = std::env::var("LIGHTRAYS_PULSE_SERVER").unwrap_or_default();
        if !pulse_server.is_empty() {
            environment.insert(
                "PULSE_SERVER".into(),
                format!("unix:{}/pulse/native", container_xdg),
            );
        }
    }

    environment
        .iter()
        .map(|(k, v)| format!("{k}={v}"))
        .collect()
}

fn redact_log_line(line: &str) -> String {
    let mut redacted = Vec::new();
    for token in line.split_whitespace() {
        let upper = token.to_ascii_uppercase();
        if upper.contains("PASSWORD=")
            || upper.contains("TOKEN=")
            || upper.contains("SECRET=")
            || upper.contains("CREDENTIAL=")
            || upper.contains("API_KEY=")
        {
            if let Some((key, _)) = token.split_once('=') {
                redacted.push(format!("{key}=<redacted>"));
            } else {
                redacted.push("<redacted>".to_string());
            }
        } else {
            redacted.push(token.to_string());
        }
    }
    redacted.join(" ")
}

/// Build volume bind mount strings.
fn build_volume_binds(
    host_xdg: &str,
    container_xdg: &str,
    host_app_state: &str,
    extra_mounts: &[String],
) -> Vec<String> {
    let mut binds = vec![
        format!("{host_xdg}:{container_xdg}:rw"),
        format!("{host_app_state}:/home/retro:rw"),
    ];
    for mount in extra_mounts {
        binds.push(mount.clone());
    }
    binds
}

/// Build device mappings from user config + auto-detect /dev/dri devices.
fn build_device_mappings(user_devices: &[String]) -> Vec<DeviceMapping> {
    let mut devices = Vec::new();
    for dev_str in user_devices {
        if let Some(dm) = parse_device_mapping(dev_str) {
            devices.push(dm);
        }
    }

    // Auto-add /dev/dri devices
    if let Ok(entries) = std::fs::read_dir("/dev/dri") {
        for entry in entries.flatten() {
            let path = entry.path();
            if path
                .metadata()
                .map(|m| m.file_type().is_char_device())
                .unwrap_or(false)
            {
                let p = path.to_string_lossy().to_string();
                devices.push(DeviceMapping {
                    path_on_host: Some(p.clone()),
                    path_in_container: Some(p),
                    cgroup_permissions: Some("rwm".into()),
                });
            }
        }
    }
    devices
}

/// Parse HostConfig overrides from base_create_json.
/// Returns (cap_add, security_opt, device_cgroup_rules, ipc_mode).
fn parse_host_config_overrides(
    base_create_json: &str,
) -> (Vec<String>, Vec<String>, Vec<String>, Option<String>) {
    let mut cap_add = Vec::new();
    let mut security_opt = Vec::new();
    let mut device_cgroup_rules = Vec::new();
    let mut ipc_mode = Some("host".to_string());

    if !base_create_json.is_empty() {
        if let Ok(bcj) = serde_json::from_str::<serde_json::Value>(base_create_json) {
            if let Some(hc) = bcj.get("HostConfig") {
                if let Some(caps) = hc.get("CapAdd").and_then(|v| v.as_array()) {
                    cap_add = caps
                        .iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect();
                }
                if let Some(secs) = hc.get("SecurityOpt").and_then(|v| v.as_array()) {
                    security_opt = secs
                        .iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect();
                }
                if let Some(rules) = hc.get("DeviceCgroupRules").and_then(|v| v.as_array()) {
                    device_cgroup_rules = rules
                        .iter()
                        .filter_map(|v| v.as_str().map(String::from))
                        .collect();
                }
                if let Some(ipc) = hc.get("IpcMode").and_then(|v| v.as_str()) {
                    ipc_mode = Some(ipc.to_string());
                }
            }
        } else {
            log::warn!("Failed to parse base_create_json");
        }
    }

    (cap_add, security_opt, device_cgroup_rules, ipc_mode)
}

fn parse_device_mapping(s: &str) -> Option<DeviceMapping> {
    let parts: Vec<&str> = s.split(':').collect();
    if parts.len() >= 2 {
        Some(DeviceMapping {
            path_on_host: Some(parts[0].to_string()),
            path_in_container: Some(parts[1].to_string()),
            cgroup_permissions: Some(parts.get(2).unwrap_or(&"rwm").to_string()),
        })
    } else {
        None
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redacts_sensitive_log_tokens() {
        let line = "TOKEN=abc ok PASSWORD=secret API_KEY=123";
        let redacted = redact_log_line(line);
        assert!(redacted.contains("TOKEN=<redacted>"));
        assert!(redacted.contains("PASSWORD=<redacted>"));
        assert!(redacted.contains("API_KEY=<redacted>"));
        assert!(!redacted.contains("secret"));
    }

    #[test]
    fn sanitize_title_keeps_safe_chars() {
        assert_eq!(sanitize_title("User-1_Game.2"), "User-1_Game_2");
    }
}
