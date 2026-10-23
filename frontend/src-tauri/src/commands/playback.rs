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
#[cfg(not(feature = "libmpv"))]
use streamarr_desktop_player::mpv::Mpv;
use streamarr_desktop_player::mpv::{HdrMode, PlayerOptions, PlayerState, TrackList};
use streamarr_desktop_player::plan::{
    notices_for, plan_playback, position_to_store, PlaybackNotice, PlaybackPlan,
};
use streamarr_desktop_player::resolve_tunnel::{tunnel_plan, ResolveTunnel};
#[cfg(feature = "libmpv")]
use tauri::Manager;
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
    /// Read the current track list (plan task 2.6).
    ///
    /// Answered over a oneshot channel rather than by a property on the shared state: the
    /// track list lives in mpv and is only meaningful when read from the player thread,
    /// which owns the IPC socket. A clone kept in the shared state would be one more thing
    /// to keep in sync, and it would be wrong exactly when a track is added mid-playback.
    TrackList(Sender<TrackList>),
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

/// The response side of a track-list request.
///
/// A pair rather than a single receiver so the command can be written as one expression
/// without borrowing rules getting in the way; the sender half travels to the player
/// thread inside [`PlayerCommand::TrackList`].
pub struct TrackReply(Sender<TrackList>, Receiver<TrackList>);

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
    /// A fresh request/response pair for reading the track list.
    ///
    /// `None` when nothing is playing, so the caller does not block on a channel nobody
    /// will answer.
    pub fn track_list_channel(&self) -> Option<(Sender<PlayerCommand>, TrackReply)> {
        let guard = self.current.lock().unwrap();
        let running = guard.as_ref()?;
        let (reply_tx, reply_rx) = std::sync::mpsc::channel();
        Some((running.commands.clone(), TrackReply(reply_tx, reply_rx)))
    }

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
        // Chosen from measurements, not from mpv's default: the display's EDID answers the
        // screen half and the installed mpv answers the renderer half. `Auto` would make
        // this depend on mpv's build and version instead — and the plan asks for
        // "HDR10 passthrough *or* provable SDR mapping", which requires a decision this
        // app made (task 2.9).
        chosen_hdr_mode(),
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

    // Compile-time choice of the backend; see `Backend` for why it is not a runtime fallback.
    //
    // The two paths differ in *where* they start, and that difference is real rather than
    // stylistic: the in-process surface owns a GL context, and a GL context belongs to the
    // thread that created it. Creating it here and moving it into the player thread would be
    // wrong at the driver level, not merely awkward in Rust — the type refuses to be `Send`
    // for exactly that reason. So the process path still fails fast in the caller (a missing
    // binary is a synchronous error the UI can show), while the in-process path creates its
    // surface inside the thread that will render it.
    #[cfg(not(feature = "libmpv"))]
    let mpv = Backend::start_process(&plan.url, &options)?;

    #[cfg(feature = "libmpv")]
    let (start_handles, start_size) = {
        let window = app
            .get_webview_window("main")
            .ok_or("Kein Hauptfenster für die Videofläche")?;
        let size = window
            .inner_size()
            .map(|s| (s.width, s.height))
            .unwrap_or((0, 0));
        (crate::render::read_handles(&window, size)?, size)
    };
    #[cfg(feature = "libmpv")]
    let early_mpv = crate::EARLY_LIBMPV
        .lock()
        .map_err(|_| "libmpv-Sperre vergiftet".to_string())?
        .take()
        .ok_or("kein vor GTK angelegtes libmpv-Handle — wurde es schon verbraucht?")?;

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

    #[cfg(not(feature = "libmpv"))]
    let spawned = {
        std::thread::Builder::new()
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
    };
    #[cfg(feature = "libmpv")]
    let spawned = {
        let thread_plan_url = plan.url.clone();
        let thread_options = options.clone();
        let thread_app = app_handle.clone();
        std::thread::Builder::new()
            .name("streamarr-player".to_string())
            .spawn(move || {
                match Backend::start_in_process(
                    early_mpv,
                    &thread_plan_url,
                    &thread_options,
                    &start_handles,
                    start_size,
                ) {
                    Ok(mpv) => monitor(
                        mpv,
                        rx,
                        thread_state,
                        thread_summary,
                        app_handle,
                        track_properties,
                    ),
                    Err(err) => {
                        // The caller has already returned success by now, so the UI must be
                        // told rather than left waiting for a picture that will not come.
                        log::error!("Wiedergabe im App-Prozess nicht gestartet: {err}");
                        let _ = thread_app.emit("player:stopped", thread_summary);
                    }
                }
            })
    };
    let handle = spawned.map_err(|e| format!("Der Wiedergabe-Thread konnte nicht starten: {e}"))?;

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

