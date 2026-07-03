//! Launch request validation, runtime-profile resolution, and ICE-server
//! assembly.
//!
//! The HTTP handler in `server.rs` deserialises an untrusted
//! `LaunchRequest` from the client, hands it to [`validate_launch_request`]
//! to produce a typed [`ValidatedLaunch`], and then asks
//! [`build_container_config`] for a server-resolved container spec. None
//! of the host-sensitive Docker fields (image, mounts, devices, …) flow
//! through the client; they're decided here from the runtime profile.

use crate::config::ServerConfig;
use crate::docker::ContainerConfig;

use std::collections::HashMap;

use axum::{http::StatusCode, Json};
use serde::Deserialize;

pub type JsonError = (StatusCode, Json<serde_json::Value>);

#[derive(Deserialize)]
pub struct LaunchRequest {
    // Stream settings
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub fps: Option<u32>,
    pub bitrate_kbps: Option<u32>,
    // App / runtime profile config
    pub title: Option<String>,
    pub runtime_profile: Option<String>,
    pub docker_image: Option<String>,
    pub keyboard_layout: Option<String>,
    pub mouse_speed: Option<f64>,
    /// Sanctioned, admin-controlled application/profile environment. Unlike
    /// the deprecated raw `env` field below (which is rejected outright),
    /// `app_env` is a curated key/value map merged into the container env for
    /// the generic `gow-app` runtime profile. It is set via the Docker API
    /// (no shell), so there is no injection surface, and the lightrays-managed
    /// streaming-contract variables always take precedence over it.
    pub app_env: Option<HashMap<String, String>>,
    // Deprecated unsafe raw Docker fields. They are still deserialized so the
    // server can reject them explicitly instead of silently ignoring them.
    pub image: Option<String>,
    pub container_name: Option<String>,
    pub env: Option<Vec<String>>,
    pub devices: Option<Vec<String>>,
    pub mounts: Option<Vec<String>>,
    pub base_create_json: Option<String>,
    /// Stable per-app state identifier. Used as the `apps_state/<app_id>`
    /// subdirectory so concurrent users sharing the same title don't step
    /// on each other's `/home/retro`. Caller convention:
    /// `<user_guid>-<game_guid>`.
    pub app_id: Option<String>,
    // Pipeline config
    pub start_virtual_compositor: Option<bool>,
    pub start_audio_server: Option<bool>,
    pub render_node: Option<String>,
}

pub struct ValidatedLaunch {
    pub width: u32,
    pub height: u32,
    pub fps: u32,
    pub bitrate_kbps: u32,
    pub title: String,
    pub app_id: Option<String>,
    pub runtime_profile: String,
    pub docker_image: Option<String>,
    pub keyboard_layout: String,
    /// Validated sanctioned app environment (empty keys dropped). Merged into
    /// the container env for the `gow-app` profile; ignored otherwise.
    pub app_env: HashMap<String, String>,
    pub start_compositor: bool,
    pub start_audio: bool,
    pub render_node: String,
}

const MIN_WIDTH: u32 = 64;
const MAX_WIDTH: u32 = 7680;
const MIN_HEIGHT: u32 = 64;
const MAX_HEIGHT: u32 = 4320;
const MIN_FPS: u32 = 15;
const MAX_FPS: u32 = 120;
const MIN_BITRATE_KBPS: u32 = 500;
const MAX_BITRATE_KBPS: u32 = 50_000;

