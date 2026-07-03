//! WebRTC helper functions and GStreamer signal handlers.
//!
//! [`configure_ice`] and [`redact_turn_url`] are pure helpers; the
//! `setup_*` functions register closures on a `webrtcbin` element that
//! read [`SessionInner`] through an `Arc<Mutex<_>>`. Those signal
//! callbacks fire on GStreamer's internal threads, so they take the lock
//! briefly and never block on async work.

use crate::input;
use crate::stream::{SessionInner, SignalingMessage};

use glib::prelude::*;
use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_webrtc as gst_webrtc;

use parking_lot::Mutex;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;

/// Configure STUN and TURN servers on the webrtcbin element. TURN URLs
/// contain credentials in the userinfo portion, so the log line uses
/// [`redact_turn_url`] to avoid leaking them.
pub fn configure_ice(webrtcbin: &gst::Element, stun_server: &str, turn_server: &str) {
    if !stun_server.is_empty() {
        webrtcbin.set_property_from_str("stun-server", stun_server);
        log::info!("STUN server: {}", stun_server);
    }
    if !turn_server.is_empty() {
        webrtcbin.set_property_from_str("turn-server", turn_server);
        log::info!("TURN server: {}", redact_turn_url(turn_server));
    }
}

/// Replace the userinfo (`user:pass@`) part of a TURN URL with
/// `<redacted>` so the credentials don't end up in plaintext logs.
pub fn redact_turn_url(url: &str) -> String {
    if let Some((scheme, rest)) = url.split_once("://") {
        if let Some((_creds, host)) = rest.split_once('@') {
            return format!("{scheme}://<redacted>@{host}");
        }
    }
    url.to_string()
}

/// Trigger SDP offer generation on the given webrtcbin and forward the
/// resulting offer to the WebSocket handler through `signaling_tx`. The
/// callback runs on GStreamer's promise thread; it takes the lock just
/// long enough to read the channel sender.
pub fn create_offer(webrtcbin: &gst::Element, inner_arc: &Arc<Mutex<SessionInner>>) {
    let webrtcbin_clone = webrtcbin.clone();
    let inner_arc_clone = Arc::clone(inner_arc);

    let promise = gst::Promise::with_change_func(move |reply| match reply {
        Ok(Some(reply)) => {
            let offer = match reply.get::<gst_webrtc::WebRTCSessionDescription>("offer") {
                Ok(offer) => offer,
                Err(e) => {
                    log::error!("Failed to get offer from reply: {}", e);
                    return;
                }
            };

            // Set local description
            let promise_local = gst::Promise::new();
            webrtcbin_clone.emit_by_name::<()>("set-local-description", &[&offer, &promise_local]);
            promise_local.interrupt();

            // Get SDP text
            let sdp_text = match offer.sdp().as_text() {
                Ok(text) => text,
                Err(e) => {
                    log::error!("Failed to get SDP text: {}", e);
                    return;
                }
            };

            log::info!("SDP offer created ({} bytes)", sdp_text.len());

            let inner = inner_arc_clone.lock();
            if let Some(tx) = &inner.signaling_tx {
                let _ = tx.send(SignalingMessage::SdpOffer(sdp_text));
            }
        }
        Ok(None) => {
            log::error!("SDP offer promise returned empty reply");
        }
        Err(e) => {
            log::error!("SDP offer promise error: {:?}", e);
        }
    });

    webrtcbin.emit_by_name::<()>("create-offer", &[&None::<gst::Structure>, &promise]);
}

