//! Live proof of the native playback chain against the **real** server.
//!
//! `play_probe.rs` next to this file proves the same chain against a substitute server
//! behind a fixed pin on 127.0.0.1. This one is for the deployment: capabilities are
//! measured, the play endpoint is asked with them as query parameters, the plan is
//! built, the name is routed to the pinned address, and mpv is started through the same
//! `Mpv::start` the shell uses.
//!
//! It exists because a proof that cannot be repeated is not a proof, and because the
//! three live proofs are the one thing the closing report has to leave open when it
//! cannot run them.
//!
//! Run from `frontend/src-tauri`:
//!
//! ```text
//! set -a; . ~/.config/streamarr/testserver.env; set +a
//! PLAY_BASE="$STREAMARR_BASE_URL" PLAY_TOKEN="$STREAMARR_API_KEY" \
//!   PLAY_PIN=10.10.60.30 PLAY_CA=/tmp/luebke-ca.pem \
//!   cargo run --example play_live_probe
//! ```
//!
//! * `PLAY_GUID` — item to play. Defaults to the test film.
//! * `PLAY_PIN` — optional. Without it mpv resolves the name itself, which is exactly
//!   the split-DNS case the pin exists for; with it the tunnel is exercised too.
//! * `PLAY_CA` — optional PEM, needed when the server uses an internal CA that the
//!   container does not trust.
//! * `PLAY_START` — overrides the resume position. This is how resume is proven as a
//!   separate thing from a fresh start.
//! * `PLAY_SECONDS` — how long to watch. Default 25.
//!
//! No credentials are read from the repository: the token arrives in the environment.
//!
//! The picture goes to `vo=null` and the sound to `ao=null`. That is deliberate — this
//! proves the *chain*, decodes frames and reports position, and works without a display.
//! Whether a picture appears is a different question, answered by starting the app.

use std::time::{Duration, Instant};

use streamarr_desktop_player::capabilities::Capabilities;
use streamarr_desktop_player::mpv::{HdrMode, Mpv, PlayerOptions, PlayerState, TrackKind};
use streamarr_desktop_player::plan::{notices_for, plan_playback};
use streamarr_desktop_player::playback::PlayResponse;
use streamarr_desktop_player::profile::{Profile, ServerAddress};
use streamarr_desktop_player::resolve_tunnel::{tunnel_plan, ResolveTunnel};

/// The test film used throughout this project.
const DEFAULT_GUID: &str = "9b0308f3-9426-4e92-b765-1b05d87ed656";

/// The same four verbs the shell uses, over whichever backend this build selected.
///
/// Both variants exist so the same probe can be run either way; only one is ever constructed
/// per build, which is the point.
#[allow(dead_code)]
enum Player {
    Process(Mpv),
    #[cfg(feature = "libmpv")]
    Native(streamarr_desktop_player::libmpv::InProcessPlayer),
}

impl Player {
    fn next_event(&mut self, timeout: Duration) -> Option<serde_json::Value> {
        match self {
            Player::Process(mpv) => mpv.next_event(timeout),
            #[cfg(feature = "libmpv")]
            Player::Native(player) => player.next_event(timeout),
        }
    }

    fn has_exited(&mut self) -> bool {
        match self {
            Player::Process(mpv) => mpv.has_exited(),
            #[cfg(feature = "libmpv")]
            Player::Native(_) => false,
        }
    }

    fn stop(&mut self) {
        match self {
            Player::Process(mpv) => mpv.stop(),
            #[cfg(feature = "libmpv")]
            Player::Native(player) => {
                let _ = player.stop();
            }
        }
    }
}