pub fn validate_launch_request(req: &LaunchRequest) -> Result<ValidatedLaunch, JsonError> {
    reject_raw_docker_fields(req)?;

    let width = validate_range("width", req.width.unwrap_or(1920), MIN_WIDTH, MAX_WIDTH)?;
    let height = validate_range("height", req.height.unwrap_or(1080), MIN_HEIGHT, MAX_HEIGHT)?;
    let fps = validate_range("fps", req.fps.unwrap_or(60), MIN_FPS, MAX_FPS)?;
    let bitrate_kbps = validate_range(
        "bitrate_kbps",
        req.bitrate_kbps.unwrap_or(5000),
        MIN_BITRATE_KBPS,
        MAX_BITRATE_KBPS,
    )?;

    let title = req
        .title
        .clone()
        .unwrap_or_else(|| "Untitled".into())
        .trim()
        .to_string();
    if title.is_empty() || title.len() > 128 {
        return Err(bad_request("title must be 1..128 characters"));
    }

    let app_id = match req.app_id.as_ref() {
        Some(value) => {
            let value = value.trim();
            if value.is_empty()
                || value.len() > 160
                || !value
                    .chars()
                    .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_' || c == '.')
            {
                return Err(bad_request(
                    "app_id must be 1..160 ASCII letters, digits, dash, underscore, or dot",
                ));
            }
            Some(value.to_string())
        }
        None => None,
    };

    let runtime_profile = req
        .runtime_profile
        .clone()
        .unwrap_or_else(|| "gow-steam".into());
    if !matches!(runtime_profile.as_str(), "gow-steam" | "gow-app" | "none") {
        return Err(bad_request("unsupported runtime_profile"));
    }

    let docker_image = match req.docker_image.as_ref() {
        Some(value) => Some(validate_docker_image(value)?),
        None => None,
    };
    if runtime_profile == "none" && docker_image.is_some() {
        return Err(bad_request(
            "docker_image is only supported for the gow-steam and gow-app runtime_profiles",
        ));
    }

    // Sanctioned app environment: keep only non-empty keys. Values may be any
    // string; there is no shell involved (set via the Docker API), so no
    // escaping is required. The map is only merged for the `gow-app` profile.
    let app_env: HashMap<String, String> = req
        .app_env
        .as_ref()
        .map(|m| {
            m.iter()
                .filter(|(k, _)| !k.trim().is_empty())
                .map(|(k, v)| (k.clone(), v.clone()))
                .collect()
        })
        .unwrap_or_default();

    let keyboard_layout = req
        .keyboard_layout
        .clone()
        .unwrap_or_else(|| "us".into())
        .trim()
        .to_string();
    if keyboard_layout.is_empty()
        || keyboard_layout.len() > 32
        || !keyboard_layout
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_')
    {
        return Err(bad_request("invalid keyboard_layout"));
    }

    if let Some(mouse_speed) = req.mouse_speed {
        if !(0.1..=5.0).contains(&mouse_speed) {
            return Err(bad_request("mouse_speed must be between 0.1 and 5.0"));
        }
    }

    let render_node = req
        .render_node
        .clone()
        .unwrap_or_else(|| "/dev/dri/renderD128".into());
    validate_render_node(&render_node)?;

    Ok(ValidatedLaunch {
        width,
        height,
        fps,
        bitrate_kbps,
        title,
        app_id,
        runtime_profile,
        docker_image,
        keyboard_layout,
        app_env,
        start_compositor: req.start_virtual_compositor.unwrap_or(true),
        start_audio: req.start_audio_server.unwrap_or(true),
        render_node,
    })
}

fn reject_raw_docker_fields(req: &LaunchRequest) -> Result<(), JsonError> {
    if req.image.is_some()
        || req.container_name.is_some()
        || req.env.is_some()
        || req.devices.is_some()
        || req.mounts.is_some()
        || req.base_create_json.is_some()
    {
        return Err(bad_request(
            "raw Docker launch fields are disabled; use runtime_profile",
        ));
    }
    Ok(())
}

fn validate_range(name: &str, value: u32, min: u32, max: u32) -> Result<u32, JsonError> {
    if value < min || value > max {
        Err(bad_request(&format!(
            "{name} must be between {min} and {max}"
        )))
    } else {
        Ok(value)
    }
}

fn validate_render_node(value: &str) -> Result<(), JsonError> {
    if value == "software" {
        return Ok(());
    }
    let rest = value.strip_prefix("/dev/dri/renderD").ok_or_else(|| {
        bad_request("render_node must be software or an allowlisted /dev/dri/renderD* path")
    })?;
    if rest.is_empty() || !rest.chars().all(|c| c.is_ascii_digit()) {
        return Err(bad_request(
            "render_node must be software or an allowlisted /dev/dri/renderD* path",
        ));
    }
    Ok(())
}

