//! Lightrays — WebRTC desktop streaming server.

mod auth;
mod config;
mod docker;
mod encoder;
mod input;
mod k8s_runtime;
mod launch;
mod metrics;
mod pipeline;
mod pulse;
mod runtime;
mod server;
mod session_store;
mod stream;
mod webrtc;

use anyhow::{bail, Result};

#[tokio::main]
async fn main() -> Result<()> {
    env_logger::Builder::from_env(env_logger::Env::default().default_filter_or("info")).init();

    log::info!(
        "=== Lightrays v{} — Desktop Streaming via WebRTC ===",
        env!("CARGO_PKG_VERSION")
    );

    // Initialize GStreamer
    gstreamer::init()?;
    log::info!("GStreamer initialized ({})", gstreamer::version_string());

    // Detect video encoders
    match encoder::detect_h264_encoder() {
        Some(name) => log::info!("H.264 encoder: {}", name),
        None => {
            bail!(
                "No H.264 encoder found! Install one of: \
                 gstreamer1.0-plugins-ugly (x264enc), \
                 gstreamer1.0-vaapi (vaapih264enc), \
                 or ensure VA-API works (vah264enc)"
            );
        }
    }
    match encoder::detect_h265_encoder() {
        Some(name) => log::info!(
            "H.265/HEVC encoder: {} (ultra-wide / >4096px support)",
            name
        ),
        None => log::info!("No H.265 encoder found — resolutions wider than 4096px may be clamped"),
    }

    // Load config from environment
    let config = config::ServerConfig::from_env()?;
    log::info!(
        "Config: host {}, API port {}, Streaming port {}, Metrics port {}, STUN {}",
        config.hostname,
        config.api_port,
        config.streaming_port,
        config.metrics_port,
        config.stun_server
    );

    // Ensure runtime directory
    let xdg_runtime =
        std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp/lightrays-runtime".to_string());
    std::fs::create_dir_all(&xdg_runtime)?;

    // Register Prometheus metrics
    metrics::register_metrics();
    log::info!("Prometheus metrics registered (GET /metrics)");

    // Start server
    server::run_server(config).await?;

    Ok(())
}
