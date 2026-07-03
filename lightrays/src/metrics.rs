//! Prometheus metrics for lightrays.

use prometheus::{
    Encoder, HistogramOpts, HistogramVec, IntCounter, IntCounterVec, IntGauge, IntGaugeVec, Opts,
    Registry, TextEncoder,
};
use std::sync::LazyLock;

/// Global metrics registry.
pub static REGISTRY: LazyLock<Registry> = LazyLock::new(Registry::new);

// ─────────────────────────────────────────────────────────────────────────────
// Session metrics
// ─────────────────────────────────────────────────────────────────────────────

/// Number of currently active sessions.
pub static SESSIONS_ACTIVE: LazyLock<IntGauge> = LazyLock::new(|| {
    IntGauge::new(
        "lightrays_sessions_active",
        "Number of currently active sessions",
    )
    .expect("metric creation failed")
});

/// Total number of sessions launched.
pub static SESSIONS_LAUNCHED_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_sessions_launched_total",
        "Total number of sessions launched",
    )
    .expect("metric creation failed")
});

/// Total number of sessions stopped (clean shutdown).
pub static SESSIONS_STOPPED_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_sessions_stopped_total",
        "Total number of sessions stopped",
    )
    .expect("metric creation failed")
});

// ─────────────────────────────────────────────────────────────────────────────
// Container metrics
// ─────────────────────────────────────────────────────────────────────────────

/// Total number of containers started.
pub static CONTAINERS_STARTED_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_containers_started_total",
        "Total number of Docker containers started",
    )
    .expect("metric creation failed")
});

/// Total number of container deaths (unexpected exits).
pub static CONTAINER_DEATHS_TOTAL: LazyLock<IntCounterVec> = LazyLock::new(|| {
    IntCounterVec::new(
        Opts::new(
            "lightrays_container_deaths_total",
            "Total container deaths by exit code",
        ),
        &["exit_code"],
    )
    .expect("metric creation failed")
});

// ─────────────────────────────────────────────────────────────────────────────
// WebRTC metrics
// ─────────────────────────────────────────────────────────────────────────────

/// Number of currently active WebRTC connections.
pub static WEBRTC_CONNECTIONS_ACTIVE: LazyLock<IntGauge> = LazyLock::new(|| {
    IntGauge::new(
        "lightrays_webrtc_connections_active",
        "Number of active WebRTC connections",
    )
    .expect("metric creation failed")
});

/// Total number of WebRTC connections established.
pub static WEBRTC_CONNECTIONS_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_webrtc_connections_total",
        "Total WebRTC connections established",
    )
    .expect("metric creation failed")
});

/// Total number of WebRTC connection failures.
pub static WEBRTC_FAILURES_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_webrtc_failures_total",
        "Total WebRTC connection failures",
    )
    .expect("metric creation failed")
});

// ─────────────────────────────────────────────────────────────────────────────
// Launch error metrics
// ─────────────────────────────────────────────────────────────────────────────

/// Total launch errors by stage.
pub static LAUNCH_ERRORS_TOTAL: LazyLock<IntCounterVec> = LazyLock::new(|| {
    IntCounterVec::new(
        Opts::new(
            "lightrays_launch_errors_total",
            "Total launch errors by stage",
        ),
        &["stage"],
    )
    .expect("metric creation failed")
});

/// Duration of each launch stage (compositor, pulse, container, stream_init).
///
/// Buckets are tuned to typical desktop-streaming launch costs: the compositor
/// usually finishes within a few hundred ms; Docker pulls in cold-cache cases
/// can stretch into tens of seconds.
pub static LAUNCH_STAGE_DURATION_SECONDS: LazyLock<HistogramVec> = LazyLock::new(|| {
    HistogramVec::new(
        HistogramOpts::new(
            "lightrays_launch_stage_duration_seconds",
            "Duration of each launch stage in seconds",
        )
        .buckets(vec![0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0]),
        &["stage"],
    )
    .expect("metric creation failed")
});

// ─────────────────────────────────────────────────────────────────────────────
// Reconnect / lifecycle metrics
// ─────────────────────────────────────────────────────────────────────────────

/// Total WebSocket reconnect attempts (resume during the grace window).
pub static WS_RECONNECTS_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_ws_reconnects_total",
        "Total WebSocket reconnect attempts within the grace window",
    )
    .expect("metric creation failed")
});

/// Total sessions reaped by the idle-timeout reaper.
pub static SESSIONS_IDLE_TIMEOUT_TOTAL: LazyLock<IntCounter> = LazyLock::new(|| {
    IntCounter::new(
        "lightrays_sessions_idle_timeout_total",
        "Total sessions stopped by the idle-timeout reaper",
    )
    .expect("metric creation failed")
});

/// Last observed exit code per runtime profile.
pub static CONTAINER_LAST_EXIT_CODE: LazyLock<IntGaugeVec> = LazyLock::new(|| {
    IntGaugeVec::new(
        Opts::new(
            "lightrays_container_last_exit_code",
            "Last observed exit code per runtime profile",
        ),
        &["runtime_profile"],
    )
    .expect("metric creation failed")
});

// ─────────────────────────────────────────────────────────────────────────────
// Registration & rendering
// ─────────────────────────────────────────────────────────────────────────────

/// Register all metrics with the global registry.
pub fn register_metrics() {
    let r = &*REGISTRY;

    r.register(Box::new(SESSIONS_ACTIVE.clone())).ok();
    r.register(Box::new(SESSIONS_LAUNCHED_TOTAL.clone())).ok();
    r.register(Box::new(SESSIONS_STOPPED_TOTAL.clone())).ok();

    r.register(Box::new(CONTAINERS_STARTED_TOTAL.clone())).ok();
    r.register(Box::new(CONTAINER_DEATHS_TOTAL.clone())).ok();

    r.register(Box::new(WEBRTC_CONNECTIONS_ACTIVE.clone())).ok();
    r.register(Box::new(WEBRTC_CONNECTIONS_TOTAL.clone())).ok();
    r.register(Box::new(WEBRTC_FAILURES_TOTAL.clone())).ok();

    r.register(Box::new(LAUNCH_ERRORS_TOTAL.clone())).ok();
    r.register(Box::new(LAUNCH_STAGE_DURATION_SECONDS.clone()))
        .ok();

    r.register(Box::new(WS_RECONNECTS_TOTAL.clone())).ok();
    r.register(Box::new(SESSIONS_IDLE_TIMEOUT_TOTAL.clone()))
        .ok();
    r.register(Box::new(CONTAINER_LAST_EXIT_CODE.clone())).ok();
}

/// Render all metrics as Prometheus text exposition format.
pub fn render_metrics() -> Result<String, String> {
    let encoder = TextEncoder::new();
    let metric_families = REGISTRY.gather();
    let mut buffer = Vec::new();
    encoder.encode(&metric_families, &mut buffer).map_err(|e| {
        log::error!("Failed to encode Prometheus metrics: {}", e);
        format!("Metrics encoding failed: {e}")
    })?;
    String::from_utf8(buffer).map_err(|e| {
        log::error!("Metrics buffer is not valid UTF-8: {}", e);
        format!("Metrics UTF-8 conversion failed: {e}")
    })
}
