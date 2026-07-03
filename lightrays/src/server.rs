//! HTTP + WebSocket signaling server for lightrays.
//!
//! Uses axum for HTTP routing and WebSocket support.

use crate::auth::{self, WsAuthQuery};
use crate::config::{RuntimeBackend, ServerConfig};
use crate::docker::{ContainerSession, DockerRunner};
use crate::launch::{
    build_container_config, build_ice_servers, forbidden, validate_launch_request, LaunchRequest,
};
use crate::metrics;
use crate::pulse;
use crate::runtime::Runtime;
use crate::session_store::{self, AppState, Session};
use crate::stream::{SignalingMessage, StreamSession};

use anyhow::Result;
use axum::{
    extract::{
        ws::{Message, WebSocket, WebSocketUpgrade},
        Path, Query, State,
    },
    http::{HeaderMap, StatusCode},
    response::IntoResponse,
    routing::{get, post},
    Json, Router,
};
use futures::{SinkExt, StreamExt};
use serde::Deserialize;
use std::collections::{HashMap, HashSet};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Mutex;
use tower_http::cors::{AllowOrigin, CorsLayer};

// ─────────────────────────────────────────────────────────────────────────────
// Server entry point
// ─────────────────────────────────────────────────────────────────────────────

pub async fn run_server(config: ServerConfig) -> Result<()> {
    let api_port = config.api_port;
    let streaming_port = config.streaming_port;
    let metrics_port = config.metrics_port;

    let runtime: Option<Arc<dyn Runtime>> = match config.runtime_backend {
        RuntimeBackend::Docker => match DockerRunner::new() {
            Ok(d) => {
                log::info!("Container runtime: Docker");
                Some(Arc::new(d) as Arc<dyn Runtime>)
            }
            Err(e) => {
                log::warn!("Docker not available: {} — container runners disabled", e);
                None
            }
        },
        RuntimeBackend::Kubernetes => match crate::k8s_runtime::KubernetesRunner::new().await {
            Ok(k) => {
                log::info!("Container runtime: Kubernetes");
                Some(Arc::new(k) as Arc<dyn Runtime>)
            }
            Err(e) => {
                log::warn!(
                    "Kubernetes not available: {} — container runners disabled",
                    e
                );
                None
            }
        },
    };

    // ── Startup reconciliation ────────────────────────────────────────
    // Session state lives only in-memory, so after a hard crash / restart
    // the map starts empty and every `lightrays-*` container, PulseAudio
    // sink, and per-session resource left on the host is orphaned — the
    // idle reaper would never see them. Sweep them before we start
    // accepting launches. This runs while nothing can be in flight yet, so
    // an empty active set with a zero min-age is safe. All errors are
    // logged and swallowed so a sweep failure never blocks startup.
    let empty_active: HashSet<String> = HashSet::new();
    if let Some(runtime) = runtime.as_ref() {
        let removed = runtime.reconcile_orphans(&empty_active, 0).await;
        if removed > 0 {
            log::warn!(
                "Startup reconciliation removed {removed} orphaned lightrays container(s)"
            );
        }
    }
    let orphan_sinks = pulse::reconcile_orphans(&empty_active).await;
    if orphan_sinks > 0 {
        log::warn!("Startup reconciliation unloaded {orphan_sinks} orphaned PulseAudio sink(s)");
    }

    // Build CORS layer from config
    let cors = build_cors_layer(&config.cors_origins);
    log::info!("CORS origins: {:?}", config.cors_origins);
    if config.cors_origins.iter().any(|o| o == "*") {
        log::warn!(
            "CORS is set to allow ALL origins (*). \
             Set LIGHTRAYS_CORS_ORIGINS to specific origins in production."
        );
    }

    if config.jwt_secret.is_empty() {
        log::warn!("JWT auth DISABLED (LIGHTRAYS_AUTH_DISABLED=true) — all endpoints are open");
    } else {
        log::info!("JWT authentication enabled");
    }

    let state = Arc::new(AppState {
        config,
        sessions: Mutex::new(HashMap::new()),
        runtime,
    });

    // ── API router (management + WebSocket on same port) ──────────────
    let api_app = Router::new()
        .route("/api/launch", post(handle_launch))
        .route("/api/stop", post(handle_stop))
        .route("/api/stats/:session_id", get(handle_container_stats))
        .route("/api/lightrays-ws/:session_id", get(handle_ws_upgrade))
        .route("/health", get(handle_health))
        .route("/ready", get(handle_ready))
        .layer(cors.clone())
        .with_state(state.clone());

    // ── Streaming router (WebSocket) ────────────────────────────────────
    let streaming_cors = build_cors_layer(&state.config.cors_origins);
    let streaming_app = Router::new()
        .route("/api/lightrays-ws/:session_id", get(handle_ws_upgrade))
        .layer(streaming_cors)
        .with_state(state.clone());

    // ── Metrics router (Prometheus) ─────────────────────────────────────
    let metrics_app = Router::new().route("/metrics", get(handle_metrics));

    log::info!(
        "API server      on http://{}:{}",
        state.config.api_bind_addr,
        api_port
    );
    log::info!(
        "Streaming server on http://{}:{}",
        state.config.streaming_bind_addr,
        streaming_port
    );
    log::info!(
        "Metrics server   on http://{}:{}",
        state.config.metrics_bind_addr,
        metrics_port
    );

    let api_listener =
        tokio::net::TcpListener::bind(format!("{}:{api_port}", state.config.api_bind_addr)).await?;
    let streaming_listener = tokio::net::TcpListener::bind(format!(
        "{}:{streaming_port}",
        state.config.streaming_bind_addr
    ))
    .await?;
    let metrics_listener =
        tokio::net::TcpListener::bind(format!("{}:{metrics_port}", state.config.metrics_bind_addr))
            .await?;

    // Share a single shutdown notify across all servers
    let notify = Arc::new(tokio::sync::Notify::new());
    let n1 = notify.clone();
    let n2 = notify.clone();
    let n3 = notify.clone();

    // Spawn session timeout reaper if configured
    let session_timeout = state.config.session_timeout_secs;
    if session_timeout > 0 {
        let state_clone = state.clone();
        tokio::spawn(async move {
            session_timeout_reaper(state_clone, session_timeout).await;
        });
        log::info!("Session timeout enabled: {}s", session_timeout);
    }

    // Drive shutdown notification from the signal
    tokio::spawn({
        let notify = notify.clone();
        async move {
            shutdown_signal(state).await;
            notify.notify_waiters();
        }
    });

    let api_server = axum::serve(api_listener, api_app)
        .with_graceful_shutdown(async move { n1.notified().await });
    let streaming_server = axum::serve(streaming_listener, streaming_app)
        .with_graceful_shutdown(async move { n2.notified().await });
    let metrics_server = axum::serve(metrics_listener, metrics_app)
        .with_graceful_shutdown(async move { n3.notified().await });

    tokio::try_join!(api_server, streaming_server, metrics_server)?;

    Ok(())
}

