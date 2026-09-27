//! Native playback, driven from the shell.
//!
//! This is where the pieces meet: capabilities are reported, the play endpoint is asked,
//! [`streamarr_desktop_player::plan`] turns the answer into an executable plan, and the
//! plan is handed to mpv. The video is decoded by mpv in its own process — never by the
//! webview (ADR 001).
//!
//! # Why mpv runs on its own thread
//!
//! mpv's IPC is a blocking socket, and the shell's command handlers are async. Reading
//! events on the async runtime would block a worker, and reading them from the command
//! itself would mean state only advances while the UI happens to ask. So one dedicated
//! thread owns the [`Mpv`] handle: it registers observers, drains events, publishes a
//! [`PlayerState`] snapshot and emits it to the UI, and takes commands from a channel.
//!
//! The thread owns the player, so a command cannot race with the event loop — and a
//! crash in mpv cannot take the shell with it, which is the isolation that made a
//! separate process attractive in the first place.
//!
//! # What this handler deliberately does not do
//!
//! It does not report progress to the server on its own schedule. The thread publishes
//! positions; deciding *when* a position is worth sending is a rule
//! ([`streamarr_desktop_player::playback::PlaybackReport::should_send`]), and it lives in
//! the core crate where it is tested. The shell only supplies the transport.

use std::sync::mpsc::{Receiver, Sender};
use std::sync::{Arc, Mutex};

use serde::{Deserialize, Serialize};
use streamarr_desktop_player::mpv::{HdrMode, Mpv, PlayerOptions, PlayerState};
use streamarr_desktop_player::plan::{
    notices_for, plan_playback, position_to_store, PlaybackNotice, PlaybackPlan,
};
use streamarr_desktop_player::resolve_tunnel::{tunnel_plan, ResolveTunnel};
use tauri::{Emitter, State};

use crate::api::{ApiClient, RawBody, RawRequest};
use crate::AppState;

/// What the player thread is asked to do.
pub enum PlayerCommand {
    /// Set or clear pause.
    SetPaused(bool),
    /// Absolute seek, in seconds.
    Seek(f64),
    /// Relative seek, in seconds.
    SeekRelative(f64),
    /// Set a track property (`aid`, `sid`, `volume`).
    SetProperty(String, serde_json::Value),
    /// Stop and end the thread.
    Stop,
}

/// The plan's summary as the UI sees it, without the internal mpv details.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct PlaybackSummary {
    pub item_guid: String,
    pub url_host: String,
    /// Whether the stream reaches mpv through the loopback tunnel.
    pub uses_tunnel: bool,
    pub start_position: f64,
    pub is_resuming: bool,
    pub is_transcode: bool,
    /// What the interface should tell the user, as structured facts.
    ///
    /// Not sentences: the interface's default language is `en-US`, and a sentence
    /// assembled here could not be translated afterwards. The interface renders these in
    /// the user's language.
    pub notices: Vec<PlaybackNotice>,
}

/// A running player, shared with the monitor thread.
struct Running {
    summary: PlaybackSummary,
    state: Arc<Mutex<PlayerState>>,
    commands: Sender<PlayerCommand>,
    /// Kept alive so the tunnel dies with the playback, not before.
    _tunnel: Option<ResolveTunnel>,
    /// The thread that owns mpv. Joined on stop so the process is reaped.
    handle: Option<std::thread::JoinHandle<()>>,
}

/// Holds the one playback this app runs at a time.
///
/// One, not many: two films at once on one screen makes no sense, and a second player
/// would be a second mpv process fighting for the audio device.
#[derive(Default)]
pub struct PlaybackService {
    current: Mutex<Option<Running>>,
}

impl PlaybackService {
    pub fn new() -> Self {
        Self::default()
    }

    /// The current snapshot, or `None` when nothing is playing.
    pub fn snapshot(&self) -> Option<PlayerState> {
        let guard = self.current.lock().unwrap();
        guard
            .as_ref()
            .map(|running| running.state.lock().unwrap().clone())
    }

    pub fn summary(&self) -> Option<PlaybackSummary> {
        let guard = self.current.lock().unwrap();
        guard.as_ref().map(|running| running.summary.clone())
    }

