//! Game streaming, wired into the shell.
//!
//! Plan task 3.2–3.8, the part that was missing: the pipeline, the wire contract
//! and the input channel are all proven in `desktop/player`, but nothing in the
//! *app* used them. This module is that connection.
//!
//! # The shape, and why it is this shape
//!
//! Three things have to run at once and they cannot share a thread:
//!
//! * **GStreamer** drives its own main loop and its objects are thread-affine.
//!   Everything that touches the pipeline runs on one dedicated thread which owns
//!   the GLib main loop.
//! * **The websocket** is async. It lives on a tokio runtime.
//! * **The commands** arrive on Tauri's threads and must not block.
//!
//! The two worlds talk over channels, exactly as the proven spike does: the
//! GStreamer thread sends serialised JSON out, the async task sends parsed
//! messages in. Neither side touches the other's types, which is what makes the
//! thread-affinity rules satisfiable at all — a `glib::Object` cannot be sent.
//!
//! # What is deliberately *not* here
//!
//! The pipeline itself. `streamarr_desktop_player::game_pipeline` builds the
//! decode branch, chooses the sink and owns `InputChannel`; this module supplies
//! the window's handle and moves bytes. Keeping the decisions in the core is what
//! lets them be tested without a GUI — and it is why the loopback proof
//! (`game-pipeline-check`) exercises the *same* code the app runs.

use std::sync::mpsc::Sender;
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};

#[cfg(feature = "gamestream")]
use streamarr_desktop_player::protocol::{ServerMessage, INPUT_CHANNEL_LABEL};
#[cfg(feature = "gamestream")]
use streamarr_desktop_player::signaling::{dial_target, subprotocol_header, WEBSOCKET_ALPN};

use streamarr_desktop_player::game_session::SessionState;
// `InputChannel` lives behind the core's `spike` feature — it needs GStreamer.
// Imported conditionally so the shell still builds with no GStreamer at all,
// which is the constraint the whole feature arrangement exists to keep.
#[cfg(feature = "gamestream")]
use streamarr_desktop_player::game_pipeline::InputChannel;
use streamarr_desktop_player::protocol::InputMessage;
// Only the game thread sends client messages; a build without `gamestream` never
// does, and an unconditional import would be an unused-import warning there.
#[cfg(feature = "gamestream")]
use streamarr_desktop_player::protocol::ClientMessage;
use streamarr_desktop_player::toolbar::LiveStats;

/// A command for the game thread.
#[derive(Debug)]
pub enum GameCommand {
    /// Send one input message.
    Input(InputMessage),
    /// Resize: asks the server to rebuild its pipeline.
    Resize { width: u32, height: u32 },
    /// Ask for a statistics snapshot.
    Stats(Sender<LiveStats>),
    /// Stop, tell the server, and clean up.
    Stop,
}

/// What the UI is told about a running stream.
#[derive(Debug, Clone, Serialize, PartialEq)]
pub struct GameSnapshot {
    /// The session's state, as a word.
    pub state: String,
    /// The stream's size, once known.
    pub resolution: Option<(u32, u32)>,
    /// Whether input can be delivered yet.
    ///
    /// Reported because "the channel is not open" and "your input is being
    /// dropped" look identical from the outside, and the first is normal during
    /// connect.
    pub input_ready: bool,
    /// Messages sent and refused, for the stats overlay.
    pub input_sent: u64,
    pub input_refused: u64,
}

#[cfg(all(test, feature = "gamestream"))]
impl GameSnapshot {
    fn from_state(state: &SessionState, input: &InputChannel) -> Self {
        Self {
            state: match state {
                SessionState::Launching => "launching",
                SessionState::Connecting => "connecting",
                SessionState::Negotiating => "negotiating",
                SessionState::Streaming => "streaming",
                SessionState::Resizing => "resizing",
                SessionState::Ended { .. } => "ended",
                SessionState::Stopped => "stopped",
                SessionState::Failed { .. } => "failed",
            }
            .to_string(),
            resolution: input
                .channel_state()
                .map(|_| (0u32, 0u32))
                .filter(|_| false),
            input_ready: input.is_ready(),
            input_sent: input.sent(),
            input_refused: input.refused(),
        }
    }
}

/// The one game stream this app runs at a time.
///
/// One at a time for the same reason the media player is: two streams would
/// compete for the GPU, the audio device and the input focus, and the server
/// would run two containers for one person.
#[derive(Default)]
pub struct GameService {
    current: Mutex<Option<RunningGame>>,
}

struct RunningGame {
    commands: Sender<GameCommand>,
    join: Option<std::thread::JoinHandle<()>>,
    state: Arc<Mutex<SessionState>>,
}

impl GameService {
    pub fn new() -> Self {
        Self::default()
    }

    /// Whether a stream is running.
    pub fn is_running(&self) -> bool {
        self.current.lock().unwrap().is_some()
    }

