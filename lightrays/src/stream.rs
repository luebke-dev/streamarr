//! StreamSession — GStreamer Wayland compositor + WebRTC pipeline.
//!
//! Manages the headless Smithay Wayland compositor (waylanddisplaysrc) and
//! bridges frames to a WebRTC pipeline with hardware H.264 encoding.
//!
//! All Python/PyO3 code has been removed — callbacks go through
//! `tokio::sync::mpsc` channels instead of Python callables.

use crate::input;

use glib::prelude::*;
use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_app as gst_app;
use gstreamer_sdp as gst_sdp;
use gstreamer_webrtc as gst_webrtc;

use parking_lot::Mutex;
use std::sync::atomic::{AtomicBool, AtomicU64, Ordering};
use std::sync::Arc;
use tokio::sync::mpsc;

use crate::encoder::{build_encoder_pipeline, select_encoder, H264_MAX_WIDTH};

// ─────────────────────────────────────────────────────────────────────────────
// Signaling messages (sent from GStreamer threads → async WS handler)
// ─────────────────────────────────────────────────────────────────────────────

pub enum SignalingMessage {
    SdpOffer(String),
    IceCandidate { mline_index: u32, candidate: String },
}

// ─────────────────────────────────────────────────────────────────────────────
// Lifecycle phase
// ─────────────────────────────────────────────────────────────────────────────

/// Lifecycle phase of a [`StreamSession`].
///
/// Transitions are linear: `Created -> CompositorRunning -> Streaming`.
/// `stop_webrtc_pipeline` moves `Streaming` back to `CompositorRunning`
/// for the reconnect-grace window; `stop` is a one-way trip to `Stopped`
/// from any state. Methods that depend on a particular phase reject
/// out-of-phase calls instead of corrupting the in-flight pipeline.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Phase {
    Created,
    CompositorRunning,
    Streaming,
    Stopped,
}

// ─────────────────────────────────────────────────────────────────────────────
// StreamSession
// ─────────────────────────────────────────────────────────────────────────────

/// Resources owned by a running compositor pipeline. All fields here are
/// alive iff the session's `Phase` is `CompositorRunning` or `Streaming`;
/// a `None` `Option<Compositor>` therefore matches `Created` or `Stopped`
/// without needing a separate flag per element.
pub(crate) struct Compositor {
    pub(crate) pipeline: gst::Pipeline,
    pub(crate) element: Option<gst::Element>,
    /// Held for future live-caps updates; currently the encoder pipeline
    /// is rebuilt around a fresh capsfilter so this isn't read at runtime.
    #[allow(dead_code)]
    pub(crate) capsfilter: Option<gst::Element>,
    /// `start_webrtc` takes ownership of the sink for the bridge loop, so
    /// after that point the compositor only holds the pipeline + element.
    pub(crate) sink: Option<gst_app::AppSink>,
    /// Wayland socket name (`wayland-0`, …) — already returned by
    /// `start_compositor` to the caller; cached on the struct so future
    /// code (env passthrough to spawned containers) can read it back.
    #[allow(dead_code)]
    pub(crate) wayland_display: String,
}

/// Resources owned by a running WebRTC pipeline. Alive iff `Phase` is
/// `Streaming`; teardown back to `CompositorRunning` clears this struct
/// without touching the compositor.
pub(crate) struct Webrtc {
    pub(crate) pipeline: gst::Pipeline,
    pub(crate) webrtcbin: gst::Element,
    pub(crate) bridge_thread: Option<std::thread::JoinHandle<()>>,
}

pub(crate) struct SessionInner {
    pub(crate) phase: Phase,
    // Configuration
    pub(crate) xdg_runtime_dir: String,
    pub(crate) render_node: String,
    // Stream/encode resolution — what the encoder produces and the
    // browser receives. Updated by `change_resolution` via videoscale,
    // so the live stream can match the browser window without forcing
    // the wayland compositor (and the game it hosts) to renegotiate.
    pub(crate) width: u32,
    pub(crate) height: u32,
    // Compositor / virtual display resolution — fixed for the lifetime
    // of the session at whatever size was passed to `start_compositor`.
    // Sending a live wayland configure to the game container causes
    // long stalls (~45 s of frozen output) on most games because they
    // don't acknowledge the new size promptly; the game itself stays
    // at this resolution and videoscale bridges to `width`/`height`.
    pub(crate) compositor_width: u32,
    pub(crate) compositor_height: u32,
    pub(crate) fps: u32,