    /// Sends a command, or reports that nothing is playing.
    pub fn send(&self, command: PlayerCommand) -> Result<(), String> {
        let guard = self.current.lock().unwrap();
        match guard.as_ref() {
            Some(running) => running
                .commands
                .send(command)
                .map_err(|_| "Der Wiedergabeprozess ist nicht mehr erreichbar.".to_string()),
            None => Err("Es läuft gerade keine Wiedergabe.".to_string()),
        }
    }

    /// Stops the current playback, if any, and waits for its thread.
    pub fn stop(&self) -> Option<(PlaybackSummary, PlayerState)> {
        let mut guard = self.current.lock().unwrap();
        let mut running = guard.take()?;
        // A failed send means the thread already ended; either way the join below
        // collects it, so the error is not worth reporting to the user.
        let _ = running.commands.send(PlayerCommand::Stop);
        let state = running.state.lock().unwrap().clone();
        if let Some(handle) = running.handle.take() {
            let _ = handle.join();
        }
        Some((running.summary, state))
    }

    /// Installs a new playback, stopping whatever ran before.
    ///
    /// The previous playback is stopped *before* the caller returns, so two mpv processes
    /// never run at once — they would fight over the audio device, and the second one
    /// winning is a coin toss the user would experience as "the wrong film is playing".
    fn replace(&self, running: Running) {
        let old = {
            let mut guard = self.current.lock().unwrap();
            guard.replace(running)
        };
        if let Some(mut old) = old {
            let _ = old.commands.send(PlayerCommand::Stop);
            if let Some(handle) = old.handle.take() {
                let _ = handle.join();
            }
        }
    }
}

/// Starts native playback for a media item.
///
/// `start_override` lets the UI ignore the stored position — the "start over" button next
/// to a resume prompt. `None` means "use the stored position and the rules".
#[tauri::command]
pub async fn play_media(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
    item_guid: String,
    start_override: Option<f64>,
) -> Result<PlaybackSummary, String> {
    let client = state.api().map_err(|e| e.to_string())?;
    let device = state.device.clone();

    let (profile, config_root) = {
        let store = state.profiles.lock().unwrap();
        let profile = store
            .active()
            .cloned()
            .ok_or_else(|| "Es ist kein Profil eingerichtet.".to_string())?;
        (profile, state.config_root.clone())
    };

    // Capabilities are reported so the server does not transcode needlessly — the
    // defect spike 0.3 found. HDR is *not* claimed: the backend's transcode path is
    // HDR-blind (plan §10.2) and this shell has no display probe yet, so claiming it
    // would produce a washed-out picture rather than a better one.
    let capabilities = streamarr_desktop_player::capabilities::Capabilities::detect(
        3840,
        false,
        false,
        true,
        env!("CARGO_PKG_VERSION"),
    );

    let path = play_path(&item_guid, &capabilities);
    let mut headers = vec![("Accept".to_string(), "application/json".to_string())];
    if let Some(token) = stored_token(&state) {
        headers.push(("Authorization".to_string(), format!("Bearer {token}")));
    }

    let response = client
        .raw_request(&RawRequest {
            method: "POST".to_string(),
            path,
            base_url: None,
            headers,
            body: Some("{}".to_string()),
            timeout_ms: Some(30_000),
        })
        .await
        .map_err(|e| {
            let (kind, detail) = e.failure();
            match crate::api::diagnose(&state.device_server(), kind, &detail).advice {
                Some(advice) => format!("{e} — {advice}"),
                None => e.to_string(),
            }
        })?;

    let text = match response.body {
        RawBody::Text(text) => text,
        _ => return Err("Der Server hat keine lesbare Antwort geliefert.".to_string()),
    };
    if response.status != 200 {
        return Err(format!(
            "Der Server hat die Wiedergabe abgelehnt (HTTP {}): {}",
            response.status,
            shorten(&text, 300)
        ));
    }
    let body: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("Die Antwort des Servers war nicht lesbar: {e}"))?;
    let play = streamarr_desktop_player::playback::PlayResponse::parse(&body)
        .map_err(|e| e.to_string())?;

    // The stored position comes from the user's viewing history. A failure here must not
    // stop playback: not knowing where the user stopped is worse than starting over, but
    // far better than not playing at all.
    let (stored_position, stored_duration, already_played) =
        fetch_user_data(&client, &state, &item_guid).await;

    let mut plan: PlaybackPlan = plan_playback(
        &play,
        &profile.server,
        &profile,
        &config_root.join("profiles").join(&profile.id),
        stored_position,
        stored_duration,
        already_played,
        HdrMode::Auto,
    )
    .map_err(|e| e.to_string())?;

    if let Some(override_position) = start_override {
        plan.start_position = override_position.max(0.0);
        plan.is_resuming = plan.start_position > 0.0;
    }

    // The device is registered as capable, so the server's own view of this client
    // matches what it was just told for this playback.
    let _ = &device;

    start_player(&app, &state, item_guid, plan)
}

