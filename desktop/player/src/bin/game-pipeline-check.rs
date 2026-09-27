//! Live proof that the pipeline module really decodes (plan task 3.3).
//!
//! Spike 0.1 proved the decode chain by hand. This proves that the *module* — the plan it
//! builds, the decoder chain it selects, the sink it chooses — produces the same result.
//! A plan that is merely well-shaped would be worthless if the elements it names cannot be
//! linked.
//!
//! It runs the same shape as `spike-local-webrtc`: two `webrtcbin` elements negotiate over
//! loopback, so real ICE, DTLS and SRTP are involved and nothing is faked except the
//! network. The receiver side is assembled from
//! [`streamarr_desktop_player::game_pipeline`], which is the point of the exercise.
//!
//! Run from `desktop/player`:
//!
//! ```text
//! cargo run --features spike --bin game-pipeline-check
//! ```
//!
//! Exit code 0 means frames were decoded.

#![cfg(feature = "spike")]

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;

use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_webrtc as gst_webrtc;
use streamarr_desktop_player::game_pipeline::{
    attach_decode_branch, make_webrtcbin, DecodePlan, DisplayServer, Platform, VideoCodec,
};

type Counter = Arc<AtomicU64>;

fn main() {
    if let Err(error) = run() {
        eprintln!("FEHLER: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    gst::init()?;

    // The plan this module would use on a real machine — but headless, because the proof
    // is about decoding, not about drawing (spike 0.2 covers the window).
    let platform = Platform::current();
    let display = DisplayServer::current();
    let plan = DecodePlan::new(VideoCodec::H264, platform, display, true);
    println!("Pipeline-Plan: {}", plan.describe());
    println!("Plattform: {platform:?}, Anzeige: {display:?}");
    println!();

    // The decoder chain the plan selected has to be checked against what exists, so a
    // missing element is named here rather than showing up as "no pictures".
    for candidate in &plan.decoder_candidates {
        let exists = gst::ElementFactory::find(candidate).is_some();
        println!(
            "  Dekoder {candidate:<16} {}",
            if exists { "vorhanden" } else { "fehlt" }
        );
    }
    println!();

    let pipeline = gst::Pipeline::new();

    let recv = make_webrtcbin("recv")?;

    // ── Sender: pattern -> encode -> RTP -> webrtcbin ──
    // The sender exists only to give the receiver something real to decode. It uses the
    // same encoder family the server does (`lightrays/src/encoder.rs`).
    // Copied from the spike, which is known to reach 421 decoded frames. Two details are
    // load-bearing and were missing in the first version of this file:
    //
    //   * `h264parse config-interval=1` — without it the SPS/PPS are sent only once, in
    //     the first buffer, and the receiver's decoder never gets them again. The pipeline
    //     then links, negotiates and decodes nothing.
    //   * the explicit `application/x-rtp` caps between payloader and `webrtcbin` — this is
    //     what tells `webrtcbin` which payload type and codec the transceiver carries.
    let sender_bin = gst::parse::bin_from_description(
        "videotestsrc is-live=true ! \
         video/x-raw,width=1280,height=720,framerate=30/1 ! \
         vah264enc ! h264parse config-interval=1 ! \
         rtph264pay name=pay0 pt=96 ! \
         application/x-rtp,media=video,encoding-name=H264,payload=96 ! \
         webrtcbin name=send bundle-policy=max-bundle",
        true,
    )?;
    let send_bin = sender_bin
        .clone()
        .downcast::<gst::Bin>()
        .map_err(|_| "der Sender ist keine Bin")?;
    let send_webrtc = send_bin
        .by_name("send")
        .ok_or("der Sender hat kein webrtcbin")?;

    pipeline.add_many([send_bin.upcast_ref(), &recv])?;

    // ── Receiver: the module's plan, built for real ──
    let decoded: Counter = Arc::new(AtomicU64::new(0));
    let decoded_for_pad = decoded.clone();
    let pipeline_weak = pipeline.downgrade();

    recv.connect_pad_added(move |_recv, pad| {
        // Printed first, before any early return: whether the signal fires at all is the
        // first thing to know, and a silent early return hides it.
        println!("  Pad aufgetaucht: {}", pad.name());
        let Some(caps) = pad.current_caps() else {
            println!("    (noch keine Caps)");
            return;
        };
        let Some(structure) = caps.structure(0) else {
            return;
        };
        if structure.name() != "application/x-rtp" {
            return;
        }
        let media = structure.get::<String>("media").ok().unwrap_or_default();
        if media != "video" {
            return;
        }
        let encoding = structure
            .get::<String>("encoding-name")
            .unwrap_or_else(|_| "?".to_string());
        println!("Empfänger: Video-RTP-Pad, encoding-name={encoding}");

        // The codec comes from what the server announced, not from an assumption.
        let Some(codec) = VideoCodec::from_encoding_name(&encoding) else {
            eprintln!("unbekannter Codec: {encoding}");
            return;
        };
        let plan = DecodePlan::new(codec, platform, display, true);

        let Some(pipeline) = pipeline_weak.upgrade() else {
            return;
        };
        match attach_decode_branch(&pipeline, &plan, decoded_for_pad.clone()) {
            Ok(first) => {
                // The branch starts with its own jitter buffer, so the RTP pad links
                // straight into it. One branch per RTP pad: two pads sharing a buffer
                // would interleave their packets.
                let Some(entry_sink) = first.static_pad("sink") else {
                    eprintln!("der Empfangszweig hat kein Eingangs-Pad");
                    return;
                };
                if pad.link(&entry_sink).is_err() {
                    eprintln!("das RTP-Pad ließ sich nicht verbinden");
                    return;
                }
                println!("  Empfangszweig gebaut: {}", plan.describe());
            }
            Err(error) => eprintln!("  Empfangszweig fehlgeschlagen: {error}"),
        }
    });

    // ── Negotiation: sender offers, receiver answers ──
    // The same sequence the spike proved: local description on the sender, remote on the
    // receiver, then the answer back. The promises are interrupted where the spike
    // interrupts them, which is what keeps this from waiting on an answer it does not need.
    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<()>();
    let recv_for_offer = recv.clone();
    let send_for_offer = send_webrtc.clone();

    let promise = gst::Promise::with_change_func(move |reply| {
        let Ok(Some(reply)) = reply else {
            eprintln!("create-offer lieferte keine Antwort");
            return;
        };
        let Ok(offer) = reply.get::<gst_webrtc::WebRTCSessionDescription>("offer") else {
            eprintln!("kein Angebot in der Antwort");
            return;
        };
        println!("Angebot erstellt");

        let local = gst::Promise::new();
        send_for_offer.emit_by_name::<()>("set-local-description", &[&offer, &local]);
        local.interrupt();
        let remote = gst::Promise::new();
        recv_for_offer.emit_by_name::<()>("set-remote-description", &[&offer, &remote]);
        remote.interrupt();

        let recv_for_answer = recv_for_offer.clone();
        let send_for_answer = send_for_offer.clone();
        let ready = ready_tx.clone();
        let recv_to_emit = recv_for_answer.clone();
        let answer_promise = gst::Promise::with_change_func(move |reply| {
            let Ok(Some(reply)) = reply else { return };
            let Ok(answer) = reply.get::<gst_webrtc::WebRTCSessionDescription>("answer") else {
                eprintln!("keine Antwort im Ergebnis");
                return;
            };
            println!("Antwort erstellt");
            let local = gst::Promise::new();
            recv_for_answer.emit_by_name::<()>("set-local-description", &[&answer, &local]);
            local.interrupt();
            let remote = gst::Promise::new();
            send_for_answer.emit_by_name::<()>("set-remote-description", &[&answer, &remote]);
            remote.interrupt();
            let _ = ready.send(());
        });
        // Two arguments, not one: the signal is `create-answer(options, promise)`.
        recv_to_emit
            .emit_by_name::<()>("create-answer", &[&None::<gst::Structure>, &answer_promise]);
    });

    pipeline.set_state(gst::State::Playing)?;
    // A bin added to a pipeline does not follow the parent's state change on its own:
    // without this the whole sender stays PAUSED while the pipeline reports PLAYING, and
    // nothing is ever encoded (diagnosed in spike 0.1 from the bus).
    send_bin.sync_state_with_parent()?;

    // ── Diagnose: does the sender encode at all? ──
    // A zero decode count has two very different causes — nothing encoded, or nothing
    // received — and they look identical from the outside.
    let encoded: Counter = Arc::new(AtomicU64::new(0));
    if let Some(payloader) = send_bin.by_name("pay0") {
        if let Some(pad) = payloader.static_pad("src") {
            let counter = encoded.clone();
            pad.add_probe(gst::PadProbeType::BUFFER, move |_, _| {
                counter.fetch_add(1, Ordering::Relaxed);
                gst::PadProbeReturn::Ok
            });
            println!("Zähler am Sender-Payloader angebracht");
        } else {
            println!("Sender-Payloader hat kein src-Pad");
        }
    } else {
        println!("Sender-Bin hat kein pay0 — der Bin-Name stimmt nicht");
    }

    // ── State logging: the evidence that ICE and DTLS really completed ──
    // Without this a zero decode count cannot be distinguished from "ICE never finished",
    // and the two have nothing in common.
    for (name, element) in [("Sender", &send_webrtc), ("Empfänger", &recv)] {
        let label = name.to_string();
        element.connect_notify(Some("ice-connection-state"), move |el, _| {
            let state: gst_webrtc::WebRTCICEConnectionState = el.property("ice-connection-state");
            println!("{label} ICE: {state:?}");
        });
        let label = name.to_string();
        element.connect_notify(Some("connection-state"), move |el, _| {
            let state: gst_webrtc::WebRTCPeerConnectionState = el.property("connection-state");
            println!("{label} Peer-Verbindung: {state:?}");
        });
    }

    // Now the offer. It must come *after* PLAYING: `webrtcbin` answers "webrtcbin is
    // closed" otherwise (defect found in spike 0.1).
    send_webrtc.emit_by_name::<()>("create-offer", &[&None::<gst::Structure>, &promise]);

    // ── ICE: what a network would do ──
    // Wired after the offer, matching the spike — which is known to reach
    // `ICE: Completed` and 421 decoded frames.
    wire_ice(&send_webrtc, &recv);
    wire_ice(&recv, &send_webrtc);

    // ── Run ──
    let bus = pipeline.bus().ok_or("kein Bus")?;
    let deadline = std::time::Instant::now() + std::time::Duration::from_secs(30);
    while std::time::Instant::now() < deadline {
        if let Some(message) = bus.timed_pop(gst::ClockTime::from_mseconds(200)) {
            use gst::MessageView;
            match message.view() {
                MessageView::Error(error) => {
                    eprintln!("Pipeline-Fehler: {} ({:?})", error.error(), error.debug());
                    break;
                }
                MessageView::Eos(_) => break,
                _ => {}
            }
        }
        if decoded.load(Ordering::Relaxed) > 0 {
            // A few more frames, so the count is a rate rather than a race.
            if decoded.load(Ordering::Relaxed) >= 10 {
                break;
            }
        }
    }

    let _ = pipeline.set_state(gst::State::Null);
    let _ = ready_rx.recv_timeout(std::time::Duration::from_millis(50));

    let count = decoded.load(Ordering::Relaxed);
    let encoded_count = encoded.load(Ordering::Relaxed);
    println!();
    println!("ENCODED={encoded_count} DECODED={count}");
    if count > 0 {
        println!("RESULT: {count} Bilder dekodiert — die Pipeline aus game_pipeline trägt.");
        Ok(())
    } else {
        Err("die Pipeline hat keine Bilder geliefert".into())
    }
}

/// Connects the ICE candidates of one element to the other.
///
/// The part a network normally provides. Kept minimal: the two elements are in one
/// process, so every candidate is directly reachable.
fn wire_ice(from: &gst::Element, to: &gst::Element) {
    let to = to.clone();
    from.connect("on-ice-candidate", false, move |values| {
        let mline: u32 = values[1].get().unwrap_or(0);
        let candidate: String = values[2].get().unwrap_or_default();
        // An empty candidate is the end-of-candidates marker; forwarding it would add a
        // second, bogus candidate.
        if !candidate.is_empty() {
            to.emit_by_name::<()>("add-ice-candidate", &[&mline, &candidate]);
        }
        None
    });
}