    // WebRTC config (stored for pipeline restart on resize)
    pub(crate) webrtc_bitrate_kbps: u32,
    pub(crate) webrtc_audio_device: String,
    pub(crate) webrtc_pulse_server: String,
    pub(crate) webrtc_stun_server: String,
    pub(crate) webrtc_turn_server: String,

    // Pipeline state — grouped so the lifecycle can be expressed by which
    // of these is `Some(...)` instead of by a sprawling set of individual
    // Option<Element> fields. See [`Phase`] for the transition rules.
    pub(crate) compositor: Option<Compositor>,
    pub(crate) webrtc: Option<Webrtc>,
    /// Shared with the bridge thread so it can observe a stop request.
    /// Lives outside [`Webrtc`] because `start_webrtc` resets the flag
    /// before constructing the rest of the WebRTC state.
    pub(crate) bridge_stop: Arc<AtomicBool>,

    // Resize coalescing: a fullscreen toggle in the browser typically
    // produces several rapid resize messages (ResizeObserver fires per
    // animation frame). Without coalescing we tear down and rebuild the
    // entire WebRTC pipeline for every intermediate size and the cascade
    // never settles on a stable resolution. Track only the final desired
    // size and let the in-flight resize observe it when it finishes.
    pub(crate) resize_in_progress: bool,
    pub(crate) pending_target: Option<(u32, u32)>,

    // Channel to async WebSocket handler
    pub(crate) signaling_tx: Option<mpsc::UnboundedSender<SignalingMessage>>,
}

/// High-performance streaming session managing compositor + WebRTC pipelines.
#[derive(Clone)]
pub struct StreamSession {
    inner: Arc<Mutex<SessionInner>>,
}

impl StreamSession {
    pub fn new(
        xdg_runtime_dir: String,
        render_node: String,
        width: u32,
        height: u32,
        fps: u32,
    ) -> anyhow::Result<Self> {
        gst::init()?;

        Ok(Self {
            inner: Arc::new(Mutex::new(SessionInner {
                phase: Phase::Created,
                xdg_runtime_dir,
                render_node,
                width,
                height,
                compositor_width: width,
                compositor_height: height,
                fps,
                webrtc_bitrate_kbps: 0,
                webrtc_audio_device: String::new(),
                webrtc_pulse_server: String::new(),
                webrtc_stun_server: String::new(),
                webrtc_turn_server: String::new(),
                compositor: None,
                webrtc: None,
                bridge_stop: Arc::new(AtomicBool::new(false)),
                resize_in_progress: false,
                pending_target: None,
                signaling_tx: None,
            })),
        })
    }

    // ── Compositor ──────────────────────────────────────────────────────

    /// Start the waylanddisplaysrc compositor pipeline.
    /// Returns the WAYLAND_DISPLAY socket name.
    pub fn start_compositor(&self) -> anyhow::Result<String> {
        let (xdg, render, w, h, fps) = {
            let inner = self.inner.lock();
            if inner.phase != Phase::Created {
                anyhow::bail!(
                    "start_compositor called from phase {:?}; expected Created",
                    inner.phase
                );
            }
            (
                inner.xdg_runtime_dir.clone(),
                inner.render_node.clone(),
                inner.compositor_width,
                inner.compositor_height,
                inner.fps,
            )
        };

        // Build the compositor without holding the lock — wayland startup
        // can take a few hundred ms and the lock is shared with signal
        // callbacks that fire on GStreamer's internal threads.
        let (compositor, display) = crate::pipeline::compositor::start(&xdg, &render, w, h, fps)?;

        let mut inner = self.inner.lock();
        inner.compositor = Some(compositor);
        inner.phase = Phase::CompositorRunning;
        Ok(display)
    }

    // ── WebRTC ──────────────────────────────────────────────────────────