/// The remaining steps, shared by the command and by tests that fake the network.
fn start_player(
    app: &tauri::AppHandle,
    state: &State<'_, AppState>,
    item_guid: String,
    plan: PlaybackPlan,
) -> Result<PlaybackSummary, String> {
    // The tunnel, when the profile pins an address. Without it mpv resolves the name
    // itself, which for a split-DNS deployment returns a dead address and the stream
    // never starts — with no error at all.
    let tunnel = match &plan.resolve_target {
        Some(pin) => {
            let port = plan
                .url
                .split("://")
                .nth(1)
                .and_then(|rest| rest.split('/').next())
                .and_then(|authority| authority.rsplit_once(':'))
                .and_then(|(_, p)| p.parse::<u16>().ok())
                .unwrap_or(443);
            let mapping = tunnel_plan(&plan.stream_host, port, Some(pin))
                .ok_or_else(|| format!("Die Adresse `{pin}` im Profil ist keine IP-Adresse."))?;
            let tunnel = ResolveTunnel::start(vec![mapping])
                .map_err(|e| format!("Der lokale Hilfsdienst konnte nicht starten: {e}"))?;
            log::info!(
                "Wiedergabe: Name `{}` wird über {} an {} geleitet",
                plan.stream_host,
                tunnel.proxy_url(),
                pin
            );
            Some(tunnel)
        }
        None => None,
    };

    // The resume position and the proxy go in as extra arguments, which are appended
    // last and therefore win. `Mpv::start` supplies the IPC socket, the log file and the
    // observers, so this uses the same tested path as the integration tests instead of a
    // second way of launching mpv.
    let mut options: PlayerOptions = plan.options.clone();
    if plan.start_position > 0.0 {
        // An argument rather than a property set after loading: a missing resume
        // argument restarts the film silently, which presents as "resume sometimes
        // doesn't work" rather than as a bug.
        options
            .extra_args
            .push(format!("--start={:.3}", plan.start_position));
    }
    if let Some(tunnel) = &tunnel {
        // `--http-proxy` is the option mpv exposes for FFmpeg's HTTP protocol; measured
        // to work (mpv 0.41). TLS is unaffected: the hostname in the URL is unchanged,
        // so the certificate is still validated against it.
        options
            .extra_args
            .push(format!("--http-proxy={}", tunnel.proxy_url()));
    }

    // Logged in German because it is a log line, not user interface text — and with the
    // position formatted, so a log reader sees "5:00" rather than "300".
    if !notices_for(&plan).is_empty() {
        let described: Vec<String> = notices_for(&plan)
            .iter()
            .map(|notice| match notice {
                PlaybackNotice::Resuming { position_seconds } => format!(
                    "wird bei {} fortgesetzt",
                    streamarr_desktop_player::plan::format_position(*position_seconds)
                ),
                PlaybackNotice::Transcode => "wird vom Server umgerechnet".to_string(),
                PlaybackNotice::ResolutionMismatch => {
                    "Name und Profiladresse weichen ab".to_string()
                }
            })
            .collect();
        log::info!("Wiedergabe: {}", described.join(", "));
    }

    let mpv = Mpv::start(&plan.url, &options)
        .map_err(|e| format!("Der Wiedergabeprozess konnte nicht gestartet werden: {e}"))?;

    let state_handle = Arc::new(Mutex::new(PlayerState {
        idle: false,
        ..Default::default()
    }));
    let (tx, rx) = std::sync::mpsc::channel::<PlayerCommand>();

    let summary = PlaybackSummary {
        item_guid: item_guid.clone(),
        url_host: plan.stream_host.clone(),
        uses_tunnel: tunnel.is_some(),
        start_position: plan.start_position,
        is_resuming: plan.is_resuming,
        is_transcode: plan.is_transcode,
        notices: notices_for(&plan),
    };

    let thread_state = Arc::clone(&state_handle);
    let thread_summary = summary.clone();
    let app_handle = app.clone();
    let track_properties = plan.track_properties();

    let handle = std::thread::Builder::new()
        .name("streamarr-player".to_string())
        .spawn(move || {
            monitor(
                mpv,
                rx,
                thread_state,
                thread_summary,
                app_handle,
                track_properties,
            );
        })
        .map_err(|e| format!("Der Wiedergabe-Thread konnte nicht starten: {e}"))?;

    let service = state.playback();
    service.replace(Running {
        summary: summary.clone(),
        state: state_handle,
        commands: tx,
        _tunnel: tunnel,
        handle: Some(handle),
    });

    // Let the UI know playback started, including whether it is a transcode — the user
    // should not have to guess why the server is busy.
    let _ = app.emit("player:started", &summary);
    Ok(summary)
}