/// Build a [`CorsLayer`] from an origins list.
/// A single `*` entry allows any origin; otherwise each entry must be an exact
/// origin string like `https://pyrate.example.com`.
fn build_cors_layer(origins: &[String]) -> CorsLayer {
    use axum::http::{HeaderValue, Method};

    let allow_origin = if origins.iter().any(|o| o == "*") {
        AllowOrigin::any()
    } else {
        let values: Vec<HeaderValue> = origins.iter().filter_map(|o| o.parse().ok()).collect();
        AllowOrigin::list(values)
    };

    CorsLayer::new()
        .allow_origin(allow_origin)
        .allow_methods([Method::GET, Method::POST, Method::OPTIONS])
        .allow_headers(tower_http::cors::Any)
}

async fn shutdown_signal(state: Arc<AppState>) {
    let ctrl_c = async {
        if let Err(e) = tokio::signal::ctrl_c().await {
            log::error!("Failed to install Ctrl+C handler: {}", e);
        }
    };

    #[cfg(unix)]
    let terminate = async {
        match tokio::signal::unix::signal(tokio::signal::unix::SignalKind::terminate()) {
            Ok(mut sig) => {
                sig.recv().await;
            }
            Err(e) => {
                log::error!("Failed to install SIGTERM handler: {}", e);
                std::future::pending::<()>().await;
            }
        }
    };

    #[cfg(unix)]
    tokio::select! {
        _ = ctrl_c => {},
        _ = terminate => {},
    }

    #[cfg(not(unix))]
    ctrl_c.await;

    log::info!("Shutdown signal received, cleaning up...");
    session_store::stop_all_sessions(&state).await;
    log::info!("Lightrays stopped");
}

// ─────────────────────────────────────────────────────────────────────────────
// Session management
// ─────────────────────────────────────────────────────────────────────────────

/// Prometheus metrics endpoint.
async fn handle_metrics() -> impl IntoResponse {
    match metrics::render_metrics() {
        Ok(body) => (
            StatusCode::OK,
            [(
                axum::http::header::CONTENT_TYPE,
                "text/plain; version=0.0.4; charset=utf-8",
            )],
            body,
        )
            .into_response(),
        Err(e) => (StatusCode::INTERNAL_SERVER_ERROR, e).into_response(),
    }
}

/// Liveness probe — always returns 200 OK.
async fn handle_health() -> impl IntoResponse {
    Json(serde_json::json!({"status": "ok"}))
}

/// Readiness probe — pings the configured container runtime.
async fn handle_ready(State(state): State<Arc<AppState>>) -> impl IntoResponse {
    match &state.runtime {
        Some(runtime) => match runtime.ping().await {
            Ok(()) => Json(serde_json::json!({"status": "ready", "runtime": true})).into_response(),
            Err(e) => (
                StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({"status": "not_ready", "runtime_error": format!("{e}")})),
            )
                .into_response(),
        },
        None => Json(serde_json::json!({"status": "ready", "runtime": false})).into_response(),
    }
}

