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
//! player core lives in `desktop/player`, is shell-independent and is tested without
//! a GUI (ADR 001). Everything decision-shaped — when a token is refreshed, whether a
//! file direct-plays, what the wire messages look like — is decided there and merely
//! carried out here.

pub mod api;
pub mod commands;
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
}

impl AppState {
    fn load(config_root: std::path::PathBuf) -> Result<Self, String> {
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
        log::info!(
            "Konfiguration: {} — Token-Ablage: {}",
            config_root.display(),
            tokens.backend().describe()
        );
        Ok(Self {
            config_root,
            api: std::sync::Mutex::new(None),
            tokens: std::sync::Mutex::new(tokens),
            profiles: std::sync::Mutex::new(profiles),
            device,
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
    pub fn invalidate_api(&self) {
        *self.api.lock().unwrap() = None;
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
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
        .plugin(tauri_plugin_window_state::Builder::default().build())
        .setup(|app| {
            let config_root = app
                .path()
                .app_config_dir()
                .unwrap_or_else(|_| storage::default_config_root());
            let state = AppState::load(config_root)?;
            app.manage(state);
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
        ])
        .run(tauri::generate_context!())
        .expect("error while running streamarr.media desktop app");
}