    /// Start WebRTC pipeline with encoding + bridging.
    /// The `signaling_tx` channel is used to send SDP offers and ICE candidates
    /// to the async WebSocket handler.
    pub fn start_webrtc(
        &self,
        bitrate_kbps: u32,
        audio_device: &str,
        pulse_server: &str,
        stun_server: &str,
        turn_server: &str,
        signaling_tx: mpsc::UnboundedSender<SignalingMessage>,
    ) -> anyhow::Result<()> {
        let mut inner = self.inner.lock();
        if inner.phase != Phase::CompositorRunning {
            anyhow::bail!(
                "start_webrtc called from phase {:?}; expected CompositorRunning",
                inner.phase
            );
        }
        inner.signaling_tx = Some(signaling_tx);

        // Store config for pipeline restart on resize
        inner.webrtc_bitrate_kbps = bitrate_kbps;
        inner.webrtc_audio_device = audio_device.to_string();
        inner.webrtc_pulse_server = pulse_server.to_string();
        inner.webrtc_stun_server = stun_server.to_string();
        inner.webrtc_turn_server = turn_server.to_string();

        let (encoder_name, is_h265) = select_encoder(inner.width);
        let encoder_fragment =
            build_encoder_pipeline(&encoder_name, bitrate_kbps, inner.fps, is_h265);

        // Pin the encoder's input resolution with a videoscale + caps filter.
        // The wayland compositor's caps don't switch instantly during a
        // resolution change (`change_resolution` updates the compositor
        // capsfilter, but in-flight frames are still at the old size). Without
        // this filter the VA-API encoder sees a caps change on the first
        // post-resize frame and stalls (the `gst_video_frame_copy` assertion
        // the pipeline-rebuild was supposed to avoid). With a fixed downstream
        // caps, videoscale absorbs the transient mismatch and the encoder
        // only ever sees one resolution.
        let (out_w, out_h) = if inner.width > H264_MAX_WIDTH {
            let scale = H264_MAX_WIDTH as f64 / inner.width as f64;
            let scaled_h = ((inner.height as f64 * scale) as u32) & !1; // even number
            log::info!(
                "Scaling {}x{} → {}x{} for H.264 compatibility",
                inner.width,
                inner.height,
                H264_MAX_WIDTH,
                scaled_h
            );
            (H264_MAX_WIDTH, scaled_h)
        } else {
            (inner.width, inner.height)
        };
        let scale_fragment = format!("videoscale ! video/x-raw,width={out_w},height={out_h} ! ");

        // H.264 vs H.265 parse + RTP payloader
        let (parse_pay, rtp_caps) = if is_h265 {
            (
                "h265parse config-interval=-1 ! rtph265pay aggregate-mode=zero-latency config-interval=-1 pt=96".to_string(),
                "application/x-rtp,media=video,encoding-name=H265,payload=96".to_string(),
            )
        } else {
            (
                "h264parse config-interval=-1 ! rtph264pay aggregate-mode=zero-latency config-interval=-1 pt=96".to_string(),
                "application/x-rtp,media=video,encoding-name=H264,payload=96".to_string(),
            )
        };

        // Audio source
        let audio_source = if !audio_device.is_empty() {
            let ps = if !pulse_server.is_empty() {
                format!(" server={pulse_server}")
            } else {
                String::new()
            };
            format!("pulsesrc{ps} device={audio_device}")
        } else {
            "audiotestsrc wave=ticks is-live=true".to_string()
        };

        let pipeline_str = format!(
            "appsrc name=wolf_wl_src is-live=true do-timestamp=true \
               format=time max-buffers=4 block=true \
             ! queue max-size-buffers=4 max-size-bytes=0 max-size-time=0 leaky=downstream \
             ! {scale_fragment}{encoder_fragment}\
             {parse_pay} \
             ! {rtp_caps} \
             ! webrtcbin name=webrtc bundle-policy=max-bundle \
             {audio_source} \
             ! queue max-size-buffers=10 leaky=downstream \
             ! audioconvert ! audioresample \
             ! audio/x-raw,rate=48000,channels=2,format=S16LE \
             ! opusenc bitrate=128000 frame-size=10 \
             ! rtpopuspay pt=97 \
             ! queue max-size-buffers=10 leaky=downstream \
             ! application/x-rtp,media=audio,encoding-name=OPUS,payload=97 \
             ! webrtc."
        );

        log::info!("WebRTC pipeline: {}", pipeline_str);

        let pipeline = gst::parse::launch(&pipeline_str)?;
        let pipeline = pipeline
            .downcast::<gst::Pipeline>()
            .map_err(|_| anyhow::anyhow!("Not a Pipeline"))?;

        let webrtcbin = pipeline
            .by_name("webrtc")
            .ok_or_else(|| anyhow::anyhow!("webrtcbin not found in pipeline"))?;

        // Configure ICE servers
        crate::webrtc::configure_ice(
            &webrtcbin,
            &inner.webrtc_stun_server,
            &inner.webrtc_turn_server,
        );

        // Setup signal handlers (negotiation, ICE, state changes, bus)
        crate::webrtc::setup_signals(&webrtcbin, &pipeline, &self.inner);

        // Pad probes to measure framerate at various pipeline stages
        let encoder = pipeline
            .by_name("vaapiencodeh264-0")
            .or_else(|| pipeline.by_name("vaapiencodeh265-0"))
            .or_else(|| pipeline.by_name("vah264lpenc0"))
            .or_else(|| pipeline.by_name("vah265lpenc0"));
        if let Some(encoder) = encoder {
            let start = std::time::Instant::now();
            // Input pad
            if let Some(pad) = encoder.static_pad("sink") {
                let counter = Arc::new(AtomicU64::new(0));
                pad.add_probe(gst::PadProbeType::BUFFER, move |_pad, _info| {
                    let n = counter.fetch_add(1, Ordering::Relaxed) + 1;
                    if n % 60 == 0 {
                        let secs = start.elapsed().as_secs_f64();
                        log::info!("Encoder INPUT: {} frames, {:.1} fps", n, n as f64 / secs);
                    }
                    gst::PadProbeReturn::Ok
                });
            }
            // Output pad
            if let Some(pad) = encoder.static_pad("src") {
                let counter = Arc::new(AtomicU64::new(0));
                let start2 = std::time::Instant::now();
                pad.add_probe(gst::PadProbeType::BUFFER, move |_pad, _info| {
                    let n = counter.fetch_add(1, Ordering::Relaxed) + 1;
                    if n % 60 == 0 {
                        let secs = start2.elapsed().as_secs_f64();
                        log::info!("Encoder OUTPUT: {} frames, {:.1} fps", n, n as f64 / secs);
                    }
                    gst::PadProbeReturn::Ok
                });
            }
        }

        // Prepare bridge components (but don't start thread yet — wait for PLAYING)
        let bridge_components = if let Some(compositor) = inner.compositor.as_mut() {
            let compositor_sink = match compositor.sink.take() {
                Some(sink) => sink,
                None => {
                    log::info!("compositor_sink not cached, attempting downcast now");
                    compositor
                        .pipeline
                        .by_name("compositor_sink")
                        .ok_or_else(|| anyhow::anyhow!("compositor_sink not found"))?
                        .downcast::<gst_app::AppSink>()
                        .map_err(|_| anyhow::anyhow!("compositor_sink downcast failed"))?
                }
            };

            let webrtc_appsrc = pipeline
                .by_name("wolf_wl_src")
                .ok_or_else(|| anyhow::anyhow!("wolf_wl_src not found in WebRTC pipeline"))?
                .downcast::<gst_app::AppSrc>()
                .map_err(|_| anyhow::anyhow!("wolf_wl_src is not an AppSrc"))?;

            inner.bridge_stop.store(false, Ordering::SeqCst);
            let stop_flag = Arc::clone(&inner.bridge_stop);
            Some((compositor_sink, webrtc_appsrc, stop_flag))
        } else {
            None
        };

        // Set pipeline to PLAYING — ensures webrtcbin starts ICE/DTLS.
        // On failure, check the bus for the actual element error.
        if pipeline.set_state(gst::State::Playing).is_err() {
            let mut detail = String::from("unknown element");
            if let Some(bus) = pipeline.bus() {
                // Drain pending error messages to find out which element failed
                while let Some(msg) = bus.pop_filtered(&[gst::MessageType::Error]) {
                    if let gst::MessageView::Error(e) = msg.view() {
                        let src_name = msg.src().map(|s| s.name().to_string()).unwrap_or_default();
                        detail = format!("{}: {}", src_name, e.error());
                        log::error!("Pipeline element failed: {} — {}", src_name, e.error());
                        if let Some(dbg) = e.debug() {
                            log::error!("  debug: {}", dbg);
                        }
                    }
                }
            }
            let _ = pipeline.set_state(gst::State::Null);
            anyhow::bail!("Pipeline failed to go PLAYING ({})", detail);
        }

        // Create data channel for input events
        crate::webrtc::setup_data_channel(&webrtcbin, &self.inner);

        // Start compositor bridge AFTER pipeline is PLAYING. This avoids
        // pushing frames before webrtcbin is ready, which would cause
        // stale data bursts when ICE/DTLS completes.
        let bridge_thread =
            if let Some((compositor_sink, webrtc_appsrc, stop_flag)) = bridge_components {
                let thread = std::thread::Builder::new()
                    .name("compositor-bridge".into())
                    .spawn(move || {
                        crate::pipeline::bridge::run(compositor_sink, webrtc_appsrc, stop_flag);
                    })?;
                log::info!("Compositor bridge started (after pipeline PLAYING)");
                Some(thread)
            } else {
                None
            };

        inner.webrtc = Some(Webrtc {
            pipeline,
            webrtcbin,
            bridge_thread,
        });
        inner.phase = Phase::Streaming;

        log::info!("WebRTC pipeline started");
        Ok(())
    }