fn validate_docker_image(value: &str) -> Result<String, JsonError> {
    let image = value.trim();
    if image.is_empty() || image.len() > 255 {
        return Err(bad_request("docker_image must be 1..255 characters"));
    }
    if image.starts_with('-')
        || image.starts_with('/')
        || image.starts_with(':')
        || image.ends_with('/')
        || image.contains("//")
        || image.contains("..")
    {
        return Err(bad_request("invalid docker_image"));
    }
    if !image
        .chars()
        .all(|c| c.is_ascii_alphanumeric() || matches!(c, '.' | '_' | '-' | '/' | ':' | '@'))
    {
        return Err(bad_request("invalid docker_image"));
    }
    Ok(image.to_string())
}

/// Extract the registry host from an image reference following Docker's
/// convention: the first path segment is a registry host only when it
/// contains a `.` or `:` or is exactly `localhost`; otherwise the image
/// lives on Docker Hub (`docker.io`).
pub fn image_registry_host(image: &str) -> String {
    let first = image.split('/').next().unwrap_or("");
    if first.contains('.') || first.contains(':') || first == "localhost" {
        first.to_string()
    } else {
        "docker.io".to_string()
    }
}

/// Enforce a registry allowlist on a client-supplied image override. An
/// empty allowlist disables the check (registry pinning off). Returns a
/// 403 when the image's registry host is not allowed. (S-C1)
pub fn validate_image_registry(image: &str, allowed: &[String]) -> Result<(), JsonError> {
    if allowed.is_empty() {
        return Ok(());
    }
    let host = image_registry_host(image);
    if allowed.iter().any(|a| a == &host) {
        Ok(())
    } else {
        Err(forbidden(&format!(
            "image registry '{host}' is not in LIGHTRAYS_ALLOWED_REGISTRIES"
        )))
    }
}

pub fn bad_request(message: &str) -> JsonError {
    (
        StatusCode::BAD_REQUEST,
        Json(serde_json::json!({ "error": message })),
    )
}

pub fn forbidden(message: &str) -> JsonError {
    (
        StatusCode::FORBIDDEN,
        Json(serde_json::json!({ "error": message })),
    )
}

pub fn build_container_config(
    config: &ServerConfig,
    launch: &ValidatedLaunch,
    owner_sub: &str,
) -> Result<Option<ContainerConfig>, JsonError> {
    match launch.runtime_profile.as_str() {
        "none" => Ok(None),
        // The established Steam profile does not merge any extra app env; it
        // shares the exact same builder as `gow-app` with an empty overlay,
        // so its behaviour is byte-for-byte identical to before.
        "gow-steam" => Ok(Some(build_gow_container_config(
            config,
            launch,
            owner_sub,
            &HashMap::new(),
        ))),
        // Generic, GOW-agnostic profile: same privileged base + streaming
        // contract as gow-steam, but additionally merges the sanctioned
        // `app_env` (e.g. a Steam AppID) into the container env.
        "gow-app" => Ok(Some(build_gow_container_config(
            config,
            launch,
            owner_sub,
            &launch.app_env,
        ))),
        _ => Err(bad_request("unsupported runtime_profile")),
    }
}

