//! Spike 0.1: minimal native WebRTC client for Lightrays.
//!
//! Purpose is to prove the *client* half of the game-streaming path before any
//! of it is wired into the app: connect to a running Lightrays session, answer
//! the server's SDP offer, trickle ICE, and decode the incoming H.264.
//!
//! Deliberately throwaway in structure but not in care: every message it sends
//! or parses goes through [`streamarr_desktop_player::protocol`], so a green run
//! validates the committed wire contract against a live server rather than
//! against our own assumptions.
//!
//! ## Direction of negotiation
//!
//! The server is **always the offerer**. `lightrays/src/server.rs` dispatches
//! only `answer`, `ice`, `keyframe` and `resize` from a client — there is no
//! handler for a client offer. This mirrors the browser client, where
//! `useLightraysStreaming.js` waits for `{"type":"offer"}` and replies with an
//! answer. A native client must do the same.
//!
//! ## GStreamer API notes
//!
//! `webrtcbin` is driven through **signals**, not typed methods: `create-answer`
//! and `set-remote-description` are emitted with `emit_by_name` and a
//! `gst::Promise` carries the asynchronous reply. The pattern follows
//! `lightrays/src/webrtc.rs`, which is the one implementation in this repository
//! known to work against the same GStreamer version.
//!
//! Usage:
//!   cargo run --features spike --bin spike-webrtc -- <ws-url> <ticket> [--render]

use std::sync::{Arc, Mutex};

use futures_util::{SinkExt, StreamExt};
use glib::prelude::*;

use gstreamer as gst;
use gstreamer_webrtc as gst_webrtc;
use gstreamer_webrtc::prelude::*;
use streamarr_desktop_player::protocol::{ClientMessage, ServerMessage, INPUT_CHANNEL_LABEL};
use tokio_tungstenite::tungstenite::client::IntoClientRequest;
use tokio_tungstenite::tungstenite::http::HeaderValue;
use tokio_tungstenite::tungstenite::Message;

type BoxError = Box<dyn std::error::Error + Send + Sync>;

fn main() {
    if let Err(err) = run() {
        eprintln!("spike failed: {err}");
        std::process::exit(1);
    }
}

thread_local! {
    /// The server-created input data channel.
    ///
    /// Thread-local on purpose: `glib::Object` is thread-affine, so it cannot
    /// live in a `Shared` struct that crosses into the async task.
    static INPUT_CHANNEL: std::cell::RefCell<Option<glib::Object>> =
        const { std::cell::RefCell::new(None) };
}

/// State shared between the GLib callbacks and the async signalling task.
///
/// GStreamer objects are thread-affine and not `Send`, so this struct is only
/// ever touched from GLib callback threads. The async signalling task never
/// sees it — it communicates through channels and through the message sender
/// extracted in [`Shared::input_sender`], which is `Send`.
struct Shared {
    /// `webrtcbin` is held as a plain `gst::Element`: the `WebRTCBin` wrapper
    /// type does not exist in gstreamer-webrtc 0.23, and `lightrays` uses the
    /// element directly for the same reason.
    webrtc: Mutex<Option<gst::Element>>,
    /// Set once the answer has been sent, so ICE is not trickled before the
    /// remote description exists.
    answered: Mutex<bool>,
}