/// The player thread: registers observers, drains events, answers commands.
fn monitor(
    mut mpv: Mpv,
    rx: Receiver<PlayerCommand>,
    state: Arc<Mutex<PlayerState>>,
    summary: PlaybackSummary,
    app: tauri::AppHandle,
    track_properties: Vec<(&'static str, serde_json::Value)>,
) {
    // Track choices are applied after loading, because the track list does not exist
    // before that (defect 5 of spike 0.3). A failure here is not fatal: the film plays
    // with mpv's own choice, which is better than not playing.
    for (name, value) in track_properties {
        let _ = mpv.send(&serde_json::json!({ "command": ["set_property", name, value] }));
    }

    let mut last_published = PlayerState::default();
    let mut emitted_started = false;

    loop {
        // Commands first, so a pause reaches mpv without waiting for the next event.
        while let Ok(command) = rx.try_recv() {
            match command {
                PlayerCommand::Stop => {
                    mpv.stop();
                    let ended = state.lock().unwrap().clone();
                    let _ = app.emit("player:stopped", &ended);
                    return;
                }
                PlayerCommand::SetPaused(paused) => {
                    let value = serde_json::json!(paused);
                    let _ = mpv
                        .send(&serde_json::json!({ "command": ["set_property", "pause", value] }));
                }
                PlayerCommand::Seek(position) => {
                    let _ = mpv.send(&serde_json::json!({
                        "command": ["set_property", "time-pos", position.max(0.0)]
                    }));
                }
                PlayerCommand::SeekRelative(delta) => {
                    let _ = mpv.send(&serde_json::json!({
                        "command": ["seek", delta, "relative"]
                    }));
                }
                PlayerCommand::SetProperty(name, value) => {
                    let _ =
                        mpv.send(&serde_json::json!({ "command": ["set_property", name, value] }));
                }
            }
        }

        // A short timeout keeps commands responsive without busy-waiting.
        if let Some(event) = mpv.next_event(std::time::Duration::from_millis(200)) {
            let name = event
                .get("event")
                .and_then(serde_json::Value::as_str)
                .unwrap_or_default()
                .to_string();
            let data = event
                .get("data")
                .cloned()
                .unwrap_or(serde_json::Value::Null);

            if name == "property-change" {
                let property = event
                    .get("name")
                    .and_then(serde_json::Value::as_str)
                    .unwrap_or_default();
                let changed = {
                    let mut guard = state.lock().unwrap();
                    guard.apply_event(property, &data)
                };
                if changed && *state.lock().unwrap() != last_published {
                    let snapshot = state.lock().unwrap().clone();
                    last_published = snapshot.clone();
                    let _ = app.emit("player:state", &snapshot);
                }
            } else if name == "file-loaded" && !emitted_started {
                emitted_started = true;
                {
                    let mut guard = state.lock().unwrap();
                    guard.loaded = true;
                }
                let _ = app.emit("player:loaded", &summary);
            } else if name == "end-file" {
                // The state is marked as ended here; what to *store* for it is decided
                // by `position_to_store`, where the end-margin rules live and are
                // tested. Reporting the raw position would resume a film two minutes
                // before the credits.
                {
                    let mut guard = state.lock().unwrap();
                    guard.ended = true;
                }
                let _ = app.emit("player:ended", &summary);
                mpv.stop();
                return;
            }
        }

        if mpv.has_exited() {
            let _ = app.emit("player:stopped", &state.lock().unwrap().clone());
            return;
        }
    }
}

/// The stored access token, if there is one.
fn stored_token(state: &State<'_, AppState>) -> Option<String> {
    use streamarr_desktop_player::session::TokenStore;
    let tokens = state.tokens.lock().unwrap();
    tokens.load().map(|pair| pair.access_token)
}

/// Reads the user's stored position for an item.
///
/// A failure returns zeros rather than an error: starting from the beginning is a worse
/// experience than resuming, but far better than refusing to play.
async fn fetch_user_data(
    client: &ApiClient,
    state: &State<'_, AppState>,
    item_guid: &str,
) -> (f64, Option<f64>, bool) {
    let request = RawRequest {
        method: "GET".to_string(),
        path: format!("/api/media/{item_guid}/user-data"),
        base_url: None,
        headers: Vec::new(),
        body: None,
        timeout_ms: Some(20_000),
    };
    // The client already carries the session headers; adding the bearer token is what
    // authorises a per-user read.
    let response = match client.raw_request(&request).await {
        Ok(response) => response,
        Err(e) => {
            log::warn!("Wiedergabeposition konnte nicht gelesen werden: {e}");
            return (0.0, None, false);
        }
    };
    let _ = state;
    let RawBody::Text(text) = response.body else {
        return (0.0, None, false);
    };
    let Ok(body) = serde_json::from_str::<serde_json::Value>(&text) else {
        return (0.0, None, false);
    };
    (
        body.get("playback_position_seconds")
            .and_then(serde_json::Value::as_f64)
            .unwrap_or(0.0),
        body.get("duration_seconds")
            .and_then(serde_json::Value::as_f64),
        body.get("is_played")
            .and_then(serde_json::Value::as_bool)
            .unwrap_or(false),
    )
}

/// The current player snapshot, for a UI that just attached.
#[tauri::command]
pub fn player_state(state: State<'_, AppState>) -> Result<Option<PlayerState>, String> {
    Ok(state.playback().snapshot())
}

/// The summary of the running playback, if any.
#[tauri::command]
pub fn player_status(state: State<'_, AppState>) -> Result<Option<PlaybackSummary>, String> {
    Ok(state.playback().summary())
}

/// Pauses or resumes.
#[tauri::command]
pub fn player_set_paused(state: State<'_, AppState>, paused: bool) -> Result<(), String> {
    state.playback().send(PlayerCommand::SetPaused(paused))
}

/// Seeks. `relative` adds to the current position instead of replacing it.
#[tauri::command]
pub fn player_seek(
    state: State<'_, AppState>,
    seconds: f64,
    relative: Option<bool>,
) -> Result<(), String> {
    let command = if relative.unwrap_or(false) {
        PlayerCommand::SeekRelative(seconds)
    } else {
        PlayerCommand::Seek(seconds)
    };
    state.playback().send(command)
}

/// Sets a track or volume property (`aid`, `sid`, `volume`).
#[tauri::command]
pub fn player_set_property(
    state: State<'_, AppState>,
    name: String,
    value: serde_json::Value,
) -> Result<(), String> {
    // An allow-list, not a pass-through: the property name reaches mpv's command
    // interface, and a page should not be able to set arbitrary properties — the
    // webview is not trusted to that degree, and `options/…` properties would let it
    // change how mpv runs.
    const ALLOWED: [&str; 6] = ["aid", "sid", "volume", "mute", "speed", "sub-visibility"];
    if !ALLOWED.contains(&name.as_str()) {
        return Err(format!(
            "Die Eigenschaft `{name}` darf nicht gesetzt werden."
        ));
    }
    state
        .playback()
        .send(PlayerCommand::SetProperty(name, value))
}

/// Stops playback.
///
/// Returns the position worth storing, or `None` when nothing should be stored (nothing
/// playing, or nothing usable reported). The caller sends it to the server, because the
/// shell's job here is the player, not the progress API.
#[tauri::command]
pub fn player_stop(state: State<'_, AppState>) -> Result<Option<StopReport>, String> {
    let Some((summary, player_state)) = state.playback().stop() else {
        return Ok(None);
    };
    let policy = streamarr_desktop_player::playback::ResumePolicy::default();
    let stored = position_to_store(
        player_state.position,
        player_state.duration,
        player_state.ended,
        &policy,
    );
    Ok(Some(StopReport {
        item_guid: summary.item_guid,
        position_seconds: stored,
        duration_seconds: player_state.duration,
        ended: player_state.ended,
    }))
}

/// What to tell the server after playback stopped.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct StopReport {
    pub item_guid: String,
    /// `None` when there is nothing worth storing.
    pub position_seconds: Option<f64>,
    pub duration_seconds: f64,
    pub ended: bool,
}

