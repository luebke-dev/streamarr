//! Streamarr desktop shell.
//!
//! Responsibilities, and — more usefully — the limits of them:
//!
//! * window management (plan tasks 1.1, 1.2)
//! * the IPC commands the web UI may call
//! * persisting profiles, the device identity and tokens
//! * owning the HTTP transport
//!
//! What this crate deliberately does **not** contain is any playback logic. The
//! player core lives in `frontend/src-tauri/player`, is shell-independent and is tested without
//! a GUI (ADR 001). Everything decision-shaped — when a token is refreshed, whether a
//! file direct-plays, what the wire messages look like — is decided there and merely
//! carried out here.

pub mod api;
pub mod commands;
#[cfg(feature = "libmpv")]
pub mod render;
pub mod storage;

use std::sync::Arc;

use tauri::{Manager, WindowEvent};

/// Everything the windows share.
pub struct AppState {
    /// Configuration root: profiles, device identity, mpv.conf.
    pub config_root: std::path::PathBuf,
    /// The HTTP client for the active server, rebuilt when the profile changes.
    pub api: std::sync::Mutex<Option<api::SharedApi>>,
    /// Token storage: keyring where available, otherwise a restricted file.
    pub tokens: std::sync::Mutex<storage::TokenStorage>,
    /// The profile store, kept in memory so the UI can list profiles without I/O.
    pub profiles: std::sync::Mutex<streamarr_desktop_player::profile::ProfileStore>,
    /// The device identity for this installation.
    pub device: streamarr_desktop_player::session::DeviceIdentity,
    /// The one native playback this app runs at a time.
    playback: commands::playback::PlaybackService,
    /// The one browser login this app is awaiting a reply for.
    deeplinks: commands::deeplink::DeepLinkService,
    /// The one game stream this app runs at a time.
    games: commands::game::GameService,
}

impl AppState {
    /// The playback service, for the player commands.
    pub fn playback(&self) -> &commands::playback::PlaybackService {
        &self.playback
    }

    /// The game service, for the game commands.
    pub fn games(&self) -> &commands::game::GameService {
        &self.games
    }

    /// The configured address pin for the active profile, if any.
    ///
    /// Read here so the game thread gets it without touching the profile store
    /// from another thread — the store is behind a mutex the UI also uses.
    pub fn resolve_pin(&self) -> Option<String> {
        let profiles = self.profiles.lock().ok()?;
        let active = profiles.active()?;
        active.server.resolve_override.clone()
    }

    /// The deep-link service, for browser logins.
    pub fn deeplinks(&self) -> &commands::deeplink::DeepLinkService {
        &self.deeplinks
    }

    fn load(config_root: std::path::PathBuf) -> Result<Self, String> {
        // Logged first, before anything that can be slow or fail. This line is the
        // evidence that startup reached its own code — the package smoke test in CI
        // greps for it — so it must not sit behind a keyring lookup or a device
        // identity that might block. What it says is true at that moment: where the
        // configuration lives. Where tokens end up is logged once that is known.
        log::info!("Konfiguration: {}", config_root.display());
        // A fresh installation gets one profile, written to disk immediately, so the
        // login screen has a server to talk to and the user can see and edit the
        // address from the first launch. Without this the app starts with no profile
        // and every command fails with "kein Profil eingerichtet" — which is exactly
        // what happened on the first run of this shell.
        if let Err(e) = storage::seed_default_profile(&config_root) {
            log::error!("Standardprofil konnte nicht angelegt werden: {e}");
        }
        let profiles = storage::load_profiles(&config_root).unwrap_or_default();
        let device = storage::device_identity(&config_root, env!("CARGO_PKG_VERSION"), "Desktop")?;
        let tokens = storage::TokenStorage::open(&config_root);
        log::info!("Token-Ablage: {}", tokens.backend().describe());
        Ok(Self {
            config_root,
            api: std::sync::Mutex::new(None),
            tokens: std::sync::Mutex::new(tokens),
            profiles: std::sync::Mutex::new(profiles),
            device,
            playback: commands::playback::PlaybackService::new(),
            deeplinks: commands::deeplink::DeepLinkService::new(),
            games: commands::game::GameService::new(),
        })
    }

