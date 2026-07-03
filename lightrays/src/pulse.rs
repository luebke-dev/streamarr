//! PulseAudio sink lifecycle for per-session audio.
//!
//! Each Lightrays session gets a dedicated `module-null-sink` so the
//! app's audio output can be captured into the WebRTC pipeline without
//! cross-talking with other sessions. The module is created on launch,
//! tracked on the [`crate::session_store::Session`], and unloaded on
//! stop / shutdown / launch failure.
//!
//! This module is independent of the container runtime — every backend
//! (Docker, Kubernetes, …) uses the same PulseAudio surface.

use anyhow::{Context, Result};

/// Create a `module-null-sink` and return its module ID.
pub async fn create_sink(sink_name: &str) -> Result<u32> {
    let pulse_server = std::env::var("LIGHTRAYS_PULSE_SERVER").unwrap_or_default();

    let mut cmd = tokio::process::Command::new("pactl");
    if !pulse_server.is_empty() {
        cmd.env("PULSE_SERVER", &pulse_server);
    }
    cmd.args([
        "load-module",
        "module-null-sink",
        &format!("sink_name={sink_name}"),
        "rate=48000",
        "channels=2",
        "channel_map=front-left,front-right",
        &format!("sink_properties=device.description=LightraysWeb-{sink_name}"),
    ]);
    let output = cmd
        .output()
        .await
        .context("pactl load-module failed to execute")?;
    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        anyhow::bail!(
            "pactl load-module failed (exit {}): {}",
            output.status,
            stderr.trim()
        );
    }
    let module_id = String::from_utf8_lossy(&output.stdout)
        .trim()
        .parse::<u32>()
        .context("pactl load-module did not return a module id")?;

    log::info!(
        "Created PulseAudio sink: {} (module {})",
        sink_name,
        module_id
    );
    Ok(module_id)
}

/// Unload a previously-created PulseAudio module. Errors are logged but
/// not returned — cleanup runs on stop/shutdown paths where bubbling up
/// failures would be more disruptive than the leak it leaves behind.
pub async fn unload_module(module_id: u32) {
    let pulse_server = std::env::var("LIGHTRAYS_PULSE_SERVER").unwrap_or_default();
    let mut cmd = tokio::process::Command::new("pactl");
    if !pulse_server.is_empty() {
        cmd.env("PULSE_SERVER", &pulse_server);
    }
    let output = cmd
        .args(["unload-module", &module_id.to_string()])
        .output()
        .await;
    match output {
        Ok(output) if output.status.success() => {
            log::info!("Unloaded PulseAudio module: {}", module_id);
        }
        Ok(output) => {
            let stderr = String::from_utf8_lossy(&output.stderr);
            log::warn!(
                "pactl unload-module {} failed (exit {}): {}",
                module_id,
                output.status,
                stderr.trim()
            );
        }
        Err(e) => {
            log::warn!("pactl unload-module {} failed to execute: {}", module_id, e);
        }
    }
}
