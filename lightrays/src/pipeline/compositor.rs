//! Headless Wayland compositor startup.
//!
//! Wraps `waylanddisplaysrc` + a capsfilter + an `appsink` into a GStreamer
//! pipeline and waits up to five seconds for the wayland-server thread to
//! post its `WAYLAND_DISPLAY` application message. Returns the freshly
//! built [`Compositor`] handle and the socket name (`wayland-0`, …) so
//! the caller can pass it on to spawned containers.

use crate::stream::Compositor;

use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_app as gst_app;

use std::os::unix::fs::PermissionsExt;

/// Remove stale `wayland-*` and `sway-ipc.*` sockets left behind by a
/// crashed previous session — `waylanddisplaysrc` refuses to bind a
/// socket name that already exists.
pub fn cleanup_stale_sockets(xdg_runtime_dir: &str) {
    let dir = match std::fs::read_dir(xdg_runtime_dir) {
        Ok(d) => d,
        Err(_) => return,
    };
    for entry in dir.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        // Only reap `wayland-*`: waylanddisplaysrc refuses to bind a socket
        // name that already exists, so a crashed session's leftover must go.
        // Do NOT touch `sway-ipc.<uid>.<pid>.sock`: those names are pid-unique
        // (a new sway never needs to reclaim them) and /tmp/sockets is a
        // shared mount, so reaping them here would wipe the LIVE IPC socket of
        // another running sway session — breaking its resize/control channel.
        if name.starts_with("wayland-") {
            if let Err(e) = std::fs::remove_file(entry.path()) {
                log::debug!("Failed to remove stale socket {}: {}", name, e);
            } else {
                log::debug!("Removed stale socket: {}", name);
            }
        }
    }
}

/// Start the `waylanddisplaysrc` compositor pipeline at the given size
/// and frame rate. Returns the populated [`Compositor`] plus the socket
/// name (`wayland-0`, ...).
pub fn start(
    xdg_runtime_dir: &str,
    render_node: &str,
    width: u32,
    height: u32,
    fps: u32,
) -> anyhow::Result<(Compositor, String)> {
    std::fs::create_dir_all(xdg_runtime_dir).ok();
    cleanup_stale_sockets(xdg_runtime_dir);

    let render_node = if std::path::Path::new(render_node).exists() {
        render_node.to_string()
    } else {
        log::info!("No GPU render node, using software rendering");
        "software".to_string()
    };

    let pipeline_str = format!(
        "waylanddisplaysrc render_node={render_node} name=wolf_wl_src \
         ! capsfilter name=res_filter \
           caps=video/x-raw,width={width},height={height},framerate={fps}/1 \
         ! appsink name=compositor_sink emit-signals=false \
           sync=false max-buffers=2 drop=true"
    );

    log::info!(
        "Compositor pipeline: {}x{}@{}fps render_node={}",
        width,
        height,
        fps,
        render_node
    );

    let pipeline = gst::parse::launch(&pipeline_str)?;
    let pipeline = pipeline
        .downcast::<gst::Pipeline>()
        .map_err(|_| anyhow::anyhow!("Not a Pipeline"))?;

    let bus = pipeline
        .bus()
        .ok_or_else(|| anyhow::anyhow!("No bus on compositor pipeline"))?;

    pipeline.set_state(gst::State::Playing)?;

    // Wait for the WAYLAND_DISPLAY application message (5 s timeout)
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(5);
    while std::time::Instant::now() < deadline {
        let timeout = gst::ClockTime::from_mseconds(100);
        if let Some(msg) = bus.timed_pop(timeout) {
            match msg.view() {
                gst::MessageView::Application(app) => {
                    if let Some(s) = app.structure() {
                        if s.name().as_str() == "wayland.src" {
                            if let Ok(display) = s.get::<String>("WAYLAND_DISPLAY") {
                                log::info!("Wayland compositor ready: {}", display);

                                // 0o770: owner + group access (no world-writable);
                                // app containers join the same group via UID/GID
                                // remap and connect through the socket.
                                let socket_path = format!("{}/{}", xdg_runtime_dir, display);
                                let lock_path = format!("{}.lock", socket_path);
                                let _ = std::fs::set_permissions(
                                    &socket_path,
                                    std::fs::Permissions::from_mode(0o770),
                                );
                                let _ = std::fs::set_permissions(
                                    &lock_path,
                                    std::fs::Permissions::from_mode(0o660),
                                );

                                let element = pipeline.by_name("wolf_wl_src");
                                let capsfilter = pipeline.by_name("res_filter");
                                let sink = pipeline
                                    .by_name("compositor_sink")
                                    .and_then(|el| el.downcast::<gst_app::AppSink>().ok());

                                let compositor = Compositor {
                                    pipeline,
                                    element,
                                    capsfilter,
                                    sink,
                                    wayland_display: display.clone(),
                                };
                                return Ok((compositor, display));
                            }
                        }
                    }
                }
                gst::MessageView::Error(e) => {
                    let _ = pipeline.set_state(gst::State::Null);
                    anyhow::bail!("waylanddisplaysrc error: {}", e.error());
                }
                _ => {}
            }
        }
    }

    let _ = pipeline.set_state(gst::State::Null);
    anyhow::bail!("waylanddisplaysrc did not post WAYLAND_DISPLAY within 5s")
}