/// Build the GOW container spec shared by the `gow-steam` and `gow-app`
/// profiles. `app_env` is an optional sanctioned overlay merged FIRST; the
/// lightrays-managed streaming-contract variables are applied afterwards so
/// they always win and `app_env` can never break the stream contract.
fn build_gow_container_config(
    config: &ServerConfig,
    launch: &ValidatedLaunch,
    owner_sub: &str,
    app_env: &HashMap<String, String>,
) -> ContainerConfig {
    // Ordered key/value list so env output is deterministic and duplicate-free.
    let mut env: Vec<(String, String)> = Vec::new();

    // 1. Sanctioned app env goes in first (sorted for a stable ordering).
    let mut app_keys: Vec<&String> = app_env.keys().collect();
    app_keys.sort();
    for key in app_keys {
        if key.trim().is_empty() {
            continue;
        }
        env_set(&mut env, key, &app_env[key]);
    }

    // 2. lightrays-managed streaming contract overrides anything above.
    env_set(
        &mut env,
        "GOW_REQUIRED_DEVICES",
        "/dev/dri/* /dev/nvidia*",
    );
    env_set(
        &mut env,
        "XKB_DEFAULT_LAYOUT",
        &launch.keyboard_layout,
    );
    // In-container compositor. gamescope (default) pins the resolution at
    // launch, so the whole session is fixed-size; sway is a real WM, so the
    // Steam UI re-lays-out live when its output resolution changes (games can
    // still run in a per-game gamescope via Steam launch options). Both reuse
    // GAMESCOPE_WIDTH/HEIGHT for the initial size. Selected via
    // LIGHTRAYS_GOW_COMPOSITOR=gamescope|sway (default gamescope). Both
    // compositor variables are contract-managed: the selected one is forced on
    // and the other removed, so app_env can never toggle the compositor.
    let (compositor_key, other_key) = match std::env::var("LIGHTRAYS_GOW_COMPOSITOR")
        .unwrap_or_default()
        .to_ascii_lowercase()
        .as_str()
    {
        "sway" => ("RUN_SWAY", "RUN_GAMESCOPE"),
        _ => ("RUN_GAMESCOPE", "RUN_SWAY"),
    };
    env_remove(&mut env, other_key);
    env_set(&mut env, compositor_key, "1");

    ContainerConfig {
        title: launch.title.clone(),
        image: launch
            .docker_image
            .clone()
            .unwrap_or_else(|| config.gow_image.clone()),
        env: env
            .into_iter()
            .map(|(k, v)| format!("{k}={v}"))
            .collect(),
        devices: Vec::new(),
        mounts: Vec::new(),
        base_create_json: gow_base_create_json(),
        app_id: launch.app_id.clone(),
        owner_sub: owner_sub.to_string(),
    }
}

/// Insert or overwrite `key` in an ordered env list, preserving the position
/// of an existing entry (so a contract override replaces an app_env value in
/// place rather than appending a duplicate).
fn env_set(env: &mut Vec<(String, String)>, key: &str, value: &str) {
    if let Some(entry) = env.iter_mut().find(|(k, _)| k == key) {
        entry.1 = value.to_string();
    } else {
        env.push((key.to_string(), value.to_string()));
    }
}

/// Remove any entry with the given key from an ordered env list.
fn env_remove(env: &mut Vec<(String, String)>, key: &str) {
    env.retain(|(k, _)| k != key);
}

fn gow_base_create_json() -> String {
    // Isolation-hardened GOW HostConfig (see S-H2 / S-H3):
    //  * IpcMode is intentionally omitted so each session gets a private
    //    IPC namespace (override with LIGHTRAYS_IPC_MODE=host if a future
    //    GOW feature needs the host IPC).
    //  * DeviceCgroupRules allow /dev/uinput (major 10, minor 223) so GOW
    //    can create virtual input devices, but NOT the physical host input
    //    devices (major 13). Major 244 is kept for GOW's uhid/hidraw path.
    serde_json::json!({
        "HostConfig": {
            "CapAdd": [
                "SYS_ADMIN",
                "SYS_NICE",
                "SYS_PTRACE",
                "NET_RAW",
                "MKNOD",
                "NET_ADMIN"
            ],
            "SecurityOpt": ["seccomp=unconfined", "apparmor=unconfined"],
            "DeviceCgroupRules": ["c 10:223 rmw", "c 244:* rmw"]
        }
    })
    .to_string()
}

/// Build the ICE servers array for the browser RTCPeerConnection.
pub fn build_ice_servers(config: &ServerConfig) -> Vec<serde_json::Value> {
    let mut servers = Vec::new();
    if !config.stun_server.is_empty() {
        // Convert from GStreamer format (stun://host:port) to browser format (stun:host:port)
        let url = config.stun_server.replace("stun://", "stun:");
        servers.push(serde_json::json!({ "urls": url }));
    }
    if !config.turn_server.is_empty() {
        // turn_server contains just the host:port (or turn://host:port)
        let base = config
            .turn_server
            .strip_prefix("turn://")
            .unwrap_or(&config.turn_server);
        let url = format!("turn:{base}");
        let mut entry = serde_json::json!({ "urls": url });
        if !config.turn_username.is_empty() {
            entry["username"] = serde_json::Value::String(config.turn_username.clone());
            entry["credential"] = serde_json::Value::String(config.turn_password.clone());
        }
        servers.push(entry);
    }
    servers
}

#[cfg(test)]
mod tests {
    use super::*;