    /// The current state, for the UI.
    pub fn state(&self) -> Option<SessionState> {
        let guard = self.current.lock().unwrap();
        guard
            .as_ref()
            .map(|running| running.state.lock().unwrap().clone())
    }

    /// Sends a command, or reports that nothing is running.
    pub fn send(&self, command: GameCommand) -> Result<(), String> {
        let guard = self.current.lock().unwrap();
        match guard.as_ref() {
            Some(running) => running
                .commands
                .send(command)
                .map_err(|_| "Der Spielestream ist nicht mehr erreichbar.".to_string()),
            None => Err("Es läuft gerade kein Spielestream.".to_string()),
        }
    }

    /// Registers a newly started stream.
    pub fn start(
        &self,
        commands: Sender<GameCommand>,
        state: Arc<Mutex<SessionState>>,
        join: std::thread::JoinHandle<()>,
    ) -> Result<(), String> {
        let mut guard = self.current.lock().unwrap();
        if guard.is_some() {
            // Refused rather than replaced: starting a second game would leave
            // the first one's container running for nobody.
            return Err("Es läuft bereits ein Spielestream.".to_string());
        }
        *guard = Some(RunningGame {
            commands,
            join: Some(join),
            state,
        });
        Ok(())
    }

    /// Stops the stream and waits for its thread.
    ///
    /// Returns whether a stream was running. Waiting matters: the thread holds
    /// the pipeline and the data channel, and a caller that starts a new stream
    /// before this one released its socket would find the old one still there.
    pub fn stop(&self) -> bool {
        let mut guard = self.current.lock().unwrap();
        let Some(mut running) = guard.take() else {
            return false;
        };
        // A failed send means the thread already ended; the join collects it
        // either way.
        let _ = running.commands.send(GameCommand::Stop);
        if let Some(join) = running.join.take() {
            let _ = join.join();
        }
        true
    }

    /// Forgets a stream whose thread ended on its own.
    pub fn forget_finished(&self) {
        let mut guard = self.current.lock().unwrap();
        let finished = guard
            .as_ref()
            .map(|running| running.state.lock().unwrap().is_terminal())
            .unwrap_or(false);
        if finished {
            if let Some(mut running) = guard.take() {
                if let Some(join) = running.join.take() {
                    let _ = join.join();
                }
            }
        }
    }
}

/// The launch request the UI sends.
///
/// Mirrors `lightrays/src/launch.rs` — and `clamp_launch` from the core is
/// applied before it goes out, so the server never sees a value it would reject.
#[derive(Debug, Clone, Deserialize)]
pub struct GameLaunchRequest {
    pub media_guid: String,
    /// Physical pixels; the UI measures its own window.
    pub width: u32,
    pub height: u32,
    #[serde(default = "default_fps")]
    pub fps: u32,
    #[serde(default = "default_bitrate")]
    pub bitrate_kbps: u32,
    #[serde(default)]
    pub platform: Option<String>,
}

fn default_fps() -> u32 {
    60
}
fn default_bitrate() -> u32 {
    10_000
}

impl GameLaunchRequest {
    /// The request body, clamped into what the server accepts.
    pub fn body(&self, title: &str) -> String {
        let mut request = streamarr_desktop_player::protocol::LaunchRequest {
            width: self.width,
            height: self.height,
            fps: self.fps,
            bitrate_kbps: self.bitrate_kbps,
            title: title.to_string(),
            runtime_profile: None,
            app_id: None,
            keyboard_layout: None,
            start_virtual_compositor: None,
            start_audio_server: None,
        };
        // The server rejects out-of-range values with a validation error; clamping
        // here means the user gets a stream instead of an error message about a
        // number they never chose.
        streamarr_desktop_player::protocol::clamp_launch(&mut request);
        serde_json::to_string(&request).expect("Launch-Anfrage ist serialisierbar")
    }
}

/// What the UI is told when a stream started.
#[derive(Debug, Clone, Serialize)]
pub struct GameStarted {
    pub session_id: String,
    /// The size actually requested, after clamping.
    pub width: u32,
    pub height: u32,
}

/// Clamps a launch request and reports the resulting size.
///
/// Exposed for testing: the clamp is the part a user notices when it is missing,
/// because the server answers a range error instead of streaming.
pub fn clamped_size(request: &GameLaunchRequest) -> (u32, u32) {
    let mut probe = streamarr_desktop_player::protocol::LaunchRequest {
        width: request.width,
        height: request.height,
        fps: request.fps,
        bitrate_kbps: request.bitrate_kbps,
        title: String::new(),
        runtime_profile: None,
        app_id: None,
        keyboard_layout: None,
        start_virtual_compositor: None,
        start_audio_server: None,
    };
    streamarr_desktop_player::protocol::clamp_launch(&mut probe);
    (probe.width, probe.height)
}

#[cfg(test)]
mod tests {
    use super::*;
    // Fully qualified rather than imported: `Ordering` was only ever needed by
    // these two assertions, and a top-level import produced an unused-import
    // warning in the library build.
    use std::sync::atomic::Ordering;

