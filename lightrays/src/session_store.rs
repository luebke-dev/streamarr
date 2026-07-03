//! Session map and shared application state.
//!
//! `AppState` is the cloned-by-Arc container threaded through every HTTP
//! and WebSocket handler. `Session` owns the per-launch resources (stream
//! pipeline, container, PulseAudio module) that need to be cleaned up on
//! stop or idle timeout.

use crate::config::ServerConfig;
use crate::metrics;
use crate::pulse;
use crate::runtime::Runtime;
use crate::stream::StreamSession;

use std::collections::HashMap;
use std::sync::atomic::AtomicBool;
use std::sync::Arc;
use std::time::Instant;
use tokio::sync::Mutex;

pub struct AppState {
    pub config: ServerConfig,
    pub sessions: Mutex<HashMap<String, Arc<Session>>>,
    /// Pluggable container runtime. `None` means no backend was
    /// available at startup (Docker daemon down, no kube cluster) and
    /// launch requests will fail fast.
    pub runtime: Option<Arc<dyn Runtime>>,
}

pub struct Session {
    pub stream: StreamSession,
    pub title: String,
    pub owner_sub: String,
    /// Per-app stable identifier used for conflict detection and state dir
    /// naming. When two sessions share the same `app_id`, the older one is
    /// stopped before launching the new one. When unset, the sanitized
    /// `title` is used (backwards-compat).
    pub app_id: Option<String>,
    pub container_name: Option<String>,
    pub bitrate_kbps: u32,
    pub audio_sink: Option<String>,
    pub pulse_module_id: Option<u32>,
    /// Receives `Some(exit_code)` when the container exits.
    pub container_dead_rx: tokio::sync::watch::Receiver<Option<i64>>,
    pub last_activity_at: Mutex<Instant>,
    pub connected: Mutex<bool>,
    pub had_first_connect: AtomicBool,
}

/// Tear down every active session. Used during graceful shutdown so we
/// don't leak containers, PulseAudio modules, or GStreamer pipelines.
pub async fn stop_all_sessions(state: &AppState) {
    let sessions: HashMap<String, Arc<Session>> =
        { std::mem::take(&mut *state.sessions.lock().await) };
    for (session_id, session) in sessions {
        cleanup_session(&session, state.runtime.as_deref()).await;
        log::info!("Session {} stopped", session_id);
    }
}

/// Tear down a single session by id. No-op if the session is already gone.
pub async fn stop_session(state: &AppState, session_id: &str) {
    let session = { state.sessions.lock().await.remove(session_id) };
    if let Some(session) = session {
        cleanup_session(&session, state.runtime.as_deref()).await;
        log::info!("Session {} stopped", session_id);
    }
}

async fn cleanup_session(session: &Session, runtime: Option<&dyn Runtime>) {
    session.stream.stop();
    if let Some(ref name) = session.container_name {
        if let Some(runtime) = runtime {
            // Cleanup is best-effort across multiple subsystems; if the
            // runtime stop fails we still need to unload PulseAudio and
            // decrement metrics. Log so the failure isn't invisible.
            if let Err(e) = runtime.stop(name).await {
                log::warn!("Failed to stop workload {} during cleanup: {:#}", name, e);
            }
        }
    }
    if let Some(module_id) = session.pulse_module_id {
        pulse::unload_module(module_id).await;
    }
    metrics::SESSIONS_ACTIVE.dec();
    metrics::SESSIONS_STOPPED_TOTAL.inc();
}