    fn test_config() -> ServerConfig {
        ServerConfig {
            runtime_backend: crate::config::RuntimeBackend::Docker,
            k8s_session_namespace: "lightrays-sessions".into(),
            k8s_session_node_selector: String::new(),
            hostname: "x".into(),
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
            gow_image: "image:tag".into(),
            gow_compositor: "gamescope".into(),
            allowed_registries: vec![],
            jwt_audience: String::new(),
            max_sessions_global: 0,
            max_sessions_per_user: 0,
        }
    }

    fn base_launch() -> LaunchRequest {
        LaunchRequest {
            width: Some(1920),
            height: Some(1080),
            fps: Some(60),
            bitrate_kbps: Some(10_000),
            title: Some("Steam".to_string()),
            runtime_profile: Some("gow-steam".to_string()),
            docker_image: None,
            keyboard_layout: Some("de".to_string()),
            mouse_speed: None,
            app_env: None,
            image: None,
            container_name: None,
            env: None,
            devices: None,
            mounts: None,
            base_create_json: None,
            app_id: Some("user-123.game-456".to_string()),
            start_virtual_compositor: Some(true),
            start_audio_server: Some(true),
            render_node: Some("/dev/dri/renderD128".to_string()),
        }
    }

    #[test]
    fn launch_validation_accepts_profile_contract() {
        let launch = validate_launch_request(&base_launch()).expect("valid launch");
        assert_eq!(launch.runtime_profile, "gow-steam");
        assert_eq!(launch.docker_image, None);
        assert_eq!(launch.keyboard_layout, "de");
    }

    #[test]
    fn launch_validation_accepts_docker_image_override() {
        let mut req = base_launch();
        req.docker_image = Some("ghcr.io/example/game-runtime:latest".to_string());
        let launch = validate_launch_request(&req).expect("valid launch");
        assert_eq!(
            launch.docker_image,
            Some("ghcr.io/example/game-runtime:latest".to_string())
        );
    }

    #[test]
    fn launch_validation_rejects_bad_docker_image() {
        let mut req = base_launch();
        req.docker_image = Some("https://example.com/image".to_string());
        assert!(validate_launch_request(&req).is_err());
    }

    #[test]
    fn launch_validation_rejects_raw_docker_fields() {
        let mut req = base_launch();
        req.image = Some("alpine:latest".to_string());
        assert!(validate_launch_request(&req).is_err());
    }

    #[test]
    fn launch_validation_rejects_bad_render_node() {
        let mut req = base_launch();
        req.render_node = Some("/tmp/renderD128 ! bad".to_string());
        assert!(validate_launch_request(&req).is_err());
    }

    #[test]
    fn build_container_config_none_profile_returns_none() {
        let config = ServerConfig {
            runtime_backend: crate::config::RuntimeBackend::Docker,
            k8s_session_namespace: "lightrays-sessions".into(),
            k8s_session_node_selector: String::new(),
            hostname: "x".into(),
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
            gow_image: "image:tag".into(),
            gow_compositor: "gamescope".into(),
            allowed_registries: vec![],
            jwt_audience: String::new(),
            max_sessions_global: 0,
            max_sessions_per_user: 0,
        };
        let mut req = base_launch();
        req.runtime_profile = Some("none".to_string());
        let launch = validate_launch_request(&req).expect("valid");
        let result = build_container_config(&config, &launch, "alice").expect("valid");
        assert!(result.is_none());
    }