/// Minimum age a `lightrays-*` container must have before the periodic
/// reaper sweep will treat it as an orphan. Comfortably longer than a
/// launch takes to register the container in the session map, so a
/// just-created container is never mistaken for an orphan mid-launch.
const ORPHAN_SWEEP_MIN_AGE_SECS: i64 = 120;

/// Background task that reaps sessions idle longer than the configured
/// timeout, and — as a standing safety net — reconciles the actually
/// running `lightrays-*` containers against the in-memory session map so a
/// workload the map has lost track of (e.g. after a partial failure) can't
/// leak indefinitely.
async fn session_timeout_reaper(state: Arc<AppState>, timeout_secs: u64) {
    let timeout = Duration::from_secs(timeout_secs);
    loop {
        tokio::time::sleep(Duration::from_secs(60)).await;
        let expired: Vec<String> = {
            let sessions: Vec<(String, Arc<Session>)> = state
                .sessions
                .lock()
                .await
                .iter()
                .map(|(id, session)| (id.clone(), session.clone()))
                .collect();
            let mut expired = Vec::new();
            for (id, session) in sessions {
                // R-H1: never reap a session with a live WebRTC connection —
                // an actively-played session sends input over the data
                // channel (not the signalling WS), so WS-only activity
                // tracking would falsely time it out.
                if *session.connected.lock().await {
                    continue;
                }
                let last_activity = *session.last_activity_at.lock().await;
                let input_idle = session.stream.seconds_since_input();
                if last_activity.elapsed() > timeout && input_idle as u64 > timeout_secs {
                    expired.push(id);
                }
            }
            expired
        };
        for sid in expired {
            log::info!(
                "Session {} idle-timed out after {}s — stopping",
                sid,
                timeout_secs
            );
            metrics::SESSIONS_IDLE_TIMEOUT_TOTAL.inc();
            session_store::stop_session(&state, &sid).await;
        }

        // Safety-net sweep: kill orphaned containers no live session owns.
        // The active set is rebuilt from the map *after* expiry handling so
        // just-stopped sessions aren't counted as active. `min_age` skips
        // containers younger than a launch window to avoid racing an
        // in-flight launch that hasn't registered its container yet.
        if let Some(runtime) = state.runtime.as_ref() {
            let active: HashSet<String> = state
                .sessions
                .lock()
                .await
                .values()
                .filter_map(|s| s.container_name.clone())
                .collect();
            let removed = runtime
                .reconcile_orphans(&active, ORPHAN_SWEEP_MIN_AGE_SECS)
                .await;
            if removed > 0 {
                log::warn!("Reaper reconciliation removed {removed} orphaned lightrays container(s)");
            }
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// HTTP handlers
// ─────────────────────────────────────────────────────────────────────────────

async fn handle_launch(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(req): Json<LaunchRequest>,
) -> impl IntoResponse {
    let principal = match auth::verify_bearer(&headers, &state.config.jwt_secret, &state.config.jwt_audience) {
        Ok(principal) => principal,
        Err(e) => return e.into_response(),
    };
    let launch = match validate_launch_request(&req) {
        Ok(launch) => launch,
        Err(e) => return e.into_response(),
    };

    // S-C1: a client-supplied raw `docker_image` runs inside a privileged
    // container, so it is an admin-only capability and must additionally
    // pass the registry allowlist. Normal users get a 403.
    if let Some(image) = launch.docker_image.as_deref() {
        if !principal.has_scope("lightrays:admin") {
            return forbidden("docker_image override requires the lightrays:admin scope")
                .into_response();
        }
        if let Err(e) =
            crate::launch::validate_image_registry(image, &state.config.allowed_registries)
        {
            return e.into_response();
        }
    }

    let container_config =
        match build_container_config(&state.config, &launch, &principal.subject) {
            Ok(config) => config,
            Err(e) => return e.into_response(),
        };

    // Stop existing sessions conflicting with this launch. When the caller
    // supplies `app_id`, match on that (keeps per-user sessions isolated
    // even if two users share the same visible title). Otherwise fall
    // back to title-based matching for legacy clients.
    {
        let sessions = state.sessions.lock().await;
        let to_stop: Vec<String> = match launch.app_id.as_ref() {
            Some(id) => sessions
                .iter()
                .filter(|(_, s)| {
                    s.owner_sub == principal.subject && s.app_id.as_deref() == Some(id.as_str())
                })
                .map(|(sid, _)| sid.clone())
                .collect(),
            None => sessions
                .iter()
                .filter(|(_, s)| {
                    s.owner_sub == principal.subject
                        && s.title == launch.title
                        && s.app_id.is_none()
                })
                .map(|(sid, _)| sid.clone())
                .collect(),
        };
        drop(sessions);
        for sid in to_stop {
            log::info!(
                "Stopping existing session {} (title='{}' app_id={:?})",
                sid,
                launch.title,
                launch.app_id,
            );
            session_store::stop_session(&state, &sid).await;
        }
    }

    // S-H4: enforce concurrency limits (after conflicting sessions have
    // been stopped so a relaunch of one's own app never trips the cap).
    {
        let sessions = state.sessions.lock().await;
        let global = sessions.len();
        let per_user = sessions
            .values()
            .filter(|s| s.owner_sub == principal.subject)
            .count();
        drop(sessions);
        let max_global = state.config.max_sessions_global;
        let max_user = state.config.max_sessions_per_user;
        if max_global > 0 && global >= max_global {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({
                    "error": "global concurrent session limit reached"
                })),
            )
                .into_response();
        }
        if max_user > 0 && per_user >= max_user {
            return (
                StatusCode::CONFLICT,
                Json(serde_json::json!({
                    "error": "per-user concurrent session limit reached"
                })),
            )
                .into_response();
        }
    }

    // Generate session ID (16 hex chars = 64 bits of entropy)
    let session_id = uuid::Uuid::new_v4().simple().to_string()[..16].to_string();

    let xdg_runtime =
        std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp/lightrays-runtime".to_string());

    // Create StreamSession
    let stream = match StreamSession::new(
        xdg_runtime.clone(),
        launch.render_node.clone(),
        launch.width,
        launch.height,
        launch.fps,
    ) {
        Ok(s) => s,
        Err(e) => {
            metrics::LAUNCH_ERRORS_TOTAL
                .with_label_values(&["stream_init"])
                .inc();
            return (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({
                    "error": format!("StreamSession init: {e}")
                })),
            )
                .into_response();
        }
    };

    let mut wayland_display = None;
    let mut container_name = None;
    let mut audio_sink = None;
    let mut pulse_module_id = None;

    // Start compositor if needed
    if launch.start_compositor {
        let stream_clone = stream.clone();
        let timer = metrics::LAUNCH_STAGE_DURATION_SECONDS
            .with_label_values(&["compositor"])
            .start_timer();
        match tokio::task::spawn_blocking(move || stream_clone.start_compositor()).await {
            Ok(Ok(display)) => {
                timer.observe_duration();
                log::info!("Compositor started, WAYLAND_DISPLAY={}", display);
                wayland_display = Some(display);
            }
            Ok(Err(e)) => {
                timer.observe_duration();
                metrics::LAUNCH_ERRORS_TOTAL
                    .with_label_values(&["compositor"])
                    .inc();
                return (
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({
                        "error": format!("Compositor failed: {e}")
                    })),
                )
                    .into_response();
            }
            Err(e) => {
                timer.observe_duration();
                metrics::LAUNCH_ERRORS_TOTAL
                    .with_label_values(&["compositor_task"])
                    .inc();
                return (
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({ "error": format!("Task error: {e}") })),
                )
                    .into_response();
            }
        }
    }

    // Create PulseAudio sink if needed
    if launch.start_audio {
        let sink_name = format!("{}{}", pulse::SINK_PREFIX, session_id);
        let timer = metrics::LAUNCH_STAGE_DURATION_SECONDS
            .with_label_values(&["pulse"])
            .start_timer();
        match pulse::create_sink(&sink_name).await {
            Ok(module_id) => {
                timer.observe_duration();
                pulse_module_id = Some(module_id);
                audio_sink = Some(sink_name);
            }
            Err(e) => {
                timer.observe_duration();
                log::warn!("Failed to create PulseAudio sink: {}", e);
            }
        }
    }

    // Start the session workload if the runtime profile requires one.
    if let Some(container_config) = container_config {
        let runtime = match state.runtime.as_ref() {
            Some(r) => r.clone(),
            None => {
                stream.stop();
                if let Some(module_id) = pulse_module_id {
                    pulse::unload_module(module_id).await;
                }
                return (
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({"error": "Container runtime not available"})),
                )
                    .into_response();
            }
        };

        // Isolate this session's socket directory before the container mounts
        // it, hard-linking the shared compositor/pulse sockets in. Best-effort:
        // on failure the container still starts (Docker creates the mount
        // source), the game just won't find the Wayland/pulse sockets — logged
        // so it isn't silent.
        if let Err(e) = crate::docker::provision_session_socket_dir(
            &xdg_runtime,
            &session_id,
            wayland_display.as_deref(),
        ) {
            log::warn!("Failed to provision session socket dir for {session_id}: {e}");
        }

        let container_session = ContainerSession {
            session_id: session_id.clone(),
            width: launch.width,
            height: launch.height,
            fps: launch.fps,
            wayland_display: wayland_display.clone(),
            xdg_runtime_dir: xdg_runtime.clone(),
            audio_sink: audio_sink.clone(),
        };

        let timer = metrics::LAUNCH_STAGE_DURATION_SECONDS
            .with_label_values(&["container"])
            .start_timer();
        match runtime.start(&container_config, &container_session).await {
            Ok(name) => {
                timer.observe_duration();
                metrics::CONTAINERS_STARTED_TOTAL.inc();
                container_name = Some(name);
            }
            Err(e) => {
                timer.observe_duration();
                log::error!("Workload failed for session {}: {e:#}", session_id);
                metrics::LAUNCH_ERRORS_TOTAL
                    .with_label_values(&["container"])
                    .inc();
                stream.stop();
                if let Some(module_id) = pulse_module_id {
                    pulse::unload_module(module_id).await;
                }
                return (
                    axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                    Json(serde_json::json!({
                        "error": format!("Workload failed: {e:#}")
                    })),
                )
                    .into_response();
            }
        }
    }

    // Store session
    let (container_dead_tx, container_dead_rx) = tokio::sync::watch::channel(None);

    let session = Arc::new(Session {
        stream,
        title: launch.title.clone(),
        owner_sub: principal.subject.clone(),
        app_id: launch.app_id.clone(),
        container_name: container_name.clone(),
        bitrate_kbps: launch.bitrate_kbps,
        audio_sink,
        pulse_module_id,
        container_dead_rx,
        last_activity_at: Mutex::new(Instant::now()),
        connected: Mutex::new(false),
        had_first_connect: std::sync::atomic::AtomicBool::new(false),
    });

    state
        .sessions
        .lock()
        .await
        .insert(session_id.clone(), session);

    // Spawn workload lifecycle monitor
    if let (Some(runtime), Some(ref cname)) = (state.runtime.clone(), &container_name) {
        let name = cname.clone();
        let state_clone = state.clone();
        let sid = session_id.clone();
        let runtime_profile = launch.runtime_profile.clone();
        tokio::spawn(async move {
            let exit_code = runtime.wait_for_exit(&name).await;
            // Only act if the session still exists (i.e. wasn't already cleaned up)
            let session_exists = state_clone.sessions.lock().await.contains_key(&sid);
            if session_exists {
                log::warn!(
                    "Workload {} died (exit code {}) — notifying session {}",
                    name,
                    exit_code,
                    sid
                );
                metrics::CONTAINER_DEATHS_TOTAL
                    .with_label_values(&[&exit_code.to_string()])
                    .inc();
                metrics::CONTAINER_LAST_EXIT_CODE
                    .with_label_values(&[&runtime_profile])
                    .set(exit_code);
                // Capture workload logs before cleanup destroys them. An
                // `exit_code == 0` is still a launch failure when it
                // happens seconds after start (GOW entrypoints often exit
                // clean when they can't find a display / devices / mounts),
                // so always dump the tail.
                runtime.dump_logs(&name, 80).await;
                let _ = container_dead_tx.send(Some(exit_code));
                // Give the WebSocket handler a moment to send the notification
                tokio::time::sleep(tokio::time::Duration::from_secs(2)).await;
                session_store::stop_session(&state_clone, &sid).await;
            } else {
                log::debug!(
                    "Container {} exited (code {}) — session {} already cleaned up",
                    name,
                    exit_code,
                    sid
                );
            }
        });
    }

    metrics::SESSIONS_LAUNCHED_TOTAL.inc();
    metrics::SESSIONS_ACTIVE.inc();

    log::info!(
        "App '{}' launched → session {} ({}x{}@{}fps)",
        launch.title,
        session_id,
        launch.width,
        launch.height,
        launch.fps
    );

    Json(serde_json::json!({
        "session_id": session_id,
        "ws_url": format!("/api/lightrays-ws/{session_id}"),
        "ws_ticket": auth::create_ws_ticket(
            &state.config.jwt_secret,
            state.config.ws_ticket_ttl_secs,
            &state.config.jwt_audience,
            &principal,
            &session_id,
        ),
        "streaming_port": state.config.streaming_port,
        "ice_servers": build_ice_servers(&state.config),
    }))
    .into_response()
}

