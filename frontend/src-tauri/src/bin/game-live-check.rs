//! Drives the shell's **own** live game client against a real Lightrays session.
//!
//! The loopback pipeline check (`desktop/player`) proves that the decode chain the plan
//! names can be linked and decodes frames. What it cannot prove is interoperability: two
//! `webrtcbin` elements in one process agree with each other by construction, and the
//! closing report says so in exactly those words. This binary closes that gap by using
//! the same `live::run` the app uses — not a copy of it — against a session that was
//! really launched, so the offer, the answer, the ICE candidates, DTLS, SRTP and the
//! input data channel all come from the deployment.
//!
//! It expects a session that already exists. That is deliberate: a diagnostic should not
//! decide on its own to start a container, and reusing a running session keeps the proof
//! from costing a second one.
//!
//! Run from `frontend/src-tauri`:
//!
//! ```text
//! GAME_WS='wss://streamarr.example/api/lightrays-ws/<session>' \
//!   GAME_TICKET='<ws_ticket>' GAME_PIN=10.10.60.30 \
//!   GAME_CA=/path/to/ca.pem GAME_SECONDS=45 \
//!   cargo run --features gamestream --bin game-live-check
//! ```
//!
//! Exit code 0 means the session reached `Streaming` and frames were decoded.

#![cfg(feature = "gamestream")]

use std::sync::{Arc, Mutex};
use std::time::{Duration, Instant};

use streamarr_desktop_player::game_session::{ResolvedEndpoint, SessionState};
use streamarr_media_lib::commands::game::{live, GameCommand};

/// A logger, because the interesting diagnostics are `log::info!` calls inside the
/// library and a binary without a logger silently discards every one of them.
///
/// Written by hand rather than pulled in as a dependency: `src/bin` cannot use
/// `dev-dependencies`, and a logging crate would ship in the app's build graph for the
/// sake of a probe.
struct StderrLogger;

impl log::Log for StderrLogger {
    fn enabled(&self, _: &log::Metadata) -> bool {
        true
    }

    fn log(&self, record: &log::Record) {
        println!("    [{}] {}", record.level(), record.args());
    }

    fn flush(&self) {}
}

fn main() {
    static LOGGER: StderrLogger = StderrLogger;
    let _ = log::set_logger(&LOGGER).map(|()| log::set_max_level(log::LevelFilter::Info));

    let url = std::env::var("GAME_WS").expect("GAME_WS fehlt");
    let ticket = std::env::var("GAME_TICKET").ok().filter(|t| !t.is_empty());
    let pin = std::env::var("GAME_PIN").ok().filter(|p| !p.is_empty());
    let seconds: u64 = std::env::var("GAME_SECONDS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(45);

    println!("Live-Spielstream gegen die echte Sitzung");
    println!("  Ziel: {}", redact_ticket(&url));
    println!(
        "  Ticket: {}",
        if ticket.is_some() {
            "vorhanden"
        } else {
            "keins"
        }
    );
    println!("  Pin:    {}", pin.as_deref().unwrap_or("keiner (DNS)"));
    println!();

    let endpoint = ResolvedEndpoint { url, ticket };
    let state = Arc::new(Mutex::new(SessionState::Connecting));
    let (commands, receiver) = std::sync::mpsc::channel::<GameCommand>();

    let thread_state = Arc::clone(&state);
    let handle = std::thread::Builder::new()
        .name("game-live-check".to_string())
        .spawn(move || live::run(endpoint, receiver, thread_state, pin))
        .expect("Der Live-Thread konnte nicht starten");

    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut last_state = String::new();
    let mut last_frames = u64::MAX;
    let mut best_frames = 0u64;
    let mut best_resolution: Option<(u32, u32)> = None;
    let mut saw_streaming = false;

    while Instant::now() < deadline {
        std::thread::sleep(Duration::from_millis(500));

        // The state is the server's answer to our offer, as the shell records it.
        let current = state
            .lock()
            .map(|s| format!("{s:?}"))
            .unwrap_or_else(|_| "gesperrt".to_string());
        if current != last_state {
            println!("  Zustand: {current}");
            if current.starts_with("Streaming") {
                saw_streaming = true;
            }
            last_state = current;
        }

        let (reply, answer) = std::sync::mpsc::channel();
        if commands.send(GameCommand::Stats(reply)).is_err() {
            println!("  Der Live-Thread nimmt keine Befehle mehr an");
            break;
        }
        if let Ok(stats) = answer.recv_timeout(Duration::from_millis(800)) {
            if stats.frames != last_frames {
                // Printed only on change: a line per poll would bury the transitions.
                println!(
                    "  Frames: {}  Auflösung: {}  seit {:.0}s",
                    stats.frames,
                    stats
                        .resolution
                        .map(|(w, h)| format!("{w}x{h}"))
                        .unwrap_or_else(|| "—".to_string()),
                    stats.elapsed.as_secs_f64()
                );
                last_frames = stats.frames;
            }
            best_frames = best_frames.max(stats.frames);
            if stats.resolution.is_some() {
                best_resolution = stats.resolution;
            }
        }

        if state.lock().map(|s| s.is_terminal()).unwrap_or(true) {
            break;
        }
    }

    // Stops the stream and tells the server, which is what keeps a diagnostic from
    // leaving a container behind.
    let _ = commands.send(GameCommand::Stop);
    let _ = handle.join();

    println!();
    println!("  Höchste Framezahl: {best_frames}");
    println!(
        "  Auflösung: {}",
        best_resolution
            .map(|(w, h)| format!("{w}x{h}"))
            .unwrap_or_else(|| "keine".to_string())
    );
    println!("  Streaming erreicht: {saw_streaming}");
    let ok = saw_streaming && best_frames > 0;
    println!(
        "ERGEBNIS: {}",
        if ok {
            "Echter Lightrays-Stream, Frames dekodiert"
        } else if saw_streaming {
            "Verbindung stand, aber es kamen keine Frames an"
        } else {
            "FEHLGESCHLAGEN — der Stream kam nicht zustande"
        }
    );
    std::process::exit(if ok { 0 } else { 1 });
}

/// Keeps a ticket out of the terminal, in case one ever arrives inside the URL.
fn redact_ticket(url: &str) -> String {
    match url.split_once("ticket=") {
        Some((head, tail)) => {
            let end = tail.find('&').unwrap_or(tail.len());
            format!("{head}ticket=<redacted>{}", &tail[end..])
        }
        None => url.to_string(),
    }
}