fn run() -> Result<(), BoxError> {
    let args: Vec<String> = std::env::args().collect();
    let positional: Vec<&String> = args[1..].iter().filter(|a| !a.starts_with("--")).collect();
    if positional.len() < 2 {
        eprintln!("usage: spike-webrtc <websocket-url> <ticket> [--render]");
        std::process::exit(64);
    }
    let url = positional[0].clone();
    let ticket = positional[1].clone();
    let render = args.iter().any(|a| a == "--render");

    gst::init()?;
    let main_loop = glib::MainLoop::new(None, false);

    let pipeline = gst::Pipeline::new();
    let webrtc = gst::ElementFactory::make("webrtcbin")
        .name("recvonly")
        .build()?;
    pipeline.add(&webrtc)?;

    let shared = Arc::new(Shared {
        webrtc: Mutex::new(Some(webrtc.clone())),
        answered: Mutex::new(false),
    });

    // GLib signal callbacks are not async, so they hand messages to the tokio
    // task through an unbounded channel.
    let (outbound_tx, outbound_rx) = tokio::sync::mpsc::unbounded_channel::<String>();

    // ── ICE candidates ──
    let ice_tx = outbound_tx.clone();
    webrtc.connect("on-ice-candidate", false, move |values| {
        let mline_index: u32 = match values.get(1).and_then(|v| v.get().ok()) {
            Some(v) => v,
            None => return None,
        };
        let candidate: String = match values.get(2).and_then(|v| v.get().ok()) {
            Some(v) => v,
            None => return None,
        };
        if !candidate.is_empty() {
            let _ = ice_tx.send(
                ClientMessage::Ice {
                    candidate,
                    mline_index,
                }
                .to_json(),
            );
        }
        None
    });

    // ── Video branch ──
    let pipeline_weak = pipeline.downgrade();
    webrtc.connect_pad_added(move |_webrtc, pad| {
        let Some(caps) = pad.current_caps() else {
            return;
        };
        let Some(structure) = caps.structure(0) else {
            return;
        };

        let is_video = structure.name().starts_with("application/x-rtp")
            && structure.get::<String>("media").ok().as_deref() == Some("video");
        if !is_video {
            println!("ignoring non-video pad: {}", structure.name());
            return;
        }

        let Some(pipeline) = pipeline_weak.upgrade() else {
            return;
        };
        if let Err(err) = attach_video_branch(&pipeline, pad, render) {
            eprintln!("failed to attach video branch: {err}");
        }
    });

    // ── Connection state logging: the clearest signal that ICE succeeded ──
    webrtc.connect_notify(Some("ice-connection-state"), |webrtc, _| {
        let state: gst_webrtc::WebRTCICEConnectionState = webrtc.property("ice-connection-state");
        println!("ICE connection state: {state:?}");
    });
    webrtc.connect_notify(Some("connection-state"), |webrtc, _| {
        let state: gst_webrtc::WebRTCPeerConnectionState = webrtc.property("connection-state");
        println!("peer connection state: {state:?}");
    });

    pipeline.set_state(gst::State::Playing)?;

    // ── Input data channel ──
    //
    // The client does NOT create this channel: the *server* creates it
    // (`lightrays/src/stream.rs` calls `setup_data_channel`), exactly as the
    // browser client expects — `useLightraysStreaming.js` only listens on
    // `pc.ondatachannel` and never calls `createDataChannel`.
    //
    // Creating one here as well produced a second, conflicting channel
    // description: the two sides never agreed on the SDP and the server
    // re-offered continuously, observed as an endless offer/answer loop.
    //
    // The channel lives in a `thread_local` rather than in `Shared`, because a
    // `glib::Object` is thread-affine and therefore not `Send`. Everything that
    // touches it runs on the GLib main thread, so thread-local storage is both
    // sufficient and the only correct place for it.
    webrtc.connect("on-data-channel", false, move |values| {
        let channel = match values[1].get::<glib::Object>() {
            Ok(channel) => channel,
            Err(_) => return None,
        };
        let label: String = channel.property("label");
        println!("<- server opened data channel: {label}");
        if label == INPUT_CHANNEL_LABEL {
            channel.connect("on-open", false, |_| {
                println!("input data channel opened");
                None
            });
            INPUT_CHANNEL.with(|slot| *slot.borrow_mut() = Some(channel));
        }
        None
    });

    // ── Signalling on tokio ──
    // The async task never touches GStreamer. It owns the socket and hands
    // received offers to the GLib main loop through a channel; the answer is
    // produced on the main thread (where `webrtcbin` lives) and pushed back
    // into the outbound queue. This split exists because GStreamer objects are
    // thread-affine and therefore not `Send`.
    let (offer_tx, offer_rx) = std::sync::mpsc::channel::<String>();
    let (remote_ice_tx, remote_ice_rx) = std::sync::mpsc::channel::<(u32, String)>();

    let runtime = tokio::runtime::Builder::new_multi_thread()
        .enable_all()
        .build()?;
    let (done_tx, done_rx) = std::sync::mpsc::channel::<()>();
    runtime.spawn(async move {
        if let Err(err) = signalling_loop(url, ticket, outbound_rx, offer_tx, remote_ice_tx).await {
            eprintln!("signalling ended: {err}");
        }
        let _ = done_tx.send(());
    });

    // ── Answer pump on the GLib main loop ──
    // Polls for offers and answers them. A timeout source is enough because an
    // offer arrives once per session, and again only when the server rebuilds
    // its pipeline (a resize).
    {
        let shared = shared.clone();
        let outbound_tx = outbound_tx.clone();
        glib::timeout_add_local(std::time::Duration::from_millis(50), move || {
            while let Ok(offer_sdp) = offer_rx.try_recv() {
                println!("<- offer received ({} bytes)", offer_sdp.len());
                match answer_offer(&shared, &offer_sdp) {
                    Ok(answer_sdp) => {
                        let answer = ClientMessage::Answer { sdp: answer_sdp };
                        println!("-> answer ({} bytes)", answer.to_json().len());
                        let _ = outbound_tx.send(answer.to_json());
                        *shared.answered.lock().unwrap() = true;
                    }
                    Err(err) => eprintln!("failed to answer the offer: {err}"),
                }
            }
            glib::ControlFlow::Continue
        });
    }

    // ── Remote ICE, applied on the GLib main loop ──
    // Same reason as above: candidates must be added from the thread that owns
    // the element.
    {
        let shared = shared.clone();
        glib::timeout_add_local(std::time::Duration::from_millis(50), move || {
            while let Ok((mline_index, candidate)) = remote_ice_rx.try_recv() {
                if !*shared.answered.lock().unwrap() {
                    continue;
                }
                if let Some(webrtc) = shared.webrtc.lock().unwrap().clone() {
                    webrtc.emit_by_name::<()>("add-ice-candidate", &[&mline_index, &candidate]);
                }
            }
            glib::ControlFlow::Continue
        });
    }

    let main_loop_clone = main_loop.clone();
    std::thread::spawn(move || {
        let _ = done_rx.recv();
        println!("signalling finished — shutting down");
        main_loop_clone.quit();
    });

    main_loop.run();

    let _ = pipeline.set_state(gst::State::Null);
    runtime.shutdown_timeout(std::time::Duration::from_secs(2));
    Ok(())
}