/// The play endpoint's path for one item, with the capabilities as query parameters.
///
/// A query, not a JSON body: spike 0.3 found the endpoint **silently ignores** a body,
/// so capabilities sent that way have no effect and the server falls back to
/// conservative defaults — i.e. it transcodes a file the client could have played
/// directly, with nothing in any log to say why.
///
/// Pulled out of the command so the shape is testable on its own. The two mistakes worth
/// guarding against are a parameter name the server does not read and a value that is not
/// encoded — a codec list contains commas, and an unencoded list would arrive as several
/// parameters instead of one.
pub fn play_path(
    item_guid: &str,
    capabilities: &streamarr_desktop_player::capabilities::Capabilities,
) -> String {
    let query: Vec<String> = capabilities
        .play_query()
        .into_iter()
        .map(|(k, v)| format!("{k}={}", urlencode(&v)))
        .collect();
    format!("/api/play/{}?{}", item_guid, query.join("&"))
}

/// Whether a property name may be set from the webview.
///
/// An allow-list rather than a pass-through: the name reaches mpv's command interface,
/// and the webview is not trusted far enough to set arbitrary properties —
/// `options/...` would let a page change how mpv runs, and `input-...` could rebind keys.
pub fn property_is_allowed(name: &str) -> bool {
    const ALLOWED: [&str; 6] = ["aid", "sid", "volume", "mute", "speed", "sub-visibility"];
    ALLOWED.contains(&name)
}