fn main() {
    let base = std::env::var("PLAY_BASE").expect("PLAY_BASE fehlt");
    let token = std::env::var("PLAY_TOKEN").expect("PLAY_TOKEN fehlt");
    let guid = std::env::var("PLAY_GUID").unwrap_or_else(|_| DEFAULT_GUID.to_string());
    let pin = std::env::var("PLAY_PIN").ok().filter(|p| !p.is_empty());
    let ca = std::env::var("PLAY_CA").ok().filter(|p| !p.is_empty());
    let seconds: u64 = std::env::var("PLAY_SECONDS")
        .ok()
        .and_then(|s| s.parse().ok())
        .unwrap_or(25);

    let mut server = ServerAddress::new(&base);
    // `parse_pin` takes `<ip>` or `<ip>:<port>`; without a port it means 443, which is
    // this deployment. Stated rather than assumed by the reader.
    server.resolve_override = pin.clone();
    server.validate().expect("Serveradresse");
    let profile = Profile::new("standard", "Standard", server.clone());

    // ── 1. Capabilities, measured rather than declared ──
    //
    // The same call the shell makes, and the reason the first probe of this project
    // measured a transcode it did not need: the server decides direct play from what it
    // is told here, and told nothing it transcodes.
    let capabilities = Capabilities::detect(3840, false, false, true, env!("CARGO_PKG_VERSION"));
    println!("1. Gemeldete Fähigkeiten");
    for (key, value) in capabilities.play_query() {
        println!(
            "     {key} = {}",
            value.chars().take(110).collect::<String>()
        );
    }
    let path = streamarr_media_lib::commands::playback::play_path(&guid, &capabilities);
    println!("   Pfad: {}", path.chars().take(150).collect::<String>());

    // ── 2. Ask the play endpoint, exactly as the app does ──
    let client = streamarr_media_lib::api::ApiClient::new(&server).expect("Client");
    let rt = tokio::runtime::Runtime::new().expect("Runtime");
    let request = streamarr_media_lib::api::RawRequest {
        method: "POST".to_string(),
        path,
        base_url: None,
        headers: vec![
            ("Accept".to_string(), "application/json".to_string()),
            ("Authorization".to_string(), format!("Bearer {token}")),
        ],
        body: Some("{}".to_string()),
        timeout_ms: Some(30_000),
    };
    let response = rt
        .block_on(client.raw_request(&request))
        .expect("Wiedergabe-Anfrage");
    println!("2. Server antwortet: HTTP {}", response.status);
    let text = match response.body {
        streamarr_media_lib::api::RawBody::Text(text) => text,
        _ => panic!("Der Server hat keinen Text geliefert."),
    };
    if response.status != 200 {
        panic!(
            "Der Server hat die Wiedergabe abgelehnt: {}",
            text.chars().take(300).collect::<String>()
        );
    }
    let body: serde_json::Value = serde_json::from_str(&text).expect("JSON");
    let play = PlayResponse::parse(&body).expect("Wiedergabe-Antwort");
    let duration = play.duration.unwrap_or(0.0);
    println!(
        "   Methode: {}  direct_play={}  Dauer: {:.0}s  {}x{}",
        play.method.as_str(),
        play.is_direct_play(),
        duration,
        play.width.unwrap_or(0),
        play.height.unwrap_or(0)
    );

    // ── 3. Plan ──
    //
    // `PLAY_START` overrides the resume position, so resume can be proven as its own
    // thing. Without it the stored position is 0 — this probe does not read the user's
    // viewing history, and pretending to would make the resume proof unfalsifiable.
    let stored = std::env::var("PLAY_START")
        .ok()
        .and_then(|s| s.parse::<f64>().ok());
    let plan = plan_playback(
        &play,
        &server,
        &profile,
        std::path::Path::new("/tmp/streamarr-live-playerconf"),
        stored.unwrap_or(0.0),
        if stored.is_some() {
            Some(duration)
        } else {
            None
        },
        false,
        HdrMode::Auto,
    )
    .expect("Plan");
    println!(
        "3. Plan: {}",
        plan.url.chars().take(130).collect::<String>()
    );
    println!("   Start bei {:.1}s", plan.start_position);
    for notice in notices_for(&plan) {
        println!("   Hinweis: {:?}", notice);
    }

    // ── 4. The tunnel, and only when a pin is set ──
    //
    // The same rule as the shell: without a pin mpv resolves the name itself, which for
    // a split-DNS deployment returns a dead address. The port is taken from the plan's
    // URL rather than hard-coded, because hard-coding it is how the earlier probe ended
    // up tied to one deployment.
    let tunnel = pin.as_ref().map(|pin| {
        let port = plan
            .url
            .split("://")
            .nth(1)
            .and_then(|rest| rest.split('/').next())
            .and_then(|authority| authority.rsplit_once(':'))
            .and_then(|(_, p)| p.parse::<u16>().ok())
            .unwrap_or(443);
        let mapping = tunnel_plan(&plan.stream_host, port, Some(pin)).expect("Mapping");
        let tunnel = ResolveTunnel::start(vec![mapping]).expect("Tunnel");
        println!(
            "4. Tunnel: {} leitet `{}` an {}",
            tunnel.proxy_url(),
            plan.stream_host,
            pin
        );
        for line in tunnel.describe() {
            println!("   {line}");
        }
        tunnel
    });
    if tunnel.is_none() {
        println!("4. Kein Pin gesetzt — mpv löst den Namen selbst auf");
    }

    // ── 5. mpv, through the path the integration tests use ──
    let mut options = plan.options.clone();
    options
        .extra_args
        .push(format!("--start={:.3}", plan.start_position));
    if let Some(tunnel) = &tunnel {
        options
            .extra_args
            .push(format!("--http-proxy={}", tunnel.proxy_url()));
    }
    if let Some(ca) = &ca {
        options.extra_args.push(format!("--tls-ca-file={ca}"));
    }
    // The play token as a header, and this is what makes transcoded playback work at
    // all.
    //
    // The playlist carries `?token=…` for *itself*, but the segment URIs inside it are
    // plain relative names — the server serves ffmpeg's playlist byte for byte and does
    // not rewrite them. Resolving a relative reference against a base with a query drops
    // the query (RFC 3986), so every segment request arrives without a token and is
    // answered with 401 `No play token provided`. Measured, not deduced: the playlist
    // loaded and all 124 segment attempts were refused.
    //
    // `_verify_play_token` accepts the token from an `Authorization: Bearer` header as
    // well as the query, and ffmpeg applies the headers set here to *every* request in
    // the HLS chain, not just the manifest. So one header closes the gap without
    // touching the server.
    let hls = !play.is_direct_play();
    if hls {
        options.extra_args.push(format!(
            "--http-header-fields=Authorization: Bearer {}",
            play.token
        ));
        println!("5. HLS: Play-Token geht als Header mit (die Segment-URLs tragen keins)");
    }
    // Headless on purpose; see the module comment.
    options.ao = "null".to_string();
    options.vo = "null".to_string();

    let mut mpv = start_player(&plan.url, &options);
    println!("6. Wiedergabe gestartet ({})", backend_name());

    // ── 6. Watch, the way the shell does ──
    let mut state = PlayerState {
        idle: false,
        ..Default::default()
    };
    let deadline = Instant::now() + Duration::from_secs(seconds);
    let mut saw_position = false;
    let mut highest = 0.0f64;
    let mut tracks_printed = false;
    let target = plan.start_position + 2.0;

    while Instant::now() < deadline {
        if let Some(event) = mpv.next_event(Duration::from_millis(200)) {
            let name = event.get("event").and_then(|v| v.as_str()).unwrap_or("");
            match name {
                "property-change" => {
                    let prop = event.get("name").and_then(|v| v.as_str()).unwrap_or("");
                    let data = event
                        .get("data")
                        .cloned()
                        .unwrap_or(serde_json::Value::Null);
                    if state.apply_event(prop, &data) && prop == "time-pos" {
                        highest = highest.max(state.position);
                        println!(
                            "   Position: {:.2}s / {:.2}s",
                            state.position, state.duration
                        );
                        // The track list, once the file is open: this is what
                        // `player_tracks` hands the interface, and what the interface
                        // now offers as dropdowns.
                        if !tracks_printed && state.position > 0.5 {
                            tracks_printed = true;
                            print_tracks(&mut mpv);
                        }
                        if state.position >= target {
                            saw_position = true;
                            println!("   -> Wiedergabe läuft über die Zielposition hinaus");
                            break;
                        }
                    }
                }
                "file-loaded" => println!("   Datei geladen"),
                "end-file" => {
                    let reason = event.get("reason").and_then(|v| v.as_str()).unwrap_or("?");
                    println!("   Datei beendet: {reason}");
                    break;
                }
                _ => {}
            }
        }
        if mpv.has_exited() {
            println!("   mpv hat sich beendet");
            break;
        }
    }
    mpv.stop();

    if let Some(tunnel) = &tunnel {
        println!(
            "8. Verbindungen durch den Tunnel: {}",
            tunnel.accepted_connections()
        );
    }
    println!("   Höchste Position: {highest:.2}s");

    // ── 9. Release the session ──
    //
    // A transcode session holds one of the server's transcode slots until it goes idle,
    // and the slots are limited — measured: after a sweep of play requests the endpoint
    // answered `503 Server transcoding capacity reached`. A probe that leaves slots
    // behind takes the deployment out of service for the next one, so it ends what it
    // started.
    if let Some(session) = &play.session_id {
        let cleanup = streamarr_media_lib::api::RawRequest {
            method: "DELETE".to_string(),
            path: format!("/api/sessions/{session}"),
            base_url: None,
            headers: vec![("Authorization".to_string(), format!("Bearer {token}"))],
            body: None,
            timeout_ms: Some(15_000),
        };
        match rt.block_on(client.raw_request(&cleanup)) {
            Ok(r) if r.status < 300 => println!("9. Sitzung {} freigegeben", &session[..8]),
            Ok(r) => println!("9. Sitzung NICHT freigegeben: HTTP {}", r.status),
            Err(e) => println!("9. Sitzung NICHT freigegeben: {e}"),
        }
    }

    // Position advanced *past where it started* is the claim. Anything less and the
    // picture could have been a frozen first frame.
    let ok = saw_position;
    println!(
        "ERGEBNIS: {}",
        if ok {
            "Wiedergabe über den nativen mpv-Kern, Position läuft"
        } else {
            "FEHLGESCHLAGEN — die Position kam nicht über den Startpunkt hinaus"
        }
    );
    std::process::exit(if ok { 0 } else { 1 });
}