    /// Returns the API client, building it for the active profile if needed.
    pub fn api(&self) -> Result<api::SharedApi, api::ApiError> {
        let mut guard = self.api.lock().unwrap();
        if let Some(client) = guard.as_ref() {
            return Ok(client.clone());
        }
        let profiles = self.profiles.lock().unwrap();
        let profile = profiles
            .active()
            .ok_or_else(|| api::ApiError::BadAddress("Kein Profil eingerichtet".to_string()))?;
        let client = Arc::new(api::ApiClient::new(&profile.server)?);
        *guard = Some(client.clone());
        Ok(client)
    }

    /// The active profile's server address, or the default when none is set.
    ///
    /// Used for diagnostics, which must work even before a profile exists.
    pub fn device_server(&self) -> streamarr_desktop_player::profile::ServerAddress {
        self.profiles
            .lock()
            .unwrap()
            .active()
            .map(|profile| profile.server.clone())
            .unwrap_or_default()
    }

    /// Drops the cached client so the next call uses the changed address.
    /// The app's own version, as the bundle carries it.
    ///
    /// Read from Tauri rather than from a constant, so a support report cannot
    /// claim a version the build does not have.
    pub fn app_version(&self) -> String {
        // `env!("CARGO_PKG_VERSION")` is the shell crate's version, which is kept
        // in step with the product version by `frontend/src-tauri/scripts/check_versions.sh`.
        env!("CARGO_PKG_VERSION").to_string()
    }

    /// Where the player writes its logs, when the session has such a place.
    ///
    /// `XDG_RUNTIME_DIR` is where mpv's log files go; without it there is no
    /// directory to read, which is reported rather than invented.
    pub fn player_log_dir(&self) -> Option<std::path::PathBuf> {
        let runtime = std::env::var_os("XDG_RUNTIME_DIR")?;
        Some(std::path::PathBuf::from(runtime))
    }

