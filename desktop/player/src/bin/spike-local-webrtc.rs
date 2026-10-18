//! Local WebRTC proof for the decode chain — no Lightrays server needed.
//!
//! Why this exists: spike 0.1 could not prove that the client actually decodes
//! video, because the test server's disk was full and it could not start a
//! session (launch returned HTTP 500). The decode chain is the single most
//! important assumption of the whole game-streaming path, so it should not be
//! left unverified while waiting for a server.
//!
//! This runs the same element chain the real client uses for every video buffer:
//!
//! ```text
//!   videotestsrc -> vah264enc -> rtph264pay -> webrtcbin (sendonly)
//!                                                  |
//!                                          (real ICE + DTLS on loopback)
//!                                                  v
//!   webrtcbin (recvonly) -> rtph264depay -> h264parse -> vah264dec
//!                        -> videoconvert -> fakesink
//! ```
//!
//! Two `webrtcbin` elements negotiate with each other over the loopback
//! interface, so ICE, DTLS and SRTP all really run. What differs from production
//! is *only* the signalling transport: this wires the SDP directly between the
//! two elements instead of through the Lightrays WebSocket. Everything that
//! touches the media path — depayload, parse, decode, the encoder the server
//! actually uses (`vah264enc`) — is identical.
//!
//! Run with: cargo run --features spike --bin spike-local-webrtc
//! Exit code 0 means frames were decoded.

use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Arc;
use std::time::Duration;

use gstreamer as gst;
use gstreamer::prelude::*;
use gstreamer_webrtc as gst_webrtc;

/// Frames the receiver decoded. The whole point of the run.
type Counter = Arc<AtomicU64>;