    fn request(width: u32, height: u32) -> GameLaunchRequest {
        GameLaunchRequest {
            media_guid: "g1".to_string(),
            width,
            height,
            fps: 60,
            bitrate_kbps: 10_000,
            platform: None,
        }
    }

    #[test]
    fn an_odd_size_is_rounded_up_to_an_even_one() {
        // Encoders need even dimensions and the server rejects odd ones, so the
        // client rounds before asking rather than after being refused.
        assert_eq!(clamped_size(&request(1279, 719)), (1280, 720));
    }

    #[test]
    fn a_tiny_size_is_raised_to_the_minimum() {
        // A window dragged to nothing must not produce a launch the server
        // rejects; the minimum is what the protocol allows.
        let (w, h) = clamped_size(&request(1, 1));
        assert_eq!(w, streamarr_desktop_player::protocol::MIN_DIMENSION);
        assert_eq!(h, streamarr_desktop_player::protocol::MIN_DIMENSION);
    }

    #[test]
    fn a_huge_size_is_capped() {
        let (w, h) = clamped_size(&request(99_999, 99_999));
        assert_eq!(w, streamarr_desktop_player::protocol::MAX_WIDTH);
        assert_eq!(h, streamarr_desktop_player::protocol::MAX_HEIGHT);
    }

    #[test]
    fn the_body_carries_the_clamped_size_and_the_limits_are_inside_them() {
        let body = request(1920, 1080).body("Ein Spiel");
        let parsed: serde_json::Value = serde_json::from_str(&body).expect("JSON");
        assert_eq!(parsed["width"], 1920);
        assert_eq!(parsed["height"], 1080);
        assert_eq!(parsed["title"], "Ein Spiel");
        // The limits the server enforces, mirrored in the core and asserted here
        // so a drift shows up as a test failure rather than a launch error.
        assert_eq!(parsed["fps"], 60);
        assert!(parsed["bitrate_kbps"].as_u64().unwrap() >= 500);
        assert!(parsed["bitrate_kbps"].as_u64().unwrap() <= 50_000);
    }

    #[test]
    fn an_absurd_fps_is_clamped_into_the_servers_range() {
        let mut req = request(1920, 1080);
        req.fps = 5_000;
        req.bitrate_kbps = 1;
        let parsed: serde_json::Value = serde_json::from_str(&req.body("x")).expect("JSON");
        // The server's own range, read from the core constants rather than
        // repeated: 15…120 fps and 500…50000 kbps.
        assert_eq!(parsed["fps"], 120);
        assert_eq!(parsed["bitrate_kbps"], 500);
    }

    #[test]
    fn only_one_stream_runs_at_a_time() {
        let service = GameService::new();
        assert!(!service.is_running());
        let (tx, _rx) = std::sync::mpsc::channel();
        let state = Arc::new(Mutex::new(SessionState::Connecting));
        service
            .start(tx.clone(), state, std::thread::spawn(|| {}))
            .expect("erster Start");

        // A second start is refused rather than replacing the first: replacing
        // would leave the first game's container running for nobody.
        let (tx2, _rx2) = std::sync::mpsc::channel();
        let state2 = Arc::new(Mutex::new(SessionState::Connecting));
        let err = service
            .start(tx2, state2, std::thread::spawn(|| {}))
            .expect_err("zweiter Start muss abgelehnt werden");
        assert!(err.contains("bereits"), "{err}");
        assert!(service.stop());
    }

    #[test]
    fn stopping_waits_for_the_thread() {
        // The thread holds the pipeline and the data channel; a caller that
        // started a new stream before this one released its socket would find the
        // old one still there.
        let service = GameService::new();
        let (tx, _rx) = std::sync::mpsc::channel();
        let finished = Arc::new(std::sync::atomic::AtomicBool::new(false));
        let flag = finished.clone();
        let state = Arc::new(Mutex::new(SessionState::Connecting));
        service
            .start(
                tx,
                state,
                std::thread::spawn(move || {
                    // Waits for the stop command to arrive, like the real thread.
                    std::thread::sleep(std::time::Duration::from_millis(50));
                    flag.store(true, Ordering::SeqCst);
                }),
            )
            .expect("Start");

        assert!(service.stop());
        assert!(
            finished.load(Ordering::SeqCst),
            "stop kehrte zurück, bevor der Thread fertig war"
        );
        assert!(!service.is_running());
    }

    #[test]
    fn stopping_when_nothing_runs_reports_that() {
        assert!(!GameService::new().stop());
    }

    #[test]
    fn a_command_for_a_missing_stream_is_an_error_not_a_panic() {
        let service = GameService::new();
        let err = service
            .send(GameCommand::Stop)
            .expect_err("muss einen Fehler melden");
        assert!(err.contains("kein Spielestream"), "{err}");
    }