#[derive(Deserialize)]
struct StopRequest {
    session_id: String,
}

async fn handle_stop(
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
    Json(req): Json<StopRequest>,
) -> impl IntoResponse {
    let principal = match auth::verify_bearer(&headers, &state.config.jwt_secret, &state.config.jwt_audience) {
        Ok(principal) => principal,
        Err(e) => return e.into_response(),
    };

    let session = { state.sessions.lock().await.get(&req.session_id).cloned() };
    let Some(session) = session else {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "Session not found"})),
        )
            .into_response();
    };
    if !principal.can_access(&session.owner_sub) {
        return forbidden("Not authorized for this session").into_response();
    }

    session_store::stop_session(&state, &req.session_id).await;
    Json(serde_json::json!({"status": "stopped"})).into_response()
}

/// Return Docker container CPU + memory stats for a session.
async fn handle_container_stats(
    Path(session_id): Path<String>,
    State(state): State<Arc<AppState>>,
    headers: HeaderMap,
) -> impl IntoResponse {
    let principal = match auth::verify_bearer(&headers, &state.config.jwt_secret, &state.config.jwt_audience) {
        Ok(principal) => principal,
        Err(e) => return e.into_response(),
    };

    let session = state.sessions.lock().await.get(&session_id).cloned();
    let session = match session {
        Some(s) => s,
        None => {
            return (
                axum::http::StatusCode::NOT_FOUND,
                Json(serde_json::json!({"error": "Session not found"})),
            )
                .into_response()
        }
    };
    if !principal.can_access(&session.owner_sub) {
        return forbidden("Not authorized for this session").into_response();
    }

    let container_name = match &session.container_name {
        Some(name) => name.clone(),
        None => {
            return Json(serde_json::json!({
                "cpu_percent": 0.0,
                "mem_used": 0,
                "mem_limit": 0
            }))
            .into_response()
        }
    };

    let runtime = match state.runtime.as_ref() {
        Some(r) => r.clone(),
        None => {
            return (
                axum::http::StatusCode::SERVICE_UNAVAILABLE,
                Json(serde_json::json!({"error": "Container runtime not available"})),
            )
                .into_response()
        }
    };

    match runtime.stats(&container_name).await {
        Ok(stats) => Json(serde_json::json!(stats)).into_response(),
        Err(e) => {
            log::warn!("Failed to get stats for {}: {}", container_name, e);
            (
                axum::http::StatusCode::INTERNAL_SERVER_ERROR,
                Json(serde_json::json!({ "error": format!("{e}") })),
            )
                .into_response()
        }
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// WebSocket signaling
// ─────────────────────────────────────────────────────────────────────────────

async fn handle_ws_upgrade(
    ws: WebSocketUpgrade,
    Path(session_id): Path<String>,
    Query(_query): Query<WsAuthQuery>,
    headers: HeaderMap,
    State(state): State<Arc<AppState>>,
) -> impl IntoResponse {
    let principal = match auth::verify_ws_token(&headers, &state.config.jwt_secret, &state.config.jwt_audience, &session_id) {
        Ok(principal) => principal,
        Err(e) => return e.into_response(),
    };

    let session = { state.sessions.lock().await.get(&session_id).cloned() };
    let Some(session) = session else {
        return (
            StatusCode::NOT_FOUND,
            Json(serde_json::json!({"error": "Session not found"})),
        )
            .into_response();
    };
    if !principal.can_access(&session.owner_sub) {
        return forbidden("Not authorized for this session").into_response();
    }

    ws.protocols(["lightrays"])
        .on_upgrade(move |socket| handle_websocket(socket, session_id, state))
        .into_response()
}

async fn handle_websocket(socket: WebSocket, session_id: String, state: Arc<AppState>) {
    let (mut ws_tx, mut ws_rx) = socket.split();

    // Look up session
    let session = { state.sessions.lock().await.get(&session_id).cloned() };

    let session = match session {
        Some(s) => s,
        None => {
            let _ = ws_tx
                .send(Message::Text(
                    serde_json::json!({"error": "Session not found"}).to_string(),
                ))
                .await;
            return;
        }
    };

    // R-M1: a session that is already streaming has a live WebRTC pipeline
    // and data channel. A second WebSocket must NOT tear it down — reject
    // the new connection and leave the running session untouched.
    if session.stream.is_streaming() {
        log::warn!(
            "Rejecting second WebSocket for already-streaming session {}",
            session_id
        );
        let _ = ws_tx
            .send(Message::Text(
                serde_json::json!({"error": "session already has an active stream"}).to_string(),
            ))
            .await;
        return;
    }

    log::info!("WebSocket connected for session {}", session_id);
    if session
        .had_first_connect
        .swap(true, std::sync::atomic::Ordering::Relaxed)
    {
        metrics::WS_RECONNECTS_TOTAL.inc();
    }
    *session.connected.lock().await = true;
    *session.last_activity_at.lock().await = Instant::now();

    // Clone the container death watcher
    let mut container_dead_rx = session.container_dead_rx.clone();

    // Pipeline error watcher — the GStreamer bus-watch threads fire this
    // on a fatal ERROR/EOS (or a failed resize rebuild) so we tear the
    // session down instead of streaming a frozen frame (R-M3/R-M4/R-M6).
    let (pipeline_error_tx, mut pipeline_error_rx) = tokio::sync::watch::channel(false);
    session.stream.set_error_sender(pipeline_error_tx);

    // Create signaling channel
    let (sig_tx, mut sig_rx) = tokio::sync::mpsc::unbounded_channel();

    // Start WebRTC pipeline (blocking GStreamer operation)
    let stream = session.stream.clone();
    let audio_device = session
        .audio_sink
        .as_ref()
        .map(|s| format!("{s}.monitor"))
        .unwrap_or_default();
    let pulse_server = std::env::var("LIGHTRAYS_PULSE_SERVER").unwrap_or_default();
    let bitrate = session.bitrate_kbps;
    let stun_server = state.config.stun_server.clone();
    // Build GStreamer-compatible TURN URL: turn://user:pass@host:port
    let turn_server =
        if !state.config.turn_server.is_empty() && !state.config.turn_username.is_empty() {
            let base = state
                .config
                .turn_server
                .strip_prefix("turn://")
                .unwrap_or(&state.config.turn_server);
            format!(
                "turn://{}:{}@{}",
                state.config.turn_username, state.config.turn_password, base
            )
        } else {
            state.config.turn_server.clone()
        };

    let webrtc_result = tokio::task::spawn_blocking(move || {
        stream.start_webrtc(
            bitrate,
            &audio_device,
            &pulse_server,
            &stun_server,
            &turn_server,
            sig_tx,
        )
    })
    .await;

    match webrtc_result {
        Ok(Ok(())) => {
            metrics::WEBRTC_CONNECTIONS_TOTAL.inc();
            metrics::WEBRTC_CONNECTIONS_ACTIVE.inc();
            log::info!("WebRTC pipeline started for session {}", session_id);
        }
        Ok(Err(e)) => {
            metrics::WEBRTC_FAILURES_TOTAL.inc();
            log::error!("WebRTC start failed: {}", e);
            let _ = ws_tx
                .send(Message::Text(
                    serde_json::json!({ "error": format!("WebRTC start failed: {e}") }).to_string(),
                ))
                .await;
            session_store::stop_session(&state, &session_id).await;
            return;
        }
        Err(e) => {
            metrics::WEBRTC_FAILURES_TOTAL.inc();
            log::error!("Task error: {}", e);
            session_store::stop_session(&state, &session_id).await;
            return;
        }
    }

    // Re-fetch session (still valid — stream was cloned, not moved)
    let session = match state.sessions.lock().await.get(&session_id).cloned() {
        Some(s) => s,
        None => return,
    };

    // Periodic ping keeps the signalling WebSocket alive through proxies
    // (Cloudflare drops idle WebSockets after ~100 s). Once WebRTC has
    // connected and input flows over the data channel, the signalling WS
    // goes silent and would otherwise be reaped, killing resize and the
    // session along with it.
    let mut ping_interval = tokio::time::interval(std::time::Duration::from_secs(25));
    ping_interval.set_missed_tick_behavior(tokio::time::MissedTickBehavior::Delay);
    // Skip the immediate first tick — we don't need to ping at t=0.
    ping_interval.tick().await;

    // Set when the message loop breaks because of a fatal pipeline error,
    // so the post-loop cleanup skips the reconnect grace window.
    let mut pipeline_error = false;

    // Message loop: multiplex between browser→server, GStreamer→browser, and container death
    loop {
        tokio::select! {
            msg = ws_rx.next() => {
                match msg {
                    Some(Ok(Message::Text(text))) => {
                        *session.last_activity_at.lock().await = Instant::now();
                        handle_ws_message(&text, &session, &state);
                    }
                    Some(Ok(Message::Ping(_) | Message::Pong(_))) => {
                        // axum auto-replies to Ping with Pong; nothing to do for Pong replies to our pings.
                    }
                    Some(Ok(Message::Close(_))) | None => break,
                    Some(Err(e)) => {
                        log::warn!("WebSocket error: {}", e);
                        break;
                    }
                    _ => {}
                }
            }
            sig = sig_rx.recv() => {
                match sig {
                    Some(SignalingMessage::SdpOffer(sdp)) => {
                        let json = serde_json::json!({"type": "offer", "sdp": sdp}).to_string();
                        if ws_tx.send(Message::Text(json)).await.is_err() {
                            break;
                        }
                    }
                    Some(SignalingMessage::IceCandidate { mline_index, candidate }) => {
                        let json = serde_json::json!({
                            "type": "ice",
                            "candidate": candidate,
                            "sdpMLineIndex": mline_index,
                        }).to_string();
                        if ws_tx.send(Message::Text(json)).await.is_err() {
                            break;
                        }
                    }
                    None => break,
                }
            }
            _ = container_dead_rx.changed() => {
                let exit_code = *container_dead_rx.borrow_and_update();
                if let Some(code) = exit_code {
                    log::info!("Container died for session {} (exit code {}) — notifying client", session_id, code);
                    let json = serde_json::json!({
                        "type": "container_died",
                        "exit_code": code,
                    }).to_string();
                    let _ = ws_tx.send(Message::Text(json)).await;
                    break;
                }
            }
            _ = pipeline_error_rx.changed() => {
                if *pipeline_error_rx.borrow_and_update() {
                    log::warn!("Pipeline error for session {} — tearing down", session_id);
                    let json = serde_json::json!({ "type": "pipeline_error" }).to_string();
                    let _ = ws_tx.send(Message::Text(json)).await;
                    pipeline_error = true;
                    break;
                }
            }
            _ = ping_interval.tick() => {
                if ws_tx.send(Message::Ping(Vec::new())).await.is_err() {
                    break;
                }
            }
        }
    }

    metrics::WEBRTC_CONNECTIONS_ACTIVE.dec();
    log::info!("WebSocket closed for session {}", session_id);
    // R-M5: teardown blocks (pipeline NULL + thread join, up to ~3 s), so
    // run it on a blocking worker instead of stalling a Tokio worker.
    {
        let stream = session.stream.clone();
        let _ = tokio::task::spawn_blocking(move || stream.stop_webrtc_pipeline()).await;
    }
    *session.connected.lock().await = false;

    let grace_secs = state.config.reconnect_grace_secs;
    // A fatal pipeline error means the compositor/encoder is gone — there is
    // nothing to reconnect to, so stop the session immediately regardless of
    // the reconnect grace window.
    if grace_secs == 0 || pipeline_error {
        session_store::stop_session(&state, &session_id).await;
    } else {
        let state_clone = state.clone();
        let sid = session_id.clone();
        tokio::spawn(async move {
            tokio::time::sleep(Duration::from_secs(grace_secs)).await;
            let session = { state_clone.sessions.lock().await.get(&sid).cloned() };
            if let Some(session) = session {
                let connected = *session.connected.lock().await;
                if !connected {
                    log::info!(
                        "Reconnect grace expired after {}s for session {} — stopping",
                        grace_secs,
                        sid
                    );
                    session_store::stop_session(&state_clone, &sid).await;
                }
            }
        });
    }
}

fn handle_ws_message(text: &str, session: &Session, state: &Arc<AppState>) {
    let data: serde_json::Value = match serde_json::from_str(text) {
        Ok(v) => v,
        Err(_) => {
            log::warn!("Invalid JSON in WebSocket: {}", text);
            return;
        }
    };

    let msg_type = data.get("type").and_then(|v| v.as_str()).unwrap_or("");

    match msg_type {
        "answer" => {
            let sdp = data.get("sdp").and_then(|v| v.as_str()).unwrap_or("");
            if let Err(e) = session.stream.set_remote_answer(sdp) {
                log::error!("Failed to set remote answer: {}", e);
            }
        }
        "ice" => {
            let mline_index = data
                .get("sdpMLineIndex")
                .and_then(|v| v.as_u64())
                .unwrap_or(0) as u32;
            let candidate = data.get("candidate").and_then(|v| v.as_str()).unwrap_or("");
            if let Err(e) = session.stream.add_ice_candidate(mline_index, candidate) {
                log::error!("Failed to add ICE candidate: {}", e);
            }
        }
        "keyframe" => {
            session.stream.request_keyframe();
        }
        "resize" => {
            let width = data.get("width").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            let height = data.get("height").and_then(|v| v.as_u64()).unwrap_or(0) as u32;
            if width > 0 && height > 0 {
                // In sway mode, live-resize the in-container compositor's
                // output so the Steam UI re-lays-out at the new size —
                // gamescope pins -W/-H at launch and can't. Fire-and-forget:
                // if it fails the UI just keeps its previous layout while the
                // stream rebuild below still applies.
                if state.config.gow_compositor == "sway" {
                    if let (Some(runtime), Some(container)) =
                        (state.runtime.clone(), session.container_name.clone())
                    {
                        tokio::spawn(async move {
                            let res = format!("{width}x{height}");
                            // sway listens at $XDG_RUNTIME_DIR/sway-ipc.<uid>.<pid>.sock
                            // (it ignores a pre-set SWAYSOCK), and /tmp/sockets is a
                            // shared mount so stale sockets from past sessions linger —
                            // probe each candidate and use the one that answers.
                            // With a per-session runtime dir sway binds the
                            // deterministic $SWAYSOCK (/tmp/sockets/sway.socket);
                            // fall back to the pid-named default if it ever
                            // couldn't. Probe each and use the one that answers.
                            let script = format!(
                                "for s in /tmp/sockets/sway.socket /tmp/sockets/sway-ipc.*.sock; do \
                                   SWAYSOCK=\"$s\" swaymsg -t get_version >/dev/null 2>&1 && \
                                   exec env SWAYSOCK=\"$s\" swaymsg output '*' resolution {res}; \
                                 done; exit 1"
                            );
                            if let Err(e) = runtime
                                .exec(
                                    &container,
                                    vec!["sh".into(), "-c".into(), script],
                                    Vec::new(),
                                )
                                .await
                            {
                                log::warn!("sway output resize failed: {e}");
                            }
                        });
                    }
                }
                // Run on a blocking worker so the signalling loop stays
                // responsive (pings, ICE forwarding, container-died, the
                // next WS message) while GStreamer rebuilds the pipeline.
                // change_resolution coalesces concurrent calls via
                // pending_target — multiple rapid resize messages collapse
                // to at most one extra rebuild.
                let stream = session.stream.clone();
                tokio::task::spawn_blocking(move || {
                    if let Err(e) = stream.change_resolution(width, height) {
                        log::warn!("Resolution change failed: {}", e);
                    }
                });
            }
        }
        "key" | "mousemove" | "mouseabs" | "mousebutton" | "wheel" => {
            session.stream.send_input(text);
        }
        _ => {
            log::warn!("Unknown WS message type: {}", msg_type);
        }
    }
}