/// Register all WebRTC signal handlers: negotiation, ICE candidates,
/// connection state, and bus message watch.
pub fn setup_signals(
    webrtcbin: &gst::Element,
    pipeline: &gst::Pipeline,
    inner_arc: &Arc<Mutex<SessionInner>>,
) {
    // on-negotiation-needed → create offer
    {
        log::info!("Registering on-negotiation-needed signal handler");
        let webrtcbin_weak = webrtcbin.downgrade();
        let inner_clone = Arc::clone(inner_arc);
        webrtcbin.connect("on-negotiation-needed", false, move |_values| {
            log::info!("WebRTC negotiation needed — creating offer");
            if let Some(webrtcbin) = webrtcbin_weak.upgrade() {
                create_offer(&webrtcbin, &inner_clone);
            }
            None
        });
    }

    // on-ice-candidate → forward via channel
    {
        let inner_clone = Arc::clone(inner_arc);
        webrtcbin.connect("on-ice-candidate", false, move |values| {
            let mline_index: u32 = match values.get(1).and_then(|v| v.get().ok()) {
                Some(v) => v,
                None => {
                    log::warn!("on-ice-candidate signal missing mline index — skipping");
                    return None;
                }
            };
            let candidate: String = match values.get(2).and_then(|v| v.get().ok()) {
                Some(v) => v,
                None => {
                    log::warn!("on-ice-candidate signal missing candidate string — skipping");
                    return None;
                }
            };
            log::debug!("ICE candidate (mline={}): {:.80}", mline_index, candidate);

            let inner = inner_clone.lock();
            if let Some(tx) = &inner.signaling_tx {
                let _ = tx.send(SignalingMessage::IceCandidate {
                    mline_index,
                    candidate,
                });
            }
            None
        });
    }

    // ICE connection state → force keyframe ONCE on first connect
    {
        let pipeline_weak = pipeline.downgrade();
        let keyframe_sent = Arc::new(AtomicBool::new(false));
        webrtcbin.connect_notify(Some("ice-connection-state"), move |webrtcbin, _| {
            let state: gst_webrtc::WebRTCICEConnectionState =
                webrtcbin.property("ice-connection-state");
            log::info!("ICE connection state: {:?}", state);

            if (state == gst_webrtc::WebRTCICEConnectionState::Connected
                || state == gst_webrtc::WebRTCICEConnectionState::Completed)
                && !keyframe_sent.swap(true, Ordering::SeqCst)
            {
                log::info!("ICE connected — forcing initial keyframe");
                if let Some(pipeline) = pipeline_weak.upgrade() {
                    let structure = gst::Structure::builder("GstForceKeyUnit")
                        .field("all-headers", true)
                        .build();
                    let event = gst::event::CustomUpstream::new(structure);
                    pipeline.send_event(event);
                }
            }
        });
    }

    // Peer connection state
    webrtcbin.connect_notify(Some("connection-state"), |webrtcbin, _| {
        let state: gst_webrtc::WebRTCPeerConnectionState = webrtcbin.property("connection-state");
        log::info!("WebRTC connection state: {:?}", state);
    });

    // Bus message watch — newly created pipelines always have a bus.
    let bus = pipeline.bus().expect("pipeline bus");
    bus.add_signal_watch();
    bus.connect_message(None, |_bus, msg| match msg.view() {
        gst::MessageView::Error(e) => {
            log::error!(
                "WebRTC pipeline ERROR: {}\n{}",
                e.error(),
                e.debug().unwrap_or_default()
            );
        }
        gst::MessageView::Warning(w) => {
            log::warn!(
                "WebRTC pipeline WARNING: {}\n{}",
                w.error(),
                w.debug().unwrap_or_default()
            );
        }
        gst::MessageView::Eos(_) => {
            log::info!("WebRTC pipeline EOS");
        }
        gst::MessageView::StateChanged(sc) => {
            if let Some(src) = msg.src() {
                if src.type_() == gst::Pipeline::static_type() {
                    log::info!(
                        "Pipeline state: {:?} → {:?} (pending: {:?})",
                        sc.old(),
                        sc.current(),
                        sc.pending()
                    );
                }
            }
        }
        _ => {}
    });
}

/// Create the WebRTC data channel for input events with fallback.
///
/// The data channel is the primary input transport (low latency, no
/// signaling round-trip). The WebSocket path is still available as a
/// fallback in case the browser-side `RTCDataChannel.send` fails.
pub fn setup_data_channel(webrtcbin: &gst::Element, inner_arc: &Arc<Mutex<SessionInner>>) {
    let options = gst::Structure::builder("application/x-datachannel")
        .field("ordered", true)
        .build();

    let channel_result: Result<glib::Object, _> =
        std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| {
            webrtcbin.emit_by_name::<glib::Object>("create-data-channel", &[&"input", &options])
        }));

    match channel_result {
        Ok(channel) => {
            channel.connect("on-open", false, |_| {
                log::info!("WebRTC data channel 'input' opened");
                None
            });

            let inner_clone = Arc::clone(inner_arc);
            channel.connect("on-message-string", false, move |values| {
                if let Ok(message) = values[1].get::<String>() {
                    // Input maps to the *compositor* coordinate space —
                    // that's where the game's surface lives. The stream
                    // resolution (inner.width/height) is decoupled and
                    // only affects encoder output, not input geometry.
                    let (el_opt, w, h) = {
                        let inner = inner_clone.lock();
                        (
                            inner.compositor.as_ref().and_then(|c| c.element.clone()),
                            inner.compositor_width,
                            inner.compositor_height,
                        )
                    };
                    if let Some(el) = el_opt {
                        input::handle_input_json(&el, &message, w, h);
                    }
                }
                None
            });

            log::info!("WebRTC data channel 'input' created");
        }
        Err(_) => {
            log::warn!("Data channel creation failed — input will use WebSocket fallback");
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn redact_strips_credentials() {
        assert_eq!(
            redact_turn_url("turn://user:pass@host:3478"),
            "turn://<redacted>@host:3478"
        );
    }

    #[test]
    fn redact_passes_through_creds_free_urls() {
        assert_eq!(redact_turn_url("turn://host:3478"), "turn://host:3478");
        assert_eq!(redact_turn_url("turns://host:5349"), "turns://host:5349");
    }

    #[test]
    fn redact_handles_urls_without_scheme() {
        // Pyrate sometimes stores the bare host:port; the helper should
        // not crash and should leave it untouched.
        assert_eq!(redact_turn_url("host:3478"), "host:3478");
    }
}