/// Build `depay → parse → decode → convert → sink` for a negotiated pad.
fn attach_video_branch(
    pipeline: &gst::Pipeline,
    pad: &gst::Pad,
    render: bool,
) -> Result<(), BoxError> {
    let caps = pad.current_caps().ok_or("pad has no caps")?;
    let encoding = caps
        .structure(0)
        .and_then(|s| s.get::<String>("encoding-name").ok())
        .unwrap_or_default();
    println!("negotiated encoding: {encoding}");

    // Selected from the negotiated encoding, so the same branch serves H.265
    // once the server starts sending it. Today it always sends H.264 — see
    // lightrays/src/encoder.rs::select_encoder.
    let (depay_name, parse_name, hw_decoder, sw_decoder) = match encoding.as_str() {
        "H264" => ("rtph264depay", "h264parse", "vah264dec", "avdec_h264"),
        "H265" => ("rtph265depay", "h265parse", "vah265dec", "avdec_h265"),
        other => return Err(format!("unsupported encoding {other}").into()),
    };

    let depay = gst::ElementFactory::make(depay_name).build()?;
    let parse = gst::ElementFactory::make(parse_name).build()?;
    let queue = gst::ElementFactory::make("queue").build()?;

    // Hardware first, software fallback. Both are verified present by the
    // environment check in spike-01-gstreamer.md.
    let (decoder, used) = match gst::ElementFactory::make(hw_decoder).build() {
        Ok(el) => (el, hw_decoder),
        Err(_) => (
            gst::ElementFactory::make(sw_decoder)
                .build()
                .map_err(|_| format!("neither {hw_decoder} nor {sw_decoder} is available"))?,
            sw_decoder,
        ),
    };
    println!("decoder: {used}");

    let convert = gst::ElementFactory::make("videoconvert").build()?;
    let sink = if render {
        gst::ElementFactory::make("glimagesink")
            .property("sync", false)
            .build()?
    } else {
        gst::ElementFactory::make("fakesink")
            .property("sync", false)
            .build()?
    };

    pipeline.add_many([&depay, &parse, &queue, &decoder, &convert, &sink])?;
    gst::Element::link_many([&depay, &parse, &queue, &decoder, &convert, &sink])?;

    let depay_sink = depay.static_pad("sink").ok_or("depay has no sink pad")?;
    pad.link(&depay_sink)?;

    for element in [&depay, &parse, &queue, &decoder, &convert, &sink] {
        element.sync_state_with_parent()?;
    }

    // Frame counting proves data actually arrived in a headless run.
    let frames = Arc::new(std::sync::atomic::AtomicU64::new(0));
    let frames_probe = frames.clone();
    let sink_pad = sink.static_pad("sink").ok_or("sink has no pad")?;
    sink_pad.add_probe(gst::PadProbeType::BUFFER, move |_pad, _info| {
        let n = frames_probe.fetch_add(1, std::sync::atomic::Ordering::Relaxed) + 1;
        if n == 1 {
            println!("FIRST FRAME DECODED");
        } else if n % 60 == 0 {
            println!("frames decoded: {n}");
        }
        gst::PadProbeReturn::Ok
    });

    Ok(())
}