    pub fn invalidate_api(&self) {
        *self.api.lock().unwrap() = None;
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
/// The libmpv instance, created before GTK and handed to whichever thread plays.
///
/// `None` in builds without the `libmpv` feature, and still `Some` only until playback takes
/// ownership — the handle is not shareable across two owners by design.
#[cfg(feature = "libmpv")]
pub static EARLY_LIBMPV: std::sync::OnceLock<
    std::sync::Arc<streamarr_desktop_player::libmpv::Libmpv>,
> = std::sync::OnceLock::new();

pub fn run() {
    // libmpv must be created before GTK is initialised: after `gtk_init` the same call returns
    // NULL (measured, see ADR 003). This is the only place in the app where that order can be
    // guaranteed, so the handle is made here and handed on.
    #[cfg(feature = "libmpv")]
    match streamarr_desktop_player::libmpv::Libmpv::create() {
        Ok(mpv) => {
            // Stored once and shared afterwards: consuming it here is what made a second
            // playback fail with no handle left.
            let _ = EARLY_LIBMPV.set(std::sync::Arc::new(mpv));
        }
        Err(err) => log::error!("libmpv nicht anlegbar: {err}"),
    }

    let mut builder = tauri::Builder::default();

    // Single instance first: the plugin must see the command line before anything
    // else acts on it. A second launch would otherwise register the device a second
    // time and race the first instance for the token store.
    builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
        if let Some(window) = app.get_webview_window("main") {
            let _ = window.set_focus();
            let _ = window.unminimize();
        }
    }));

    builder
        .plugin(
            // Logging first, so everything after it is actually recorded. The file is
            // kept in the app config directory; `targets` is explicit rather than a
            // catch-all so a future noisy dependency cannot flood the log.
            tauri_plugin_log::Builder::new()
                .targets([
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::Stdout),
                    tauri_plugin_log::Target::new(tauri_plugin_log::TargetKind::LogDir {
                        file_name: Some("streamarr-desktop".to_string()),
                    }),
                ])
                .level(log::LevelFilter::Info)
                .build(),
        )
        .plugin(tauri_plugin_opener::init())
        // Deep links last before setup: the scheme must be registered before a link can
        // arrive, and `setup` below reads the link that may have started this process.
        .plugin(tauri_plugin_deep_link::init())
        .plugin(tauri_plugin_updater::Builder::new().build())
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            let config_root = app
                .path()
                .app_config_dir()
                .unwrap_or_else(|_| storage::default_config_root());
            let state = AppState::load(config_root)?;
            app.manage(state);

            // Diagnostic, off unless asked for: plays a generated source through the production
            // modules so the frame rate comes from shipping code rather than from the spike.
            #[cfg(feature = "libmpv")]
            if std::env::var("STREAMARR_NATIVE_CHECK").ok().as_deref() == Some("1") {
                if let Some(window) = app.get_webview_window("main") {
                    let app_handle = app.handle().clone();
                    let size = window
                        .inner_size()
                        .map(|s| (s.width, s.height))
                        .unwrap_or((0, 0));
                    std::thread::spawn(move || {
                        std::thread::sleep(std::time::Duration::from_millis(2500));
                        match render::native_check(&window, size, &app_handle) {
                            Ok(info) => log::info!("NATIVPRUEFUNG {info}"),
                            Err(err) => log::error!("NATIVPRUEFUNG fehlgeschlagen: {err}"),
                        }
                    });
                }
            }
            // Couch mode's own state. Separate from `AppState` because it is
            // per-window session state rather than configuration: it holds the
            // focus and the repeat timers, both of which must start empty.
            app.manage(commands::couch::CouchMode::default());

            // Deep links: registers the `streamarr://` scheme with the desktop, and
            // installs the listener. Both are needed, and forgetting to call this at all
            // is exactly the kind of mistake that shows up only as "the browser login
            // never comes back" — the function existed and compiled, but nothing invoked
            // it, so the scheme was never registered.
            if let Err(e) = commands::deeplink::install(app.handle()) {
                log::warn!("Deep-Link-Einrichtung fehlgeschlagen: {e}");
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            // The window-state plugin persists geometry on exit; this only covers the
            // case of the main window being closed, which must end the app rather than
            // leave a process running with no visible window.
            if let WindowEvent::CloseRequested { .. } = event {
                if window.label() == "main" {
                    log::info!("Hauptfenster geschlossen — App wird beendet");
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            commands::profiles::list_profiles,
            commands::profiles::active_profile,
            commands::profiles::save_profile,
            commands::profiles::set_active_profile,
            commands::profiles::delete_profile,
            commands::profiles::profile_paths,
            commands::profiles::server_info,
            commands::session::login,
            commands::session::logout,
            commands::session::session_state,
            commands::session::capabilities,
            commands::session::token_backend,
            commands::session::register_capabilities,
            commands::session::auth_status,
            commands::session::diagnose_connection,
            commands::bridge::api_request,
            commands::bridge::frontend_log,
            commands::bridge::store_tokens,
            commands::bridge::stored_access_token,
            commands::bridge::forget_tokens,
            commands::playback::play_media,
            commands::playback::player_state,
            commands::playback::player_status,
            commands::playback::player_set_paused,
            commands::playback::player_seek,
            commands::playback::player_set_property,
            commands::playback::player_stop,
            commands::playback::player_tracks,
            commands::deeplink::begin_browser_login,
            commands::deeplink::browser_login_pending,
            commands::deeplink::cancel_browser_login,
            commands::update::check_for_update,
            commands::report::report_problem,
            commands::report::report_preview,
            commands::game::game_start,
            commands::game::game_state,
            commands::game::game_input,
            commands::game::game_pad_input,
            commands::game::game_stats,
            commands::game::game_resize,
            commands::game::game_stop,
            commands::couch::set_couch_mode,
            commands::couch::couch_state,
            commands::couch::set_couch_layout,
            commands::couch::couch_move,
            commands::couch::couch_intent,
            commands::couch::couch_repeat_info,
            commands::couch::couch_pad_input,
            commands::couch::couch_pads,
            commands::couch::couch_set_fullscreen,
        ])
        .run(tauri::generate_context!())
        .expect("error while running streamarr.media desktop app");
}
