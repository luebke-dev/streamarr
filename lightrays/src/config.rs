//! Configuration for lightrays — loaded entirely from environment variables.

use anyhow::{bail, Result};

/// Selector for the container runtime backend. Docker is the default
/// laptop/local path; Kubernetes is the in-cluster path that uses a
/// ServiceAccount instead of mounting the host Docker socket.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum RuntimeBackend {
    Docker,
    Kubernetes,
}

/// Server configuration, read from environment variables.
#[derive(Debug, Clone)]
pub struct ServerConfig {
    /// Which backend spawns the session workloads.
    pub runtime_backend: RuntimeBackend,
    /// Namespace the Kubernetes runtime spawns session pods into.
    pub k8s_session_namespace: String,
    /// Node selector applied to spawned session pods (kept as raw JSON
    /// so users can drop in vendor-specific keys like
    /// `nvidia.com/gpu.product`).
    pub k8s_session_node_selector: String,
    pub hostname: String,
    /// Bind address for the management API and WebSocket endpoint.
    pub api_bind_addr: String,
    /// Port for the management API (`/api/launch`, `/api/stop`).
    pub api_port: u16,
    /// Bind address for the dedicated WebSocket streaming listener.
    pub streaming_bind_addr: String,
    /// Port for WebSocket streaming (`/ws/:session_id`).
    pub streaming_port: u16,
    /// Bind address for Prometheus metrics. Defaults to localhost.
    pub metrics_bind_addr: String,
    /// Port for Prometheus metrics (`/metrics`).
    pub metrics_port: u16,
    pub stun_server: String,
    pub turn_server: String,
    pub turn_username: String,
    pub turn_password: String,
    /// Allowed CORS origins.  Each entry is a full origin string, e.g.
    /// `https://pyrate.example.com`.  The special value `*` permits any origin.
    /// Multiple origins are separated by commas.
    /// Defaults to `*` (allow all) when the variable is unset.
    pub cors_origins: Vec<String>,
    /// Shared secret for JWT verification (HS256).  When set, all API and
    /// WebSocket endpoints require a valid Bearer token or a short-lived
    /// ticket passed through `Sec-WebSocket-Protocol`. When empty, auth is disabled
    /// unless `LIGHTRAYS_AUTH_DISABLED=true` is explicitly set.
    pub jwt_secret: String,
    /// Maximum idle session lifetime in seconds (0 = disabled).
    pub session_timeout_secs: u64,
    /// Grace period after WebSocket disconnect before the session is stopped.
    pub reconnect_grace_secs: u64,
    /// Short-lived WebSocket ticket lifetime in seconds.
    pub ws_ticket_ttl_secs: u64,
    /// Server-side image used by the built-in Games on Whales Steam profile.
    pub gow_image: String,
    /// In-container compositor for the GOW profile: `gamescope` (default,
    /// pins the resolution at launch) or `sway` (a real WM whose output can
    /// be resized live via `swaymsg`, so the Steam UI re-lays-out).
    pub gow_compositor: String,
    /// Registry hosts a client-supplied `docker_image` override may pull
    /// from. Empty disables the check. Defaults to the registry host of
    /// `gow_image`. (S-C1)
    pub allowed_registries: Vec<String>,
    /// Absolute host-path prefixes under which an admin-gated `app_mounts`
    /// bind may expose a host directory (e.g. a Wine game folder) inside the
    /// privileged `gow-app` container. An **empty** list disables the feature
    /// entirely (fail-closed): no `app_mounts` are accepted. Set via
    /// `LIGHTRAYS_ALLOWED_MOUNT_PREFIXES` (comma-separated). (S-C1)
    pub allowed_mount_prefixes: Vec<String>,
    /// Expected JWT audience (`aud`). When non-empty, tokens must carry a
    /// matching `aud` claim. Empty disables audience validation. (S-M3)
    pub jwt_audience: String,
    /// Maximum number of concurrent sessions across all users (0 = unlimited).
    pub max_sessions_global: usize,
    /// Maximum number of concurrent sessions per authenticated user
    /// (`owner_sub`) (0 = unlimited).
    pub max_sessions_per_user: usize,
}