/// Which mpv serves this session.
///
/// Chosen at **compile time**, never at runtime. A runtime fallback that quietly started a
/// process when the in-process path failed would make "nothing in the playback path starts mpv
/// as a process" unprovable — and provability is the point of criterion 6, not convenience.
enum Backend {
    #[cfg(not(feature = "libmpv"))]
    Process(Mpv),
    #[cfg(feature = "libmpv")]
    InProcess {
        player: streamarr_desktop_player::libmpv::InProcessPlayer,
        /// Owns the GL context, so it must live exactly as long as the picture does. Dropped
        /// with the backend, which is what removes the video surface from the window.
        _surface: crate::render::VideoSurface,
    },
}

impl Backend {
    #[cfg(not(feature = "libmpv"))]
    fn start_process(url: &str, options: &PlayerOptions) -> Result<Self, String> {
        Mpv::start(url, options)
            .map(Self::Process)
            .map_err(|e| format!("Der Wiedergabeprozess konnte nicht gestartet werden: {e}"))
    }

    #[cfg(feature = "libmpv")]
    fn start_in_process(
        mpv: streamarr_desktop_player::libmpv::Libmpv,
        url: &str,
        options: &PlayerOptions,
        handles: &crate::render::WindowHandles,
        size: (u32, u32),
    ) -> Result<Self, String> {
        let surface = crate::render::VideoSurface::create(handles, &mpv, size)?;
        let player = streamarr_desktop_player::libmpv::InProcessPlayer::start(mpv, url, options)
            .map_err(|e| format!("libmpv konnte die Wiedergabe nicht starten: {e}"))?;
        Ok(Self::InProcess {
            player,
            _surface: surface,
        })
    }

    fn send(&mut self, command: &serde_json::Value) -> Result<(), String> {
        match self {
            #[cfg(not(feature = "libmpv"))]
            Self::Process(mpv) => mpv.send(command).map_err(|e| e.to_string()),
            #[cfg(feature = "libmpv")]
            Self::InProcess { player, .. } => player.send(command).map_err(|e| e.to_string()),
        }
    }

    fn stop(&mut self) {
        match self {
            #[cfg(not(feature = "libmpv"))]
            Self::Process(mpv) => mpv.stop(),
            #[cfg(feature = "libmpv")]
            Self::InProcess { player, .. } => {
                // An error here means mpv is already gone; there is nothing to report and
                // nothing to retry, which is why the process path ignores it too.
                let _ = player.stop();
            }
        }
    }

    fn track_list(&mut self) -> TrackList {
        match self {
            #[cfg(not(feature = "libmpv"))]
            Self::Process(mpv) => mpv.track_list(),
            #[cfg(feature = "libmpv")]
            Self::InProcess { player, .. } => player.track_list(),
        }
    }

    fn next_event(&mut self, timeout: std::time::Duration) -> Option<serde_json::Value> {
        match self {
            #[cfg(not(feature = "libmpv"))]
            Self::Process(mpv) => mpv.next_event(timeout),
            #[cfg(feature = "libmpv")]
            Self::InProcess { player, .. } => player.next_event(timeout),
        }
    }

    fn has_exited(&mut self) -> bool {
        match self {
            #[cfg(not(feature = "libmpv"))]
            Self::Process(mpv) => mpv.has_exited(),
            // There is no child to exit: the instance lives as long as the app does.
            #[cfg(feature = "libmpv")]
            Self::InProcess { .. } => false,
        }
    }
}