    fn env_value<'a>(env: &'a [String], key: &str) -> Option<&'a str> {
        env.iter()
            .find_map(|e| e.strip_prefix(&format!("{key}=")))
    }

    #[test]
    fn gow_app_merges_app_env_but_contract_vars_win() {
        std::env::remove_var("LIGHTRAYS_GOW_COMPOSITOR");
        let config = test_config();
        let mut app_env = std::collections::HashMap::new();
        // An extra, unmanaged game variable is passed through untouched.
        app_env.insert("STEAM_APP_ID".to_string(), "570".to_string());
        // Attempts to override contract variables must NOT win.
        app_env.insert("XKB_DEFAULT_LAYOUT".to_string(), "evil".to_string());
        app_env.insert("GOW_REQUIRED_DEVICES".to_string(), "/dev/evil".to_string());
        app_env.insert("RUN_GAMESCOPE".to_string(), "0".to_string());
        // A contradictory compositor toggle must be stripped by the contract.
        app_env.insert("RUN_SWAY".to_string(), "1".to_string());
        // Empty keys are dropped.
        app_env.insert(String::new(), "ignored".to_string());

        let mut req = base_launch();
        req.runtime_profile = Some("gow-app".to_string());
        req.app_env = Some(app_env);
        let launch = validate_launch_request(&req).expect("valid");
        let cfg = build_container_config(&config, &launch, "alice")
            .expect("valid")
            .expect("some container");

        // Additional app env survives.
        assert_eq!(env_value(&cfg.env, "STEAM_APP_ID"), Some("570"));
        // Contract vars win over app_env attempts.
        assert_eq!(env_value(&cfg.env, "XKB_DEFAULT_LAYOUT"), Some("de"));
        assert_eq!(
            env_value(&cfg.env, "GOW_REQUIRED_DEVICES"),
            Some("/dev/dri/* /dev/nvidia*")
        );
        assert_eq!(env_value(&cfg.env, "RUN_GAMESCOPE"), Some("1"));
        // The contradictory compositor var was removed by the contract.
        assert_eq!(env_value(&cfg.env, "RUN_SWAY"), None);
        // No duplicate keys leaked through the merge.
        assert_eq!(
            cfg.env.iter().filter(|e| e.starts_with("RUN_GAMESCOPE=")).count(),
            1
        );
        assert_eq!(
            cfg.env
                .iter()
                .filter(|e| e.starts_with("XKB_DEFAULT_LAYOUT="))
                .count(),
            1
        );
    }

    #[test]
    fn gow_steam_env_is_unchanged_and_has_no_app_env() {
        std::env::remove_var("LIGHTRAYS_GOW_COMPOSITOR");
        let config = test_config();
        // Even if a caller supplies app_env, the established gow-steam profile
        // ignores it and produces the exact historical env vector.
        let mut app_env = std::collections::HashMap::new();
        app_env.insert("STEAM_APP_ID".to_string(), "570".to_string());
        let mut req = base_launch();
        req.runtime_profile = Some("gow-steam".to_string());
        req.app_env = Some(app_env);
        let launch = validate_launch_request(&req).expect("valid");
        let cfg = build_container_config(&config, &launch, "alice")
            .expect("valid")
            .expect("some container");
        assert_eq!(
            cfg.env,
            vec![
                "GOW_REQUIRED_DEVICES=/dev/dri/* /dev/nvidia*".to_string(),
                "XKB_DEFAULT_LAYOUT=de".to_string(),
                "RUN_GAMESCOPE=1".to_string(),
            ]
        );
    }

    #[test]
    fn build_ice_servers_with_turn_credentials() {
        let config = ServerConfig {
            runtime_backend: crate::config::RuntimeBackend::Docker,
            k8s_session_namespace: "lightrays-sessions".into(),
            k8s_session_node_selector: String::new(),
            hostname: "x".into(),
            api_bind_addr: "0.0.0.0".into(),
            api_port: 8080,
            streaming_bind_addr: "0.0.0.0".into(),
            streaming_port: 8081,
            metrics_bind_addr: "127.0.0.1".into(),
            metrics_port: 9090,
            stun_server: "stun://stun.l.google.com:19302".into(),
            turn_server: "turn.example.com:3478".into(),
            turn_username: "user".into(),
            turn_password: "pass".into(),
            cors_origins: vec!["*".into()],
            jwt_secret: String::new(),
            session_timeout_secs: 3600,
            reconnect_grace_secs: 30,
            ws_ticket_ttl_secs: 120,
            gow_image: "image:tag".into(),
            gow_compositor: "gamescope".into(),
            allowed_registries: vec![],
            jwt_audience: String::new(),
            max_sessions_global: 0,
            max_sessions_per_user: 0,
        };
        let servers = build_ice_servers(&config);
        assert_eq!(servers.len(), 2);
        assert_eq!(servers[0]["urls"], "stun:stun.l.google.com:19302");
        assert_eq!(servers[1]["urls"], "turn:turn.example.com:3478");
        assert_eq!(servers[1]["username"], "user");
        assert_eq!(servers[1]["credential"], "pass");
    }
}