/// Drive the socket: forward our outbound messages and hand incoming offers and
/// ICE candidates to the GLib main loop.
///
/// This function deliberately knows nothing about GStreamer: it moves strings
/// and tuples only, so its future stays `Send`.
async fn signalling_loop(
    url: String,
    ticket: String,
    mut outbound: tokio::sync::mpsc::UnboundedReceiver<String>,
    offers: std::sync::mpsc::Sender<String>,
    remote_ice: std::sync::mpsc::Sender<(u32, String)>,
) -> Result<(), BoxError> {
    let mut request = url.clone().into_client_request()?;
    {
        let headers = request.headers_mut();
        // lightrays/src/auth.rs accepts the ticket either as the second
        // Sec-WebSocket-Protocol value or as a Bearer token; send both so the
        // spike survives either server configuration.
        headers.insert(
            "sec-websocket-protocol",
            HeaderValue::from_str(&format!("lightrays, {ticket}"))?,
        );
        headers.insert(
            "authorization",
            HeaderValue::from_str(&format!("Bearer {ticket}"))?,
        );
    }

    // ── Why the socket is dialled by hand ──
    //
    // Two environment quirks make the plain `connect_async` path unusable here,
    // and both are properties of this deployment rather than of the protocol:
    //
    // 1. DNS resolves `streamarr.luebke.internal` to a Tailscale address
    //    (100.64.0.2) that does not answer, while the real endpoint is
    //    10.10.60.30 — the same reason curl needs `--resolve`. So the target
    //    address is overridable, defaulting to whatever DNS returns.
    // 2. nginx offers `h2` and prefers it when the client offers both, and a
    //    WebSocket upgrade cannot happen over h2. ALPN is therefore pinned to
    //    http/1.1 (verified with `openssl s_client`: `-alpn h2,http/1.1`
    //    negotiates h2, `-alpn http/1.1` negotiates http/1.1).
    let tls = native_tls::TlsConnector::builder()
        .request_alpns(&["http/1.1"])
        .build()?;

    let host = request.uri().host().unwrap_or_default().to_string();
    let port = request.uri().port_u16().unwrap_or(443);
    // `--resolve host:port:ip` mirroring curl, so a broken split-DNS answer can
    // be bypassed without editing the shared /etc/hosts.
    let target = resolve_override(&host, port).unwrap_or(format!("{host}:{port}"));

    println!("dialling {target} (host: {host})");
    let tcp = tokio::net::TcpStream::connect(&target).await?;
    tcp.set_nodelay(true)?;
    let tls_stream = tokio_native_tls::TlsConnector::from(tls)
        .connect(&host, tcp)
        .await?;
    let (mut ws, response) = tokio_tungstenite::client_async(request, tls_stream).await?;
    println!("websocket connected: HTTP {}", response.status());

    loop {
        tokio::select! {
            Some(out) = outbound.recv() => {
                if out.contains("\"ice\"") {
                    println!("-> local {}", truncate(&out));
                }
                ws.send(Message::Text(out)).await?;
            }
            incoming = ws.next() => {
                let Some(message) = incoming else { break };
                match message? {
                    Message::Text(text) => handle_server_message(&text, &offers, &remote_ice)?,
                    Message::Close(frame) => {
                        println!("server closed the connection: {frame:?}");
                        break;
                    }
                    _ => {}
                }
            }
        }
    }
    Ok(())
}