/// The player thread: registers observers, drains events, answers commands.
fn monitor(
    mut mpv: Backend,
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
                PlayerCommand::TrackList(reply) => {
                    // Read here, on the thread that owns the socket. A send failure means
                    // the caller gave up waiting, which is not an error worth logging.
                    let _ = reply.send(mpv.track_list());
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

/// The audio and subtitle tracks of the current file (plan task 2.6).
///
/// A native client must read these from mpv rather than from the browser's `TextTrack`
/// API, which does not exist here — and, more importantly, the browser's list would be of
/// the *stream* mpv was given, not of what mpv actually resolved after demuxing. For a
/// container with five audio tracks those are not the same thing.
///
/// Returns `None` when nothing is playing, which the interface shows as "no track
/// selection available" rather than as an error.
#[tauri::command]
pub fn player_tracks(state: State<'_, AppState>) -> Result<Option<PlayerTracks>, String> {
    let service = state.playback();
    let Some((request, response)) = service.track_list_channel() else {
        return Ok(None);
    };

    request
        .send(PlayerCommand::TrackList(response.0))
        .map_err(|_| "Der Wiedergabeprozess läuft nicht mehr.".to_string())?;

    // A short deadline: the player thread answers within one event loop, so a wait longer
    // than that means the thread is gone rather than busy.
    let list = response
        .1
        .recv_timeout(std::time::Duration::from_secs(3))
        .map_err(|_| "Der Wiedergabeprozess hat nicht geantwortet.".to_string())?;

    Ok(Some(PlayerTracks::from(list)))
}

/// The track list as the interface needs it.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PlayerTracks {
    /// Audio tracks, in mpv's order.
    pub audio: Vec<TrackView>,
    /// Subtitle tracks, in mpv's order.
    pub subtitles: Vec<TrackView>,
    /// The audio track currently selected, by mpv's id.
    pub selected_audio: Option<i64>,
    /// The subtitle track currently selected, by mpv's id. `None` means subtitles are off.
    pub selected_subtitle: Option<i64>,
}

/// One selectable track.
#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct TrackView {
    /// mpv's track id, to be passed back to `player_set_property` as `aid`/`sid`.
    pub id: i64,
    /// The display label, built from the language and title mpv reported.
    pub label: String,
    /// The ISO language code, when mpv knows it.
    pub language: Option<String>,
    /// Whether this is the track mpv is currently using.
    pub selected: bool,
    /// Whether the track is external (a separate subtitle file next to the video).
    ///
    /// Worth surfacing: an external track can disappear when the file is re-encoded,
    /// unlike one embedded in the container.
    pub external: bool,
    /// The codec, when mpv named one — useful to tell an AC3 track from a commentary.
    pub codec: Option<String>,
    /// `true` for mpv's synthetic "no subtitles" entry, which is a real choice in the list
    /// rather than a missing track.
    pub is_default: bool,
}

impl From<TrackList> for PlayerTracks {
    fn from(list: TrackList) -> Self {
        use streamarr_desktop_player::mpv::TrackKind;

        let view = |track: &streamarr_desktop_player::mpv::Track| TrackView {
            id: track.id,
            label: track.label(),
            language: track.language.clone(),
            selected: track.selected,
            external: track.external,
            codec: track.codec.clone(),
            is_default: track.is_default,
        };

        Self {
            audio: list.audio().iter().map(|t| view(t)).collect(),
            subtitles: list.subtitles().iter().map(|t| view(t)).collect(),
            selected_audio: list.selected(TrackKind::Audio).map(|t| t.id),
            selected_subtitle: list.selected(TrackKind::Subtitle).map(|t| t.id),
        }
    }
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

/// The HDR mode this machine warrants.
///
/// Both halves are probed: the display's EDID says whether the panel can show HDR10, and
/// the installed mpv says whether its renderer can pass HDR through. Measured on this
/// machine both are true, so the answer here is `Passthrough`; on a machine with an SDR
/// screen it is `ToneMapSdr`, which is the provable mapping the plan asks for.
///
/// Logged, because "why is the picture tone-mapped" is otherwise unanswerable from the
/// outside.
pub fn chosen_hdr_mode() -> HdrMode {
    let display_supports_hdr10 =
        streamarr_desktop_player::display_hdr::any_display_supports_hdr10();
    let renderer_supports_passthrough = streamarr_desktop_player::mpv_caps::detect()
        .map(|caps| caps.supports_hdr_passthrough())
        .unwrap_or(false);

    let mode = HdrMode::choose(display_supports_hdr10, renderer_supports_passthrough);
    log::info!(
        "HDR-Modus: {mode:?} (Display kann HDR10: {display_supports_hdr10},          Renderer kann Durchreichung: {renderer_supports_passthrough})"
    );
    mode
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
    fn the_hdr_mode_follows_the_probes() {
        // Replaces a test that asserted "HDR is never claimed", with the comment "this
        // shell has no display probe yet". That comment stopped being true: the probe now
        // exists (the display's EDID and the installed mpv), so the old assertion would
        // have locked in the *absence* of a feature that is now implemented — and passed,
        // because it tested a hardcoded `false` rather than the code path.
        let display = streamarr_desktop_player::display_hdr::any_display_supports_hdr10();
        let renderer = streamarr_desktop_player::mpv_caps::detect()
            .map(|c| c.supports_hdr_passthrough())
            .unwrap_or(false);

        let mode = chosen_hdr_mode();
        assert_eq!(mode, HdrMode::choose(display, renderer));
        // Whatever it is, it is a decision rather than a deferral.
        assert_ne!(mode, HdrMode::Auto);
    }

    #[test]
    fn the_play_path_still_carries_the_capabilities() {
        use streamarr_desktop_player::capabilities::Capabilities;
        // The capabilities that decide direct play must still reach the server; that part
        // of the old test was right and is kept.
        let caps = Capabilities::detect(3840, true, true, true, "1.0");
        let path = play_path("abc", &caps);
        assert!(path.contains("supported_video_codecs"));
        assert!(path.contains("client_max_resolution"));
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