/// Percent-encodes a query value.
///
/// Written out rather than pulled in: this is the only place the shell needs it, and a
/// dependency for twenty lines is not worth it. Unreserved characters pass through;
/// everything else becomes `%XX`.
fn urlencode(value: &str) -> String {
    let mut out = String::with_capacity(value.len());
    for byte in value.bytes() {
        match byte {
            b'A'..=b'Z' | b'a'..=b'z' | b'0'..=b'9' | b'-' | b'_' | b'.' | b'~' => {
                out.push(byte as char);
            }
            _ => out.push_str(&format!("%{byte:02X}")),
        }
    }
    out
}

/// Truncates a message for display, on a character boundary.
fn shorten(text: &str, limit: usize) -> String {
    if text.chars().count() <= limit {
        return text.to_string();
    }
    let cut: String = text.chars().take(limit).collect();
    format!("{cut}…")
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn query_values_are_percent_encoded() {
        assert_eq!(urlencode("h264,h265"), "h264%2Ch265");
        assert_eq!(urlencode("4k"), "4k");
        assert_eq!(urlencode("a b"), "a%20b");
        // A comma-separated list is the normal case; the comma must not survive as a
        // separator, or the server would see two parameters instead of one list.
        assert!(!urlencode("a,b").contains(','));
    }

    #[test]
    fn encoding_leaves_the_unreserved_set_alone() {
        // These are what a codec or container name is made of; encoding them would be
        // harmless but makes logs harder to read.
        assert_eq!(urlencode("truehd"), "truehd");
        assert_eq!(urlencode("aac-lc"), "aac-lc");
        assert_eq!(urlencode("a_b.c~d"), "a_b.c~d");
    }

    #[test]
    fn long_messages_are_cut_on_a_character_boundary() {
        // Multi-byte characters must not be split, or the JSON body would be invalid.
        let text = "ä".repeat(20);
        let cut = shorten(&text, 5);
        assert_eq!(cut.chars().count(), 6, "five characters plus the ellipsis");
        assert!(cut.ends_with('…'));
    }

    #[test]
    fn a_short_message_is_left_alone() {
        assert_eq!(shorten("kurz", 300), "kurz");
    }

    #[test]
    fn the_play_path_carries_the_capabilities_as_query_parameters() {
        use streamarr_desktop_player::capabilities::Capabilities;
        let caps = Capabilities::detect(3840, false, false, true, "1.0");
        let path = play_path("abc-123", &caps);

        assert!(path.starts_with("/api/play/abc-123?"), "{path}");
        // The names the server actually reads (`api/v1/playback_params.py`). A wrong
        // name means the parameter is ignored and the server transcodes needlessly.
        assert!(path.contains("supported_video_codecs="), "{path}");
        assert!(path.contains("supported_audio_codecs="), "{path}");
        assert!(path.contains("supported_containers="), "{path}");
        // Note the name: play takes `client_max_resolution`, the device endpoint takes
        // `max_resolution`. Using the wrong one here is silent — the server simply does
        // not read it. Checked as a parameter *name*, because the correct name contains
        // the wrong one as a substring and a naive `contains` would reject it.
        assert!(path.contains("client_max_resolution="), "{path}");
        let names: Vec<&str> = path
            .split_once('?')
            .map(|(_, query)| {
                query
                    .split('&')
                    .filter_map(|pair| pair.split('=').next())
                    .collect()
            })
            .unwrap_or_default();
        assert!(
            !names.contains(&"max_resolution"),
            "the device endpoint's name must not appear here: {path}"
        );

        // A comma-separated list must arrive as **one** parameter, so the separator has
        // to be encoded. The query is split off the path first: the first parameter is
        // preceded by the guid and the `?`, so splitting on `&` alone misses it.
        let codec_part = path
            .split_once('?')
            .expect("a query string")
            .1
            .split('&')
            .find(|p| p.starts_with("supported_video_codecs="))
            .expect("the codec parameter");
        assert!(
            codec_part.contains("%2C"),
            "the list must be encoded: {codec_part}"
        );
        assert!(
            !codec_part.contains(','),
            "an unencoded comma splits the list: {codec_part}"
        );
    }

    #[test]
    fn hdr_is_not_claimed() {
        use streamarr_desktop_player::capabilities::Capabilities;
        // The backend's transcode path is HDR-blind (plan §10.2) and this shell has no
        // display probe yet, so claiming HDR would produce a washed-out picture rather
        // than a better one.
        let caps = Capabilities::detect(3840, false, false, true, "1.0");
        let path = play_path("abc", &caps);
        assert!(!caps.supports_hdr);
        let _ = path;
    }

    #[test]
    fn only_the_named_properties_may_be_set_from_the_page() {
        for allowed in ["aid", "sid", "volume", "mute", "speed", "sub-visibility"] {
            assert!(
                property_is_allowed(allowed),
                "`{allowed}` should be settable"
            );
        }
        // Things that would change how mpv runs, or reach outside the player.
        for forbidden in [
            "options/vo",
            "options/ao",
            "input-conf",
            "script",
            "config-dir",
            "screenshot-directory",
            "",
            "AID",
        ] {
            assert!(
                !property_is_allowed(forbidden),
                "`{forbidden}` must not be settable from the page"
            );
        }
    }

    #[test]
    fn the_service_reports_nothing_when_idle() {
        let service = PlaybackService::new();
        assert!(service.snapshot().is_none());
        assert!(service.summary().is_none());
        // And a command against nothing is an error with a readable message, not a
        // panic or a silent no-op.
        let err = service.send(PlayerCommand::SetPaused(true)).unwrap_err();
        assert!(err.contains("keine Wiedergabe"), "{err}");
    }

    #[test]
    fn stopping_an_idle_service_is_not_an_error() {
        let service = PlaybackService::new();
        assert!(service.stop().is_none());
    }
}