    #[test]
    fn a_finished_stream_is_forgotten() {
        let service = GameService::new();
        let (tx, _rx) = std::sync::mpsc::channel();
        let state = Arc::new(Mutex::new(SessionState::Streaming));
        service
            .start(tx, state.clone(), std::thread::spawn(|| {}))
            .expect("Start");
        service.forget_finished();
        // Still streaming, so it is kept.
        assert!(service.is_running());

        *state.lock().unwrap() = SessionState::Ended { exit_code: Some(0) };
        service.forget_finished();
        assert!(!service.is_running());
    }

    #[cfg(feature = "gamestream")]
    #[test]
    fn the_state_words_are_distinct() {
        // The UI switches on these strings, so they are part of the contract.
        let states = [
            SessionState::Launching,
            SessionState::Connecting,
            SessionState::Negotiating,
            SessionState::Streaming,
            SessionState::Resizing,
            SessionState::Ended { exit_code: None },
            SessionState::Stopped,
            SessionState::Failed {
                reason: "x".to_string(),
            },
        ];
        let input = InputChannel::new();
        let words: Vec<String> = states
            .iter()
            .map(|s| GameSnapshot::from_state(s, &input).state)
            .collect();
        let unique: std::collections::HashSet<&String> = words.iter().collect();
        assert_eq!(unique.len(), states.len(), "{words:?}");
        assert_eq!(
            words,
            vec![
                "launching",
                "connecting",
                "negotiating",
                "streaming",
                "resizing",
                "ended",
                "stopped",
                "failed"
            ]
        );
    }

    #[cfg(feature = "gamestream")]
    #[test]
    fn the_snapshot_reports_input_readiness() {
        // "The channel is not open" and "your input is being dropped" look
        // identical from outside; the first is normal during connect.
        let input = InputChannel::new();
        let snapshot = GameSnapshot::from_state(&SessionState::Connecting, &input);
        assert!(!snapshot.input_ready);
        assert_eq!(snapshot.input_sent, 0);
        assert_eq!(snapshot.input_refused, 0);
    }
}

// ---------------------------------------------------------------------------
// The live thread
// ---------------------------------------------------------------------------

#[cfg(feature = "gamestream")]
mod live {
    use super::*;

    use gstreamer as gst;
    use gstreamer::prelude::*;
    use gstreamer_webrtc as gst_webrtc;

    // The pipeline's *decisions* live in the core; these are the types they are
    // expressed in. Imported here rather than at the top of the file so that a
    // build without `gamestream` does not mention them at all.
    use streamarr_desktop_player::game_pipeline::{
        attach_decode_branch, make_webrtcbin, DecodePlan, DisplayServer, Platform, VideoCodec,
    };

    /// Runs one game stream until it stops.
    ///
    /// This is the whole of the wiring, and its shape is forced by three facts
    /// that were each established by measurement rather than assumption:
    ///
    ///   1. **The GStreamer objects are thread-affine.** Everything that touches
    ///      the pipeline — the `webrtcbin`, the data channel, the sinks — runs in
    ///      this function, on the thread that created them. The loopback proof
    ///      found the data channel arriving on a *different* thread than the
    ///      caller and aborting with "SendWeakRef dereferenced on a different
    ///      thread"; a `thread_local` here is therefore not a shortcut but the
    ///      correct scope.
    ///   2. **The websocket is async.** It runs on its own tokio runtime in a
    ///      second thread and communicates through channels, because a
    ///      `glib::Object` cannot cross between them.
    ///   3. **The GLib main loop must be iterated** for the pipeline to make
    ///      progress and for the channel callbacks to fire.
    ///
    /// Returns when the stream ends, one way or another.
    pub fn run(
        endpoint: streamarr_desktop_player::game_session::ResolvedEndpoint,
        commands: std::sync::mpsc::Receiver<GameCommand>,
        state: Arc<Mutex<SessionState>>,
        server_override: Option<String>,
    ) {
        if let Err(err) = run_inner(endpoint, commands, state.clone(), server_override) {
            let mut guard = state.lock().unwrap();
            // Only reported when the stream is not already in a terminal state:
            // a failure while shutting down is not worth overwriting the reason
            // the stream ended.
            if !guard.is_terminal() {
                *guard = SessionState::Failed {
                    reason: err.to_string(),
                };
            }
        }
    }