impl ServerConfig {
    /// Build config from environment variables with sensible defaults.
    pub fn from_env() -> Result<Self> {
        let cors_origins = std::env::var("LIGHTRAYS_CORS_ORIGINS")
            .unwrap_or_else(|_| "*".into())
            .split(',')
            .map(|s| s.trim().to_string())
            .filter(|s| !s.is_empty())
            .collect();

        let jwt_secret = std::env::var("LIGHTRAYS_JWT_SECRET").unwrap_or_default();

        let runtime_backend = match std::env::var("LIGHTRAYS_RUNTIME")
            .unwrap_or_else(|_| "docker".into())
            .to_lowercase()
            .as_str()
        {
            "docker" => RuntimeBackend::Docker,
            "kubernetes" | "k8s" => RuntimeBackend::Kubernetes,
            other => bail!(
                "LIGHTRAYS_RUNTIME={other:?} is not recognised; expected one of: docker, kubernetes"
            ),
        };

        // JWT auth is required by default. To disable, set LIGHTRAYS_AUTH_DISABLED=true.
        if jwt_secret.is_empty() {
            let auth_disabled = std::env::var("LIGHTRAYS_AUTH_DISABLED")
                .map(|v| v.eq_ignore_ascii_case("true") || v == "1")
                .unwrap_or(false);
            if !auth_disabled {
                bail!(
                    "LIGHTRAYS_JWT_SECRET is not set and auth is required. \
                     Set LIGHTRAYS_JWT_SECRET to enable JWT authentication, \
                     or set LIGHTRAYS_AUTH_DISABLED=true to explicitly disable auth."
                );
            }
        }

        let gow_image = std::env::var("LIGHTRAYS_GOW_IMAGE")
            .or_else(|_| std::env::var("LIGHTRAYS_DEFAULT_IMAGE"))
            .unwrap_or_else(|_| "ghcr.io/games-on-whales/steam:edge".into());

        // Registry allowlist for client image overrides. Default: the
        // registry host of the configured GOW image, so overrides can only
        // pull from the same trusted registry unless an operator widens it.
        let allowed_registries: Vec<String> = std::env::var("LIGHTRAYS_ALLOWED_REGISTRIES")
            .ok()
            .map(|v| {
                v.split(',')
                    .map(|s| s.trim().to_string())
                    .filter(|s| !s.is_empty())
                    .collect()
            })
            .unwrap_or_else(|| vec![crate::launch::image_registry_host(&gow_image)]);

        // Host-path prefixes that admin-gated app_mounts may bind from. Empty
        // (the default) keeps the feature off — fail-closed.
        let allowed_mount_prefixes: Vec<String> =
            std::env::var("LIGHTRAYS_ALLOWED_MOUNT_PREFIXES")
                .ok()
                .map(|v| {
                    v.split(',')
                        .map(|s| s.trim().to_string())
                        .filter(|s| !s.is_empty())
                        .collect()
                })
                .unwrap_or_default();

        let config = Self {
            runtime_backend,
            k8s_session_namespace: std::env::var("LIGHTRAYS_K8S_SESSION_NAMESPACE")
                .unwrap_or_else(|_| "lightrays-sessions".into()),
            k8s_session_node_selector: std::env::var("LIGHTRAYS_K8S_SESSION_NODE_SELECTOR")
                .unwrap_or_default(),
            hostname: std::env::var("LIGHTRAYS_HOSTNAME").unwrap_or_else(|_| "Lightrays".into()),
            api_bind_addr: std::env::var("LIGHTRAYS_API_BIND_ADDR")
                .unwrap_or_else(|_| "0.0.0.0".into()),
            api_port: std::env::var("LIGHTRAYS_API_PORT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(8080),
            streaming_bind_addr: std::env::var("LIGHTRAYS_STREAMING_BIND_ADDR")
                .unwrap_or_else(|_| "0.0.0.0".into()),
            streaming_port: std::env::var("LIGHTRAYS_STREAMING_PORT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(8081),
            metrics_bind_addr: std::env::var("LIGHTRAYS_METRICS_BIND_ADDR")
                .unwrap_or_else(|_| "127.0.0.1".into()),
            metrics_port: std::env::var("LIGHTRAYS_METRICS_PORT")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(9090),
            stun_server: std::env::var("LIGHTRAYS_STUN_SERVER")
                .unwrap_or_else(|_| "stun://stun.l.google.com:19302".into()),
            turn_server: std::env::var("LIGHTRAYS_TURN_SERVER").unwrap_or_default(),
            turn_username: std::env::var("LIGHTRAYS_TURN_USERNAME").unwrap_or_default(),
            turn_password: std::env::var("LIGHTRAYS_TURN_PASSWORD").unwrap_or_default(),
            cors_origins,
            jwt_secret,
            session_timeout_secs: std::env::var("LIGHTRAYS_SESSION_TIMEOUT_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(3600),
            reconnect_grace_secs: std::env::var("LIGHTRAYS_RECONNECT_GRACE_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(30),
            ws_ticket_ttl_secs: std::env::var("LIGHTRAYS_WS_TICKET_TTL_SECS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(120),
            gow_image,
            gow_compositor: std::env::var("LIGHTRAYS_GOW_COMPOSITOR")
                .unwrap_or_else(|_| "gamescope".into())
                .to_ascii_lowercase(),
            allowed_registries,
            allowed_mount_prefixes,
            jwt_audience: std::env::var("LIGHTRAYS_JWT_AUDIENCE")
                .unwrap_or_else(|_| "lightrays".into()),
            max_sessions_global: std::env::var("LIGHTRAYS_MAX_SESSIONS")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(0),
            max_sessions_per_user: std::env::var("LIGHTRAYS_MAX_SESSIONS_PER_USER")
                .ok()
                .and_then(|v| v.parse().ok())
                .unwrap_or(0),
        };

        config.validate()?;
        Ok(config)
    }

    /// Validate configuration and log warnings for common misconfigurations.
    fn validate(&self) -> Result<()> {
        let ports = [
            ("api", self.api_port),
            ("streaming", self.streaming_port),
            ("metrics", self.metrics_port),
        ];
        // Check for port conflicts
        for i in 0..ports.len() {
            for j in (i + 1)..ports.len() {
                if ports[i].1 == ports[j].1 {
                    bail!(
                        "Port conflict: {} and {} both use port {}",
                        ports[i].0,
                        ports[j].0,
                        ports[i].1
                    );
                }
            }
        }
        // Check for port 0
        for (name, port) in &ports {
            if *port == 0 {
                bail!("Invalid port 0 for {} server", name);
            }
        }
        if self.gow_image.trim().is_empty() {
            bail!("LIGHTRAYS_GOW_IMAGE must not be empty");
        }
        Ok(())
    }
}