/// Prints mpv's own track list, grouped by kind.
/// Starts the backend this build selected.
///
/// With `libmpv` the handle is created here — an example has no GTK, so the ordering
/// constraint that shapes the app does not apply — and `vo` is forced back to `null`
/// afterwards, because the in-process option set always sets it to `libmpv` and this probe has
/// no window to render into.
fn start_player(url: &str, options: &PlayerOptions) -> Player {
    #[cfg(feature = "libmpv")]
    {
        let mpv = streamarr_desktop_player::libmpv::Libmpv::create().expect("libmpv");
        let player = streamarr_desktop_player::libmpv::InProcessPlayer::start(mpv, url, options)
            .expect("libmpv startet");
        Player::Native(player)
    }
    #[cfg(not(feature = "libmpv"))]
    {
        Player::Process(Mpv::start(url, options).expect("mpv"))
    }
}

fn backend_name() -> &'static str {
    if cfg!(feature = "libmpv") {
        "im App-Prozess"
    } else {
        "getrennter Prozess"
    }
}

fn print_tracks(player: &mut Player) {
    let list = match player {
        Player::Process(mpv) => mpv.track_list(),
        #[cfg(feature = "libmpv")]
        Player::Native(player) => player.track_list(),
    };
    if list.tracks.is_empty() {
        println!("   Spuren: keine gemeldet");
        return;
    }
    println!("   Spuren (aus mpv, nicht aus der Antwort des Servers):");
    for track in &list.tracks {
        let kind = match track.kind {
            TrackKind::Video => "Video",
            TrackKind::Audio => "Audio",
            TrackKind::Subtitle => "Untertitel",
        };
        println!(
            "     #{} {:<11} {:<28} {:<6} {}{}",
            track.id,
            kind,
            track.title.clone().unwrap_or_else(|| "—".to_string()),
            track.language.clone().unwrap_or_else(|| "—".to_string()),
            track.codec.clone().unwrap_or_else(|| "—".to_string()),
            if track.selected { "  [gewählt]" } else { "" }
        );
        if track.external {
            println!("        (extern)");
        }
    }
}