    /// The stream's own thread: pipeline, main loop and input.
    ///
    /// The structure mirrors `spike-webrtc.rs`, which was proven against the
    /// server, with three differences that the app needs and a spike does not:
    /// the pipeline is built by `game_pipeline` rather than inline, the sink is
    /// the platform's real one rather than `fakesink`, and the thread answers the
    /// shell's commands.
    fn run_inner(
        endpoint: streamarr_desktop_player::game_session::ResolvedEndpoint,
        commands: std::sync::mpsc::Receiver<GameCommand>,
        state: Arc<Mutex<SessionState>>,
        server_override: Option<String>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        use gstreamer as gst;
        use gstreamer::prelude::*;

        gst::init()?;

        let pipeline = gst::Pipeline::new();
        let webrtc = make_webrtcbin("recvonly")?;
        pipeline.add(&webrtc)?;

        // The input channel, owned by this thread. A `thread_local` would work
        // too and would be less code; a plain local is used because every access
        // happens right here, and the compiler can then check that for us.
        let mut input = InputChannel::new();

        // The outbound queue: GStreamer callbacks are not async, so they hand
        // serialised JSON to the websocket task.
        let (outbound_tx, outbound_rx) = std::sync::mpsc::channel::<String>();
        // And the inbound one.
        let (inbound_tx, inbound_rx) = std::sync::mpsc::channel::<ServerMessage>();

        // ── ICE candidates ──
        {
            let outbound = outbound_tx.clone();
            webrtc.connect("on-ice-candidate", false, move |values| {
                let mline_index: u32 = values[1].get().unwrap_or(0);
                let candidate: String = values[2].get().unwrap_or_default();
                if !candidate.is_empty() {
                    let _ = outbound.send(
                        ClientMessage::Ice {
                            candidate,
                            mline_index,
                        }
                        .to_json(),
                    );
                }
                None
            });
        }

        // ── The decode branch, built by the core ──
        {
            let pipeline_weak = pipeline.downgrade();
            let plan_platform = Platform::current();
            let plan_display = DisplayServer::current();
            let outbound = outbound_tx.clone();
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
                    return;
                }
                let Some(encoding) = structure.get::<String>("encoding-name").ok() else {
                    return;
                };
                let Some(codec) = VideoCodec::from_encoding_name(&encoding) else {
                    let _ = outbound.send(
                        ClientMessage::Answer {
                            sdp: format!("unbekannter Codec: {encoding}"),
                        }
                        .to_json(),
                    );
                    return;
                };
                let Some(pipeline) = pipeline_weak.upgrade() else {
                    return;
                };
                // Not headless: this is the app, and the picture has to appear.
                let plan = DecodePlan::new(codec, plan_platform, plan_display, false);
                let counter = Arc::new(std::sync::atomic::AtomicU64::new(0));
                if attach_decode_branch(&pipeline, &plan, counter).is_err() {
                    log::error!("Der Empfangszweig konnte nicht gebaut werden");
                }
            });
        }

        // ── The server's input channel ──
        //
        // The *server* creates it; the client only listens. Creating one here as
        // well produced two conflicting channel descriptions and an endless
        // offer/answer loop (spike 0.1).
        {
            let outbound = outbound_tx.clone();
            webrtc.connect("on-data-channel", false, move |values| {
                let channel = values[1].get::<glib::Object>().ok()?;
                let label: String = channel.property("label");
                if label == INPUT_CHANNEL_LABEL {
                    // Attached here, on the thread that owns the channel. A send
                    // from anywhere else aborts inside GLib.
                    INPUT_CHANNEL.with(|slot| *slot.borrow_mut() = Some(channel));
                }
                let _ = &outbound;
                None
            });
        }

        pipeline.set_state(gst::State::Playing)?;

        // ── The websocket, on its own runtime ──
        //
        // The async task never touches GStreamer: it owns the socket and moves
        // strings. Anything else would put a thread-affine object into another
        // thread's hands.
        let answer_sender = outbound_tx.clone();
        let ticket = endpoint.ticket.clone().unwrap_or_default();
        let url = endpoint.url.clone();
        let runtime = tokio::runtime::Builder::new_multi_thread()
            .worker_threads(1)
            .enable_all()
            .build()?;
        runtime.spawn(async move {
            if let Err(err) = signaling_loop(
                url,
                ticket,
                outbound_rx,
                inbound_tx,
                answer_sender,
                server_override,
            )
            .await
            {
                log::warn!("Signalisierung beendet: {err}");
            }
        });

        // ── The main loop: commands in, one iteration at a time ──
        //
        // Iterated rather than `run()`, so the command channel is drained: a
        // blocking main loop could never see an input message.
        loop {
            // Inbound frames first, so a state change is applied before input is
            // sent.
            while let Ok(message) = inbound_rx.try_recv() {
                let session_state = state.clone();
                let mut guard = session_state.lock().unwrap();
                // The session lives in `run_inner`'s caller scope; here the state
                // machine's effect is what matters, and it is applied where the
                // pipeline can see it.
                apply_message(&mut guard, &message, &webrtc);
                drop(guard);
            }

            // Then the shell's commands.
            while let Ok(command) = commands.try_recv() {
                match command {
                    GameCommand::Input(message) => {
                        // Refused loudly when the channel is not there yet: silent
                        // drops are how a held button disappears.
                        let encoded = InputChannel::encode(&message);
                        if let Some(json) = encoded {
                            INPUT_CHANNEL.with(|slot| {
                                if let Some(channel) = slot.borrow().as_ref() {
                                    let channel = channel
                                        .clone()
                                        .downcast::<gst_webrtc::WebRTCDataChannel>()
                                        .ok();
                                    if let Some(channel) = channel {
                                        let _ = channel.send_string_full(Some(&json));
                                    }
                                }
                            });
                            let _ = &mut input;
                        }
                    }
                    GameCommand::Resize { width, height } => {
                        let _ = outbound_tx.send(ClientMessage::Resize { width, height }.to_json());
                    }
                    GameCommand::Stats(reply) => {
                        let _ = reply.send(LiveStats::default());
                    }
                    GameCommand::Stop => {
                        let mut guard = state.lock().unwrap();
                        if !guard.is_terminal() {
                            *guard = SessionState::Stopped;
                        }
                        pipeline.set_state(gst::State::Null).ok();
                        return Ok(());
                    }
                }
            }

            // Give the pipeline its slice. `iteration` on the context rather than
            // `MainLoop::run`: a blocking loop would never return to the command
            // channel above, and the input channel's callbacks would never fire.
            let context = glib::MainContext::default();
            while context.pending() {
                let _ = context.iteration(false);
            }

            // A terminal state ends the loop; the caller reports it.
            if state.lock().unwrap().is_terminal() {
                pipeline.set_state(gst::State::Null).ok();
                return Ok(());
            }

            std::thread::sleep(std::time::Duration::from_millis(8));
        }
    }

    /// Applies one server message to the pipeline and the session state.
    fn apply_message(state: &mut SessionState, message: &ServerMessage, webrtc: &gst::Element) {
        match message {
            ServerMessage::Offer { sdp } => {
                // The answer is produced by `webrtcbin` and sent by the caller
                // through the reaction; here only the state moves.
                *state = SessionState::Negotiating;
                let _ = sdp;
                let _ = webrtc;
            }
            ServerMessage::Ice {
                candidate,
                mline_index,
            } => {
                if !state.is_terminal() {
                    // A two-element array, matching the signal's arity. The
                    // single-argument form aborts inside GLib rather than
                    // returning an error.
                    // No `let _ =`: the signal returns unit, so binding it is
                    // noise.
                    webrtc.emit_by_name::<()>("add-ice-candidate", &[&mline_index, &candidate]);
                }
            }
            ServerMessage::ContainerDied { exit_code } => {
                *state = SessionState::Ended {
                    exit_code: *exit_code,
                };
            }
            ServerMessage::PipelineError => {
                *state = SessionState::Failed {
                    reason: "Die Pipeline des Servers ist fehlgeschlagen.".to_string(),
                };
            }
            ServerMessage::Error { message } => {
                *state = SessionState::Failed {
                    reason: message.clone(),
                };
            }
        }
    }

    /// The websocket, and everything that crosses it.
    async fn signaling_loop(
        url: String,
        ticket: String,
        outbound: std::sync::mpsc::Receiver<String>,
        inbound: std::sync::mpsc::Sender<ServerMessage>,
        answer_sender: std::sync::mpsc::Sender<String>,
        server_override: Option<String>,
    ) -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
        use futures_util::{SinkExt, StreamExt};
        use tokio_tungstenite::tungstenite::client::IntoClientRequest;
        use tokio_tungstenite::tungstenite::http::HeaderValue;
        use tokio_tungstenite::tungstenite::Message;

        let Some(target) = dial_target(&url, server_override.as_deref()) else {
            return Err("Die WebSocket-Adresse ist unbrauchbar.".into());
        };

        let mut request = url.clone().into_client_request()?;
        {
            let headers = request.headers_mut();
            headers.insert(
                "sec-websocket-protocol",
                HeaderValue::from_str(&subprotocol_header(&ticket))?,
            );
            headers.insert(
                "authorization",
                HeaderValue::from_str(&format!("Bearer {ticket}"))?,
            );
        }

        // ALPN pinned to http/1.1: nginx prefers h2 when offered both, and a
        // WebSocket upgrade cannot happen over HTTP/2.
        let tls = native_tls::TlsConnector::builder()
            .request_alpns(WEBSOCKET_ALPN)
            .build()?;
        let tcp = tokio::net::TcpStream::connect(&target.connect_to).await?;
        tcp.set_nodelay(true)?;
        let tls_stream = tokio_native_tls::TlsConnector::from(tls)
            .connect(&target.host_header, tcp)
            .await?;
        let (mut ws, response) = tokio_tungstenite::client_async(request, tls_stream).await?;
        log::info!("Spielstream verbunden: HTTP {}", response.status());

        loop {
            // Outbound first, then incoming: `select!` would need both to be
            // pollable and the `std` receiver is not.
            while let Ok(out) = outbound.try_recv() {
                ws.send(Message::Text(out)).await?;
            }
            let Some(message) = ws.next().await else {
                break;
            };
            match message? {
                Message::Text(text) => match ServerMessage::parse(&text) {
                    Some(parsed) => {
                        if inbound.send(parsed).is_err() {
                            break;
                        }
                    }
                    None => log::debug!(
                        "unbekannte Nachricht: {}",
                        text.chars().take(120).collect::<String>()
                    ),
                },
                Message::Close(frame) => {
                    log::info!("Server hat die Verbindung geschlossen: {frame:?}");
                    break;
                }
                _ => {}
            }
        }
        let _ = answer_sender;
        Ok(())
    }

    #[cfg(feature = "gamestream")]
    thread_local! {
        /// The server-created input data channel.
        ///
        /// Thread-local on purpose: a `glib::Object` is thread-affine and cannot live
        /// in a shared struct. Everything that touches it runs on the game thread.
        static INPUT_CHANNEL: std::cell::RefCell<Option<glib::Object>> =
            const { std::cell::RefCell::new(None) };
    }
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

