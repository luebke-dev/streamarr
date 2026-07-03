//! Compositor → WebRTC bridge loop.
//!
//! Runs on a dedicated OS thread (not a Tokio task) because GStreamer's
//! blocking `try_pull_sample` doesn't cooperate with async runtimes.
//! Samples are pushed by reference — the original code copied each buffer
//! (~4 MB / frame at 1262×782 RGBx, ~230 MB/s at 60 fps) and starved the
//! pipeline; pushing the borrowed sample keeps the encoder fed.

use gstreamer as gst;
use gstreamer_app as gst_app;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Pull samples from `compositor_sink` and push them into `webrtc_src`
/// until `stop` is set or the appsrc returns `Flushing`.
pub fn run(compositor_sink: gst_app::AppSink, webrtc_src: gst_app::AppSrc, stop: Arc<AtomicBool>) {
    let mut pushed: u64 = 0;
    let mut current_caps = String::new();
    let t_start = std::time::Instant::now();

    log::info!("Compositor bridge thread started");

    while !stop.load(Ordering::Relaxed) {
        let timeout = gst::ClockTime::from_mseconds(100);
        let sample = match compositor_sink.try_pull_sample(timeout) {
            Some(s) => s,
            None => continue,
        };

        // Check caps and reject tiny frames
        let sample_caps = sample.caps().map(|c| c.to_owned());
        if let Some(ref caps) = sample_caps {
            if let Some(s) = caps.structure(0) {
                let w: i32 = s.get("width").unwrap_or(0);
                let h: i32 = s.get("height").unwrap_or(0);
                if w < 16 || h < 16 {
                    continue;
                }
            }

            let caps_str = caps.to_string();
            if caps_str != current_caps {
                log::info!("Compositor bridge caps: {}", caps_str);
                current_caps = caps_str;
            }
        }

        // Push the original sample directly — it already contains buffer+caps.
        // Rebuilding with buffer.to_owned() was copying ~4MB per frame
        // (~230 MB/s at 60fps for 1262x782 RGBx), starving the pipeline.
        if sample.buffer().is_some() {
            match webrtc_src.push_sample(&sample) {
                Ok(_) => {
                    pushed += 1;
                }
                Err(gst::FlowError::Flushing) => {
                    log::info!("push-sample: FLUSHING, stopping bridge");
                    break;
                }
                Err(e) => {
                    log::warn!("push-sample error: {:?} (frame {})", e, pushed);
                    break;
                }
            }

            if pushed == 1 {
                log::info!("Compositor bridge: first frame");
            } else if pushed % 60 == 0 {
                let elapsed = t_start.elapsed().as_secs_f64();
                let fps = pushed as f64 / elapsed;
                log::info!("Compositor bridge: {} frames, {:.1} fps", pushed, fps);
            }
        }
    }

    log::info!("Compositor bridge thread exiting ({} frames)", pushed);
}