fn main() {
    if let Err(err) = run() {
        eprintln!("FAILED: {err}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    gst::init()?;
    let main_loop = glib::MainLoop::new(None, false);

    let pipeline = gst::Pipeline::new();
    // The receiver stays a plain element; only the sender needs the bin.
    let recv = gst::ElementFactory::make("webrtcbin")
        .name("recv")
        .build()?;
    pipeline.add(&recv)?;

    // ── Sender: pattern -> encode -> RTP -> webrtcbin ──
    //
    // Built as a `parse::launch` string with the encoder linked straight into
    // webrtcbin, which is exactly how Lightrays assembles its pipeline
    // (`lightrays/src/stream.rs`). Requesting the sink pad by hand *before* the
    // element is running produced an offer with no media line (82 bytes) and no
    // frames: webrtcbin never learned a direction for the transceiver.
    //
    // `vah264enc` is the encoder the server selects on AMD
    // (lightrays/src/encoder.rs), so the bytes decoded here are produced the way
    // a real session produces them.
    let sender_desc = "videotestsrc is-live=true ! \
         video/x-raw,width=1280,height=720,framerate=30/1 ! \
         vah264enc ! h264parse config-interval=1 ! \
         rtph264pay pt=96 ! \
         application/x-rtp,media=video,encoding-name=H264,payload=96 ! \
         webrtcbin name=send bundle-policy=max-bundle";
    let sender = gst::parse::launch(sender_desc)?;
    let send = sender
        .downcast::<gst::Bin>()
        .map_err(|_| "sender did not parse to a bin")?;
    let send_webrtc = send
        .by_name("send")
        .ok_or("sender bin has no `send` element")?;
    pipeline.add(&send)?;

    // ── Receiver: webrtcbin -> depay -> parse -> decode -> sink ──
    let frames: Counter = Arc::new(AtomicU64::new(0));
    let decoded: Counter = Arc::new(AtomicU64::new(0));
    let decoded_for_pad = decoded.clone();
    let pipeline_weak = pipeline.downgrade();

    recv.connect_pad_added(move |_recv, pad| {
        let Some(caps) = pad.current_caps() else {
            return;
        };
        let Some(structure) = caps.structure(0) else {
            return;
        };
        // Only the media pad matters; webrtcbin also emits data-channel pads.
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
        println!("receiver: video RTP pad, encoding-name={encoding}");

        let Some(pipeline) = pipeline_weak.upgrade() else {
            return;
        };
        if let Err(err) = attach_decode_branch(&pipeline, pad, decoded_for_pad.clone()) {
            eprintln!("could not attach decode branch: {err}");
        }
    });

    // ── Negotiation ──
    // The sender offers, the receiver answers, exactly as the server and client
    // do — just without a network in between.
    let send_for_offer = send_webrtc.clone();
    let recv_for_offer = recv.clone();
    let frames_for_probe = frames.clone();

    let (ready_tx, ready_rx) = std::sync::mpsc::channel::<()>();

    let promise = gst::Promise::with_change_func(move |reply| {
        let reply = match reply {
            Ok(Some(reply)) => reply,
            Ok(None) => {
                eprintln!("create-offer produced an empty reply");
                return;
            }
            Err(err) => {
                eprintln!("create-offer promise error: {err:?}");
                return;
            }
        };
        // Print what actually arrived. `get` failing says nothing about *why*,
        // and the first version of this binary stopped at "no offer field"
        // without showing the structure it was looking in.
        // A failed create-offer reports itself as an `error` field, so print its
        // value — the field names alone do not say what went wrong.
        for (name, value) in reply.iter() {
            // A GError prints as a bare pointer, which is useless; pull the
            // message out properly.
            if name == "error" {
                match reply.get::<glib::Error>("error") {
                    Ok(err) => eprintln!("create-offer failed: {err}"),
                    Err(_) => eprintln!("create-offer failed (unreadable error field)"),
                }
                continue;
            }
            eprintln!("offer reply field `{name}` = {value:?}");
        }
        let offer = match reply.get::<gst_webrtc::WebRTCSessionDescription>("offer") {
            Ok(offer) => offer,
            Err(err) => {
                eprintln!("offer reply had no usable `offer` field: {err:?}");
                return;
            }
        };
        println!(
            "offer created ({} bytes of SDP)",
            offer.sdp().as_text().map(|t| t.len()).unwrap_or(0)
        );

        // Settle the offer on the sender...
        let local = gst::Promise::new();
        send_for_offer.emit_by_name::<()>("set-local-description", &[&offer, &local]);
        local.interrupt();
        // ...and hand it to the receiver as the remote description.
        let remote = gst::Promise::new();
        recv_for_offer.emit_by_name::<()>("set-remote-description", &[&offer, &remote]);
        remote.interrupt();

        // Now the receiver answers.
        let recv_for_answer = recv_for_offer.clone();
        let send_for_answer = send_for_offer.clone();
        let ready = ready_tx.clone();
        // A clone for the emit below, because the closure takes ownership.
        let recv_to_emit = recv_for_answer.clone();
        let answer_promise = gst::Promise::with_change_func(move |reply| {
            let Ok(Some(reply)) = reply else {
                eprintln!("create-answer produced no reply");
                return;
            };
            let Ok(answer) = reply.get::<gst_webrtc::WebRTCSessionDescription>("answer") else {
                eprintln!("answer reply had no `answer` field");
                return;
            };
            println!("answer created");
            let local = gst::Promise::new();
            recv_for_answer.emit_by_name::<()>("set-local-description", &[&answer, &local]);
            local.interrupt();
            let remote = gst::Promise::new();
            send_for_answer.emit_by_name::<()>("set-remote-description", &[&answer, &remote]);
            remote.interrupt();
            let _ = ready.send(());
        });
        recv_to_emit
            .emit_by_name::<()>("create-answer", &[&None::<gst::Structure>, &answer_promise]);
    });
    // PLAYING *first*. `create-offer` answers "webrtcbin is closed" if the
    // element has not started, and the error arrives inside the promise where it
    // is easy to misread as a missing field.
    pipeline.set_state(gst::State::Playing)?;
    // A bin added to a pipeline does not follow the parent's state change on its
    // own; without this the whole sender stays PAUSED while the pipeline reports
    // PLAYING, and nothing is ever encoded. (Diagnosed from the bus: every
    // element inside the bin reported "-> Paused" and never progressed.)
    send.sync_state_with_parent()?;

    // Offer creation is triggered by `on-negotiation-needed`, which is what
    // Lightrays relies on (`lightrays/src/webrtc.rs::setup_signals`). Calling
    // create-offer directly after set_state produced a well-formed 546-byte offer
    // with a media line, yet no RTP ever flowed — consistent with the element not
    // having been ready. The promise is shared with that callback, so both paths
    // use the same continuation.
    // Offer created directly. `on-negotiation-needed` is what Lightrays uses, but
    // this path yields a valid 546-byte offer with a media line, and the open
    // question is narrower: whether ICE completes on loopback.
    send_webrtc.emit_by_name::<()>("create-offer", &[&None::<gst::Structure>, &promise]);

    // ── ICE candidate exchange ──
    //
    // This is the part that a network normally provides. Two webrtcbin elements in
    // one process do *not* discover each other: without this wiring ICE stays in
    // "new", the transport never becomes ready and the sender's payloader blocks
    // after a single buffer. (Diagnosed from ENCODED=1 and no ICE state at all.)
    {
        let recv_for_candidates = recv.clone();
        send_webrtc.connect("on-ice-candidate", false, move |values| {
            let mline: u32 = values[1].get().unwrap_or(0);
            let candidate: String = values[2].get().unwrap_or_default();
            if !candidate.is_empty() {
                recv_for_candidates.emit_by_name::<()>("add-ice-candidate", &[&mline, &candidate]);
            }
            None
        });
    }
    {
        let send_for_candidates = send_webrtc.clone();
        recv.connect("on-ice-candidate", false, move |values| {
            let mline: u32 = values[1].get().unwrap_or(0);
            let candidate: String = values[2].get().unwrap_or_default();
            if !candidate.is_empty() {
                send_for_candidates.emit_by_name::<()>("add-ice-candidate", &[&mline, &candidate]);
            }
            None
        });
    }

    // ── State logging: the evidence that ICE and DTLS really completed ──
    for (name, element) in [("sender", &send_webrtc), ("receiver", &recv)] {
        let label = name.to_string();
        element.connect_notify(Some("ice-connection-state"), move |el, _| {
            let state: gst_webrtc::WebRTCICEConnectionState = el.property("ice-connection-state");
            println!("{label} ICE: {state:?}");
        });
        let label = name.to_string();
        element.connect_notify(Some("connection-state"), move |el, _| {
            let state: gst_webrtc::WebRTCPeerConnectionState = el.property("connection-state");
            println!("{label} peer connection: {state:?}");
        });
    }

    // Count encoded buffers too, so a zero decode count can be told apart from
    // "nothing was ever sent".
    // Count encoded buffers inside the sender bin, so a zero decode count can be
    // told apart from "nothing was ever sent".
    let frames_probe = frames_for_probe.clone();
    // `parse::launch` names elements by factory plus an index (`rtph264pay0`), so
    // match on the factory name rather than a hard-coded index — the index shifts
    // whenever the pipeline string changes.
    let payloader = send
        .iterate_elements()
        .into_iter()
        .flatten()
        .find(|el| {
            el.factory()
                .map(|f| f.name() == "rtph264pay")
                .unwrap_or(false)
        })
        .ok_or("sender bin has no rtph264pay element")?;
    println!("counting encoded buffers on {}", payloader.name());
    let pad = payloader
        .static_pad("sink")
        .ok_or("payloader has no sink pad")?;
    pad.add_probe(gst::PadProbeType::BUFFER, move |_, _| {
        frames_probe.fetch_add(1, Ordering::Relaxed);
        gst::PadProbeReturn::Ok
    });

    // Wait for the answer, then let the media flow.
    match ready_rx.recv_timeout(Duration::from_secs(15)) {
        Ok(()) => println!("negotiation complete, waiting for frames"),
        Err(_) => {
            eprintln!("negotiation did not complete within 15s");
            return Err("negotiation timed out".into());
        }
    }

    // The state reached and anything the bus complained about. Zero frames has
    // several causes (state not reached, caps negotiation failed, no RTP) and the
    // frame counters alone cannot tell them apart.
    std::thread::sleep(Duration::from_millis(1500));
    println!(
        "pipeline state: {:?}",
        pipeline.state(gst::ClockTime::ZERO).1
    );
    if let Some(bus) = pipeline.bus() {
        while let Some(msg) = bus.pop() {
            use gst::MessageView;
            match msg.view() {
                MessageView::Error(err) => {
                    eprintln!(
                        "BUS ERROR from {:?}: {}",
                        err.src().map(|s| s.name()),
                        err.error()
                    );
                    if let Some(debug) = err.debug() {
                        eprintln!("  debug: {debug}");
                    }
                }
                MessageView::Warning(warn) => {
                    eprintln!("bus warning: {}", warn.error());
                }
                MessageView::StateChanged(sc) => {
                    if let Some(src) = sc.src() {
                        println!("state change: {} -> {:?}", src.name(), sc.current());
                    }
                }
                _ => {}
            }
        }
    }

    let decoded_final = decoded.clone();
    let encoded_final = frames.clone();
    let loop_clone = main_loop.clone();
    glib::timeout_add_seconds_local(12, move || {
        println!();
        println!("ENCODED={}", encoded_final.load(Ordering::Relaxed));
        println!("DECODED={}", decoded_final.load(Ordering::Relaxed));
        loop_clone.quit();
        glib::ControlFlow::Break
    });

    main_loop.run();
    pipeline.set_state(gst::State::Null)?;

    let decoded_count = decoded.load(Ordering::Relaxed);
    let encoded_count = frames.load(Ordering::Relaxed);
    println!();
    if decoded_count > 0 {
        println!("RESULT: {decoded_count} frames decoded from {encoded_count} encoded");
        println!("        the decode chain works");
        Ok(())
    } else {
        eprintln!("RESULT: no frames decoded ({encoded_count} encoded)");
        Err("decode chain produced no frames".into())
    }
}

/// Builds `depay -> parse -> decode -> convert -> fakesink` for a negotiated pad.
///
/// The decoder preference order matches the real client: hardware first, software
/// as fallback, so a pass here means the same chain that production uses works.
fn attach_decode_branch(
    pipeline: &gst::Pipeline,
    pad: &gst::Pad,
    decoded: Counter,
) -> Result<(), Box<dyn std::error::Error>> {
    let depay = gst::ElementFactory::make("rtph264depay").build()?;
    let parse = gst::ElementFactory::make("h264parse").build()?;
    let (decoder, used) = match gst::ElementFactory::make("vah264dec").build() {
        Ok(el) => (el, "vah264dec (hardware)"),
        Err(_) => (
            gst::ElementFactory::make("avdec_h264").build()?,
            "avdec_h264 (software)",
        ),
    };
    let convert = gst::ElementFactory::make("videoconvert").build()?;
    // `fakesink` because this proves decoding, not display — the window path is
    // covered by spike 0.2.
    let sink = gst::ElementFactory::make("fakesink")
        .property("sync", false)
        .build()?;
    println!("decode branch using {used}");

    // Added to the *existing* pipeline. A separate pipeline produces
    // "Pads have no common grandparent" when linking to this one's pad, because
    // the two pads then live in unrelated bin hierarchies.
    pipeline.add_many([&depay, &parse, &decoder, &convert, &sink])?;
    gst::Element::link_many([&depay, &parse, &decoder, &convert, &sink])?;

    let counter = decoded.clone();
    sink.static_pad("sink").ok_or("sink has no pad")?.add_probe(
        gst::PadProbeType::BUFFER,
        move |_, _| {
            counter.fetch_add(1, Ordering::Relaxed);
            gst::PadProbeReturn::Ok
        },
    );

    let sink_pad = depay.static_pad("sink").ok_or("depay has no sink pad")?;
    pad.link(&sink_pad)?;
    // Each new element must be brought up to the pipeline's current state; the
    // pipeline is already PLAYING by the time a pad appears.
    for element in [&depay, &parse, &decoder, &convert, &sink] {
        element.sync_state_with_parent()?;
    }
    Ok(())
}