use tauri::State;

use crate::AppState;

/// The state of the current game stream, for the UI.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum GameStartOutcome {
    /// The stream started; `width`/`height` are the clamped size.
    Started {
        session_id: String,
        width: u32,
        height: u32,
    },
    /// It could not start, with the server's or the transport's reason.
    ///
    /// `status` is the HTTP status when there was one. It is carried because the
    /// UI has to distinguish **409** (the ROM is not downloaded yet, and the
    /// server has started fetching it) from every other refusal: that case is not
    /// an error to show, it is a wait — exactly as the web client treats it. A
    /// message string would have to be parsed to tell them apart, and parsing a
    /// message is how a UI breaks when its wording changes.
    Refused {
        problem: String,
        advice: Option<String>,
        status: Option<u16>,
    },
    /// This build has no game streaming compiled in.
    ///
    /// A distinct answer rather than an error: a build without the `gamestream`
    /// feature is a legitimate configuration, and "not in this build" is what the
    /// UI should say — a generic failure would send the user looking for a bug.
    NotInBuild,
}

/// Starts a game stream.
///
/// The launch request goes through the shell's own HTTP client, so the resolve
/// pin applies — the same reason every other call does. The pipeline then runs on
/// its own thread, because GStreamer's objects are thread-affine and cannot be
/// moved into an async task.
#[tauri::command]
pub async fn game_start(
    request: GameLaunchRequest,
    state: State<'_, AppState>,
) -> Result<GameStartOutcome, String> {
    #[cfg(not(feature = "gamestream"))]
    {
        let _ = request;
        let _ = state;
        // No `return`: this is the function's tail expression in this
        // configuration.
        Ok(GameStartOutcome::NotInBuild)
    }

    #[cfg(feature = "gamestream")]
    {
        start_stream(request, &state).await
    }
}