    // ── Signaling helpers ───────────────────────────────────────────────

    /// Set remote SDP answer from the browser.
    pub fn set_remote_answer(&self, sdp_text: &str) -> anyhow::Result<()> {
        let inner = self.inner.lock();
        let webrtc = inner
            .webrtc
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("WebRTC not started"))?;

        let sdp = gst_sdp::SDPMessage::parse_buffer(sdp_text.as_bytes())
            .map_err(|e| anyhow::anyhow!("Failed to parse SDP answer: {e}"))?;

        let answer =
            gst_webrtc::WebRTCSessionDescription::new(gst_webrtc::WebRTCSDPType::Answer, sdp);

        let promise = gst::Promise::new();
        webrtc
            .webrtcbin
            .emit_by_name::<()>("set-remote-description", &[&answer, &promise]);
        promise.interrupt();

        log::info!("Remote SDP answer set");
        Ok(())
    }

    /// Add ICE candidate from the browser.
    pub fn add_ice_candidate(&self, mline_index: u32, candidate: &str) -> anyhow::Result<()> {
        let inner = self.inner.lock();
        let webrtc = inner
            .webrtc
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("WebRTC not started"))?;

        log::debug!(
            "Adding remote ICE candidate (mline={}): {:.80}",
            mline_index,
            candidate
        );
        webrtc
            .webrtcbin
            .emit_by_name::<()>("add-ice-candidate", &[&mline_index, &candidate.to_string()]);
        Ok(())
    }

    /// Send a JSON input event to the compositor.
    pub fn send_input(&self, json_str: &str) {
        let inner = self.inner.lock();
        if let Some(el) = inner.compositor.as_ref().and_then(|c| c.element.as_ref()) {
            input::handle_input_json(
                el,
                json_str,
                inner.compositor_width,
                inner.compositor_height,
            );
        }
    }

    /// Request an IDR keyframe from the encoder.
    pub fn request_keyframe(&self) {
        let inner = self.inner.lock();
        if let Some(webrtc) = inner.webrtc.as_ref() {
            let structure = gst::Structure::builder("GstForceKeyUnit")
                .field("all-headers", true)
                .build();
            let event = gst::event::CustomUpstream::new(structure);
            webrtc.pipeline.send_event(event);
        }
    }

    // ── WebRTC teardown (for resize) ───────────────────────────────────

    /// Stop the bridge thread and WebRTC pipeline, but keep the compositor
    /// running and preserve the signaling channel.  Used by
    /// `change_resolution` to rebuild the encoder pipeline at the new size.
    fn stop_webrtc(&self) {
        // Take ownership of resources under a brief lock — the actual
        // GStreamer teardown must NOT hold `inner`, because webrtcbin signal
        // callbacks (`on-ice-candidate`, data-channel `on-message-string`)
        // try to acquire the same lock from the pipeline's internal threads.
        // Holding it across `pipeline.set_state(Null)` deadlocks when an
        // active ICE/TURN connection emits a final event during teardown.
        let webrtc = {
            let mut inner = self.inner.lock();
            inner.bridge_stop.store(true, Ordering::SeqCst);
            inner.webrtc.take()
        };

        // Stop the pipeline FIRST. The bridge thread may be blocked inside
        // `webrtc_src.push_sample()` because the downstream encoder is
        // stalled — in that state it cannot observe `bridge_stop` and a
        // plain `join` would hang for tens of seconds. Setting the pipeline
        // to NULL flushes appsrc, push_sample returns FlowError::Flushing,
        // and the bridge loop exits cleanly.
        if let Some(webrtc) = webrtc {
            if let Some(bus) = webrtc.pipeline.bus() {
                bus.remove_signal_watch();
            }
            let _ = webrtc.pipeline.set_state(gst::State::Null);
            let _ = webrtc.pipeline.state(gst::ClockTime::from_seconds(3));
            log::info!("WebRTC pipeline stopped");

            // Now the bridge is unblocked, join it (no lock held).
            if let Some(thread) = webrtc.bridge_thread {
                let _ = thread.join();
            }
        }

        // NOTE: signaling_tx is kept — we reuse the same channel for the
        //       rebuilt pipeline so the existing WebSocket keeps working.
        // NOTE: compositor.sink was already taken by start_webrtc;
        //       start_webrtc will look it up from the compositor pipeline.
        let mut inner = self.inner.lock();
        // Drop back to CompositorRunning when we tore down a live stream;
        // if we were already stopped (full teardown path) keep that state.
        if inner.phase == Phase::Streaming {
            inner.phase = Phase::CompositorRunning;
        }
    }

    /// Stop only the WebRTC pipeline and bridge thread while keeping the
    /// compositor and application container alive for reconnect grace.
    pub fn stop_webrtc_pipeline(&self) {
        self.stop_webrtc();
    }

    // ── Resolution change (pipeline restart) ────────────────────────────

    /// Change the compositor resolution by tearing down the WebRTC
    /// pipeline, updating the capsfilter while no downstream consumer
    /// exists, and rebuilding a fresh encoder pipeline at the new size.
    ///
    /// This avoids the `gst_video_frame_copy` assertion that occurs when
    /// VA-API hardware encoders receive buffers at a different resolution
    /// than their internal state during a live caps renegotiation.
    pub fn change_resolution(&self, width: u32, height: u32) -> anyhow::Result<()> {
        // Round to even numbers — H.264/H.265 encoders require even dimensions
        let width = (width + 1) & !1;
        let height = (height + 1) & !1;

        if width < 64 || height < 64 || width > 7680 || height > 4320 {
            anyhow::bail!(
                "Resolution {}x{} out of range (64–7680 × 64–4320)",
                width,
                height
            );
        }

        // ── Coalesce rapid resize requests ──
        // Record the latest target. If another invocation is already running
        // the rebuild, hand off to it (it will observe our pending_target
        // when it finishes its current iteration). Otherwise become the
        // owner of the rebuild loop. This collapses a flurry of fullscreen
        // animation events into at most one extra rebuild instead of N.
        {
            let mut inner = self.inner.lock();
            inner.pending_target = Some((width, height));
            if inner.resize_in_progress {
                return Ok(());
            }
            inner.resize_in_progress = true;
        }

        // Ensure the in-progress flag is always cleared on exit, even on
        // early return from the `?` operator inside the loop.
        struct InProgressGuard<'a>(&'a Mutex<SessionInner>);
        impl Drop for InProgressGuard<'_> {
            fn drop(&mut self) {
                let mut inner = self.0.lock();
                inner.resize_in_progress = false;
                inner.pending_target = None;
            }
        }
        let _guard = InProgressGuard(&self.inner);

        loop {
            // Pick up the latest target the user has asked for.
            let (
                target_w,
                target_h,
                old_w,
                old_h,
                bitrate,
                audio_device,
                pulse_server,
                signaling_tx,
            ) = {
                let inner = self.inner.lock();
                let (tw, th) = match inner.pending_target {
                    Some(t) => t,
                    None => return Ok(()),
                };

                // Nothing to do — already at the target size.
                if tw == inner.width && th == inner.height {
                    return Ok(());
                }

                // Dead zone: skip changes ≤ 8 px in both axes.
                let dw = (tw as i64 - inner.width as i64).unsigned_abs();
                let dh = (th as i64 - inner.height as i64).unsigned_abs();
                if dw <= 8 && dh <= 8 {
                    log::debug!(
                            "Resolution change {}x{} → {}x{} suppressed (Δ{}×Δ{} within 8 px dead zone)",
                            inner.width, inner.height, tw, th, dw, dh
                        );
                    return Ok(());
                }

                let signaling_tx =
                    inner.signaling_tx.as_ref().cloned().ok_or_else(|| {
                        anyhow::anyhow!("No signaling channel for WebRTC restart")
                    })?;

                (
                    tw,
                    th,
                    inner.width,
                    inner.height,
                    inner.webrtc_bitrate_kbps,
                    inner.webrtc_audio_device.clone(),
                    inner.webrtc_pulse_server.clone(),
                    signaling_tx,
                )
            };

            log::info!(
                "Stream resolution change {}x{} → {}x{}: rebuilding encoder pipeline",
                old_w,
                old_h,
                target_w,
                target_h
            );

            // ── Stop WebRTC pipeline + bridge ──
            self.stop_webrtc();

            // Update only the *stream* resolution. The wayland compositor
            // keeps producing at its original size; videoscale in the new
            // pipeline bridges between the two. Live wayland resolution
            // changes stall the game (~45 s) on every resize and result
            // in the picture reverting to the original size anyway.
            {
                let mut inner = self.inner.lock();
                inner.width = target_w;
                inner.height = target_h;
            }

            // ── Rebuild WebRTC pipeline at the new resolution ──
            let (stun_server, turn_server) = {
                let inner = self.inner.lock();
                (
                    inner.webrtc_stun_server.clone(),
                    inner.webrtc_turn_server.clone(),
                )
            };
            self.start_webrtc(
                bitrate,
                &audio_device,
                &pulse_server,
                &stun_server,
                &turn_server,
                signaling_tx,
            )?;

            log::info!(
                "Resolution change complete: {}x{} → {}x{} — WebRTC pipeline restarted",
                old_w,
                old_h,
                target_w,
                target_h
            );

            // If the user requested a different size while we were rebuilding,
            // loop and apply it. Otherwise we're done.
            {
                let mut inner = self.inner.lock();
                match inner.pending_target {
                    Some((pw, ph)) if pw == target_w && ph == target_h => {
                        inner.pending_target = None;
                        return Ok(());
                    }
                    None => return Ok(()),
                    _ => {} // new target arrived — continue the loop
                }
            }
        }
    }

    /// Stop all pipelines and release resources.
    pub fn stop(&self) {
        // Stop WebRTC pipeline + bridge thread (reuses stop_webrtc logic)
        self.stop_webrtc();

        let mut inner = self.inner.lock();

        // Stop compositor pipeline. Taking ownership drops the contained
        // element/capsfilter/sink with the struct.
        if let Some(compositor) = inner.compositor.take() {
            let _ = compositor.pipeline.set_state(gst::State::Null);
            log::info!("Compositor pipeline stopped");
        }

        // Clean up sockets
        crate::pipeline::compositor::cleanup_stale_sockets(&inner.xdg_runtime_dir);

        // Clear channel
        inner.signaling_tx = None;
        inner.phase = Phase::Stopped;
    }

    /// Returns the current lifecycle phase. Useful for tests and metrics.
    #[cfg(test)]
    pub fn phase(&self) -> Phase {
        self.inner.lock().phase
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn new_session() -> StreamSession {
        StreamSession::new(
            "/tmp/lightrays-test".to_string(),
            "/dev/null".to_string(),
            1920,
            1080,
            60,
        )
        .expect("new session")
    }

    #[test]
    fn new_session_starts_in_created_phase() {
        let session = new_session();
        assert_eq!(session.phase(), Phase::Created);
    }

    #[test]
    fn start_webrtc_rejects_before_compositor() {
        let session = new_session();
        let (tx, _rx) = mpsc::unbounded_channel();
        let err = session
            .start_webrtc(5000, "", "", "", "", tx)
            .expect_err("phase guard rejects");
        assert!(
            err.to_string().contains("expected CompositorRunning"),
            "{err}"
        );
    }

    #[test]
    fn stop_transitions_to_stopped() {
        let session = new_session();
        session.stop();
        assert_eq!(session.phase(), Phase::Stopped);
    }

    #[test]
    fn start_compositor_rejects_when_already_stopped() {
        let session = new_session();
        session.stop();
        let err = session
            .start_compositor()
            .expect_err("phase guard rejects after stop");
        assert!(err.to_string().contains("expected Created"), "{err}");
    }
}