/// Parse a server message and route it to the right GLib-side channel.
fn handle_server_message(
    text: &str,
    offers: &std::sync::mpsc::Sender<String>,
    remote_ice: &std::sync::mpsc::Sender<(u32, String)>,
) -> Result<(), BoxError> {
    let Some(message) = ServerMessage::parse(text) else {
        println!("<- (unhandled) {}", truncate(text));
        return Ok(());
    };

    match message {
        ServerMessage::Offer { sdp } => {
            let _ = offers.send(sdp);
        }
        ServerMessage::Ice {
            candidate,
            mline_index,
        } => {
            println!(
                "<- remote ice (mline={mline_index}) {}",
                truncate(&candidate)
            );
            let _ = remote_ice.send((mline_index, candidate));
        }
        ServerMessage::ContainerDied { exit_code } => {
            println!("<- container died (exit {exit_code:?}) — session over");
        }
        ServerMessage::PipelineError => println!("<- pipeline error"),
        ServerMessage::Error { message } => println!("<- server error: {message}"),
    }
    Ok(())
}

/// Turn the server's offer into an answer and install it locally.
///
/// `create-answer` is a `webrtcbin` signal, not a method: it is emitted with a
/// `gst::Promise` and the reply arrives as a `gst::Structure` carrying an
/// `answer` field. This mirrors how `lightrays/src/webrtc.rs` obtains the offer
/// on the server side.
fn answer_offer(shared: &Arc<Shared>, offer_sdp: &str) -> Result<String, BoxError> {
    let webrtc = shared
        .webrtc
        .lock()
        .unwrap()
        .clone()
        .ok_or("webrtcbin is gone")?;

    let sdp = gstreamer_webrtc::gst_sdp::SDPMessage::parse_buffer(offer_sdp.as_bytes())
        .map_err(|_| "could not parse the offer SDP")?;
    let offer = gst_webrtc::WebRTCSessionDescription::new(gst_webrtc::WebRTCSDPType::Offer, sdp);

    // set-remote-description is synchronous enough for our purpose; the promise
    // is interrupted immediately, as lightrays does for the answer direction.
    let promise = gst::Promise::new();
    webrtc.emit_by_name::<()>("set-remote-description", &[&offer, &promise]);
    promise.interrupt();

    // create-answer delivers its result through a change function.
    let (tx, rx) = std::sync::mpsc::channel::<Result<String, String>>();
    let webrtc_for_answer = webrtc.clone();
    let promise = gst::Promise::with_change_func(move |reply| {
        let result = match reply {
            Ok(Some(reply)) => match reply.get::<gst_webrtc::WebRTCSessionDescription>("answer") {
                Ok(answer) => {
                    let local = gst::Promise::new();
                    webrtc_for_answer
                        .emit_by_name::<()>("set-local-description", &[&answer, &local]);
                    local.interrupt();
                    answer
                        .sdp()
                        .as_text()
                        .map_err(|_| "answer SDP has no text".to_string())
                }
                Err(_) => Err("create-answer reply had no answer field".to_string()),
            },
            Ok(None) => Err("create-answer promise returned an empty reply".to_string()),
            Err(err) => Err(format!("create-answer promise error: {err:?}")),
        };
        let _ = tx.send(result);
    });
    webrtc.emit_by_name::<()>("create-answer", &[&None::<gst::Structure>, &promise]);

    match rx.recv_timeout(std::time::Duration::from_secs(10)) {
        Ok(Ok(sdp)) => Ok(sdp),
        Ok(Err(err)) => Err(err.into()),
        Err(_) => Err("timed out waiting for create-answer".into()),
    }
}

/// Honour `SPIKE_RESOLVE=host:port:ip`, mirroring curl's `--resolve`.
///
/// Exists because `streamarr.luebke.internal` resolves to a Tailscale address
/// that does not answer on this network, while the real endpoint is reachable
/// on the VLAN address. Overriding it here keeps the workaround out of the
/// shared /etc/hosts.
fn resolve_override(host: &str, port: u16) -> Option<String> {
    let spec = std::env::var("SPIKE_RESOLVE").ok()?;
    let mut parts = spec.split(':');
    let (h, p, ip) = (parts.next()?, parts.next()?, parts.next()?);
    if h == host && p.parse::<u16>().ok() == Some(port) {
        Some(format!("{ip}:{port}"))
    } else {
        None
    }
}

fn truncate(value: &str) -> String {
    let mut out: String = value.chars().take(100).collect();
    if value.chars().count() > 100 {
        out.push('…');
    }
    out
}