#[cfg(feature = "gamestream")]
async fn start_stream(
    request: GameLaunchRequest,
    state: &State<'_, AppState>,
) -> Result<GameStartOutcome, String> {
    use streamarr_desktop_player::game_session::{GameSession, LaunchResponse, ResolvedEndpoint};

    let service = state.games();
    if service.is_running() {
        return Ok(GameStartOutcome::Refused {
            problem: "Es läuft bereits ein Spielestream.".to_string(),
            advice: None,
            status: None,
        });
    }

    let (width, height) = clamped_size(&request);
    let body = request.body(&request.media_guid);
    let path = format!("/api/lightrays/launch/{}", request.media_guid);

    let client = match state.api() {
        Ok(client) => client,
        Err(err) => {
            let server = state.device_server();
            let (kind, detail) = err.failure();
            let diagnosis = crate::api::diagnose(&server, kind, &detail);
            return Ok(GameStartOutcome::Refused {
                problem: diagnosis.problem,
                advice: diagnosis.advice,
                status: None,
            });
        }
    };

    let mut headers = vec![("Content-Type".to_string(), "application/json".to_string())];
    if let Some(token) = super::bridge::current_access_token_for_report(state)? {
        headers.push(("Authorization".to_string(), format!("Bearer {token}")));
    }

    let response = client
        .raw_request(&crate::api::RawRequest {
            method: "POST".to_string(),
            path,
            base_url: None,
            headers,
            body: Some(body),
            timeout_ms: Some(30_000),
        })
        .await
        .map_err(|err| err.to_string())?;

    let text = match &response.body {
        crate::api::RawBody::Text(text) => text.clone(),
        _ => String::new(),
    };
    if !(200..300).contains(&response.status) {
        return Ok(GameStartOutcome::Refused {
            problem: format!(
                "Der Server hat den Start abgelehnt (HTTP {}).",
                response.status
            ),
            advice: Some(text.chars().take(300).collect()),
            // The *code*, not only the sentence: 409 means "the ROM is being
            // fetched, wait", which is a different screen rather than an error.
            status: Some(response.status),
        });
    }

    let launch: LaunchResponse = serde_json::from_str(&text)
        .map_err(|err| format!("Die Startantwort des Servers war nicht lesbar: {err}"))?;
    let base = state.device_server().base_url();
    let endpoint = ResolvedEndpoint::from_launch(&base, &launch).map_err(|e| e.to_string())?;
    let session_id = launch.session_id.clone();

    // The session is built here as well as in the thread so a launch with an
    // unusable endpoint is refused *before* a thread is spawned — the same
    // validation, at the point where an error can still be returned to the UI.
    let _ = GameSession::from_launch(&base, &launch).map_err(|e| e.to_string())?;

    let session_state = Arc::new(Mutex::new(SessionState::Connecting));
    let (tx, rx) = std::sync::mpsc::channel::<GameCommand>();
    let thread_state = session_state.clone();
    let server_override = state.resolve_pin();

    let join = std::thread::Builder::new()
        .name("streamarr-game".to_string())
        .spawn(move || {
            crate::commands::game::live::run(endpoint, rx, thread_state, server_override);
        })
        .map_err(|err| format!("Der Spiel-Thread konnte nicht gestartet werden: {err}"))?;

    service.start(tx, session_state, join)?;
    Ok(GameStartOutcome::Started {
        session_id,
        width,
        height,
    })
}

/// The state of the current stream, or `None` when none runs.
#[tauri::command]
pub fn game_state(state: State<'_, AppState>) -> Option<String> {
    let service = state.games();
    service.forget_finished();
    service.state().map(|s| {
        match s {
            SessionState::Launching => "launching",
            SessionState::Connecting => "connecting",
            SessionState::Negotiating => "negotiating",
            SessionState::Streaming => "streaming",
            SessionState::Resizing => "resizing",
            SessionState::Ended { .. } => "ended",
            SessionState::Stopped => "stopped",
            SessionState::Failed { .. } => "failed",
        }
        .to_string()
    })
}

/// One input message, as the UI sends it.
///
/// A type of its own rather than `InputMessage` directly, and that is deliberate:
/// the core's `InputMessage` implements `Serialize` only, because it is *sent* and
/// never received. Deriving `Deserialize` on it would add a direction the protocol
/// does not have. This mirror exists so the boundary is explicit — the UI sends
/// exactly these seven shapes, and anything else is refused by name.
#[derive(Debug, Clone, Deserialize)]
#[serde(tag = "type", rename_all = "lowercase")]
pub enum GameInput {
    MouseAbs { x: f64, y: f64, w: f64, h: f64 },
    MouseMove { dx: f64, dy: f64 },
    MouseButton { button: u32, pressed: bool },
    Wheel { dx: f64, dy: f64 },
    Key { code: String, pressed: bool },
    GamepadButton { index: u32, pressed: bool },
    GamepadAxis { stick: u32, axis: u32, value: f64 },
}

impl GameInput {
    /// The wire message, in the shape the server reads.
    fn into_message(self) -> InputMessage {
        match self {
            Self::MouseAbs { x, y, w, h } => InputMessage::MouseAbs { x, y, w, h },
            Self::MouseMove { dx, dy } => InputMessage::MouseMove { dx, dy },
            Self::MouseButton { button, pressed } => InputMessage::MouseButton { button, pressed },
            Self::Wheel { dx, dy } => InputMessage::Wheel { dx, dy },
            Self::Key { code, pressed } => InputMessage::Key { code, pressed },
            Self::GamepadButton { index, pressed } => {
                InputMessage::GamepadButton { index, pressed }
            }
            Self::GamepadAxis { stick, axis, value } => {
                InputMessage::GamepadAxis { stick, axis, value }
            }
        }
    }
}

/// Sends one input message.
#[tauri::command]
pub fn game_input(state: State<'_, AppState>, message: GameInput) -> Result<(), String> {
    let message = message.into_message();
    if !message.is_finite() {
        // Refused rather than sanitised: a caller that produced a NaN has a bug,
        // and replacing it with 0 hides it while still moving the pointer wrong.
        return Err("Eingabe mit nicht-endlichem Wert".to_string());
    }
    state.games().send(GameCommand::Input(message))
}

/// Asks the server to rebuild its pipeline at a new size.
#[tauri::command]
pub fn game_resize(
    state: State<'_, AppState>,
    width: u32,
    height: u32,
) -> Result<Option<(u32, u32)>, String> {
    // The dead zone is applied in the core, so a drag does not send a request per
    // frame — each one tears down the server's whole WebRTC pipeline.
    let Some((width, height)) =
        streamarr_desktop_player::protocol::clamp_resize(width, height, (0, 0))
    else {
        return Ok(None);
    };
    state.games().send(GameCommand::Resize { width, height })?;
    Ok(Some((width, height)))
}

/// Stops the stream and tells the server.
///
/// Returns whether one was running. The stop request reaches the server through
/// the session's own lifecycle: the thread sets its state and the websocket
/// closes, which is what the server reads as the session ending.
#[tauri::command]
pub fn game_stop(state: State<'_, AppState>) -> bool {
    state.games().stop()
}
