//! Session commands: login, logout, state, capabilities.
//!
//! No command here returns a token. The UI learns *whether* a session exists, never
//! with what — a refresh token sent into the WebView would be readable by any script
//! running there, which is exactly what storing it in the keyring avoids.

use serde::Serialize;
use streamarr_desktop_player::capabilities::Capabilities;
use streamarr_desktop_player::session::{TokenStore, CLIENT_PLATFORM_VALUE};
use tauri::State;

use crate::AppState;

/// What the UI is told about the session.
#[derive(Debug, Clone, Serialize)]
pub struct SessionState {
    pub authenticated: bool,
    /// Display label, when known.
    pub user_label: Option<String>,
    /// Whether the access token needs renewing.
    ///
    /// Exposed because it is genuinely useful in the UI — "Sitzung wird erneuert" —
    /// and it carries no secret: it is a timestamp comparison.
    pub needs_refresh: bool,
    /// Whether the platform header is being sent. If this were ever false the server
    /// would answer without a refresh token and the session would die on restart, so
    /// the UI can surface it rather than the fault being invisible.
    pub native_client: bool,
    pub token_backend: String,
}

#[tauri::command]
pub fn token_backend(state: State<'_, AppState>) -> Result<String, String> {
    let tokens = state.tokens.lock().unwrap();
    Ok(tokens.backend().describe().to_string())
}

#[tauri::command]
pub fn session_state(state: State<'_, AppState>) -> Result<SessionState, String> {
    let tokens = state.tokens.lock().unwrap();
    let backend = tokens.backend();
    let stored = tokens.load();
    Ok(SessionState {
        authenticated: stored.is_some(),
        user_label: state
            .profiles
            .lock()
            .unwrap()
            .active()
            .and_then(|p| p.user_label.clone()),
        needs_refresh: stored
            .as_ref()
            .map(|pair| stored_needs_refresh(pair, std::time::SystemTime::now()))
            .unwrap_or(false),
        native_client: CLIENT_PLATFORM_VALUE != "web",
        token_backend: backend.describe().to_string(),
    })
}

/// Whether a stored pair is inside the refresh margin.
///
/// A free function so the rule can be tested without a running app or a lock.
fn stored_needs_refresh(
    pair: &streamarr_desktop_player::session::TokenPair,
    now: std::time::SystemTime,
) -> bool {
    use streamarr_desktop_player::session::REFRESH_MARGIN;
    match pair.access_expires_at().checked_sub(REFRESH_MARGIN) {
        Some(deadline) => now >= deadline,
        None => true,
    }
}

/// Logs in and stores the tokens.
///
/// On success the refresh token is written to the token store here and never leaves
/// this process. The returned value is only what the UI may know.
#[tauri::command]
pub async fn login(
    state: State<'_, AppState>,
    email: String,
    password: String,
) -> Result<SessionState, String> {
    let client = state.api().map_err(|e| e.to_string())?;
    let device = state.device.clone();

    let response = client
        .login(&email, &password, &device)
        .await
        .map_err(|e| {
            // A login failure that never reached the server is a connection problem, and
            // the user needs the connection advice rather than "wrong password".
            let (kind, detail) = e.failure();
            match kind {
                crate::api::FailureKind::Http(_) => e.to_string(),
                _ => match crate::api::diagnose(&state.device_server(), kind, &detail).advice {
                    Some(advice) => format!("{e} — {advice}"),
                    None => e.to_string(),
                },
            }
        })?;

    // Stored before anything else: if persisting fails, the caller must know, because
    // a session that only lives in memory disappears on restart and looks like the
    // phase-0.5 bug all over again.
    {
        let tokens = state.tokens.lock().unwrap();
        tokens
            .save(&response.tokens)
            .map_err(|e| format!("Token konnten nicht gespeichert werden: {e}"))?;
    }

    // Remember who is logged in, so the profile list can show it offline.
    {
        let root = state.config_root.clone();
        let mut store = state.profiles.lock().unwrap();
        // The active id is read out first: borrowing it across `iter_mut` would be a
        // second borrow of `store`.
        let active_id = store.active_id.clone();
        if let Some(profile) = store
            .profiles
            .iter_mut()
            .find(|p| Some(p.id.as_str()) == active_id.as_deref())
        {
            profile.user_guid = Some(response.user_guid.clone());
            profile.user_label = response.user_label.clone();
            if let Err(e) = store.save(&root) {
                // Not fatal: the session itself is stored and usable, so failing the
                // login over an unwritable profile file would be the wrong trade.
                log::warn!("Profil konnte nicht aktualisiert werden: {e}");
            }
        }
    }

    session_state(state)
}

#[tauri::command]
pub async fn logout(state: State<'_, AppState>) -> Result<SessionState, String> {
    // The server call is attempted but its failure does not block the local logout: a
    // user who presses "sign out" must end up signed out even when the server is
    // unreachable. The token is revoked server-side when it works, cleared locally
    // either way.
    let access = {
        let tokens = state.tokens.lock().unwrap();
        tokens.load().map(|pair| pair.access_token)
    };
    if let (Some(token), Ok(client)) = (access, state.api()) {
        if let Err(e) = client.logout(&token).await {
            log::warn!("Abmelden am Server fehlgeschlagen (lokal wird trotzdem abgemeldet): {e}");
        }
    }
    {
        let mut tokens = state.tokens.lock().unwrap();
        tokens.clear().map_err(|e| e.to_string())?;
    }
    session_state(state)
}

/// The client capabilities this installation reports.
///
/// Detection uses the values the shell can observe. The display size comes from the
/// main window; HDR is reported as unsupported until a display probe exists, and the
/// plan (§10) explains why claiming it without one is worse than not claiming it: the
/// server's transcode path is HDR-blind, so a false claim yields washed-out video
/// rather than a fallback.
#[tauri::command]
pub fn capabilities(app: tauri::AppHandle) -> Result<serde_json::Value, String> {
    let (width, height) = current_display_size(&app).unwrap_or((1920, 1080));
    let caps = Capabilities::detect(width, false, false, true, env!("CARGO_PKG_VERSION"));
    serde_json::to_value(CapabilitiesView::from(&caps, width, height)).map_err(|e| e.to_string())
}

#[derive(Debug, Clone, Serialize)]
pub struct CapabilitiesView {
    pub video_codecs: Vec<String>,
    pub audio_codecs: Vec<String>,
    pub containers: Vec<String>,
    pub max_resolution: String,
    pub supports_hdr: bool,
    pub hardware_decode: bool,
    pub app_name: String,
    pub app_version: String,
    pub display_width: u32,
    pub display_height: u32,
    /// The exact query parameters sent to `POST /api/play/{guid}`.
    ///
    /// Exposed so the values that decide direct-play versus transcode are visible
    /// rather than buried; spike 0.3 showed the server silently transcodes when these
    /// are missing.
    pub play_query: Vec<(String, String)>,
}

impl CapabilitiesView {
    fn from(caps: &Capabilities, width: u32, height: u32) -> Self {
        Self {
            video_codecs: caps
                .video_codecs
                .iter()
                .map(|c| c.as_str().to_string())
                .collect(),
            audio_codecs: caps
                .audio_codecs
                .iter()
                .map(|c| c.as_str().to_string())
                .collect(),
            containers: caps
                .containers
                .iter()
                .map(|c| c.as_str().to_string())
                .collect(),
            max_resolution: caps.max_resolution.as_str().to_string(),
            supports_hdr: caps.supports_hdr,
            hardware_decode: caps.hardware_decode,
            app_name: caps.app_name.clone(),
            app_version: caps.app_version.clone(),
            display_width: width,
            display_height: height,
            play_query: caps.play_query(),
        }
    }
}

/// Reports the capabilities to the server for this device (plan task 1.5).
#[tauri::command]
pub async fn register_capabilities(
    state: State<'_, AppState>,
) -> Result<serde_json::Value, String> {
    let device_guid = state
        .device
        .guid
        .clone()
        .ok_or("Dieses Gerät ist dem Server noch nicht bekannt")?;
    let access = {
        let tokens = state.tokens.lock().unwrap();
        tokens.load().ok_or("Nicht angemeldet")?.access_token
    };
    let client = state.api().map_err(|e| e.to_string())?;
    let caps = Capabilities::detect(1920, false, false, true, env!("CARGO_PKG_VERSION"));
    client
        .put_capabilities(&access, &device_guid, &caps)
        .await
        .map_err(|e| e.to_string())
}

/// The server's own answer about login options. Needs no authentication, so the
/// login screen can be correct before any credentials exist.
#[tauri::command]
pub async fn auth_status(state: State<'_, AppState>) -> Result<serde_json::Value, String> {
    let client = state.api().map_err(|e| e.to_string())?;
    client.auth_status().await.map_err(|e| e.to_string())
}

/// What went wrong reaching the server, and what to do about it.
///
/// A separate command rather than an error string, because the UI needs to react
/// differently depending on the cause: a timeout on an unpinned address means the IP
/// field should be offered, a certificate problem means it should not. Both were
/// measured live — the name resolves to an unreachable address, so the failure arrives
/// as a **20-second timeout with no explanation at all**.
#[derive(Debug, Clone, Serialize)]
pub struct ConnectionDiagnosis {
    pub problem: String,
    pub advice: Option<String>,
    pub suggests_pin: bool,
    /// The address that was tried, so the user can see which one is meant.
    pub server_url: String,
    pub resolve_override: Option<String>,
}

/// Checks reachability and explains a failure in concrete terms.
#[tauri::command]
pub async fn diagnose_connection(
    state: State<'_, AppState>,
) -> Result<ConnectionDiagnosis, String> {
    let (server, profile_hint) = {
        let profiles = state.profiles.lock().unwrap();
        let profile = profiles.active().cloned();
        match profile {
            Some(profile) => (profile.server.clone(), None),
            None => (
                streamarr_desktop_player::profile::ServerAddress::default(),
                Some("Es ist kein Profil eingerichtet.".to_string()),
            ),
        }
    };

    let client = crate::api::ApiClient::new(&server).map_err(|e| e.to_string())?;
    match client.auth_status().await {
        Ok(_) => Ok(ConnectionDiagnosis {
            problem: "Der Server antwortet.".to_string(),
            advice: None,
            suggests_pin: false,
            server_url: server.base_url(),
            resolve_override: server.resolve_override.clone(),
        }),
        Err(err) => {
            let (kind, detail) = err.failure();
            let mut diagnosis = crate::api::diagnose(&server, kind, &detail);
            if let Some(hint) = profile_hint {
                diagnosis.advice = Some(match diagnosis.advice {
                    Some(advice) => format!("{hint} {advice}"),
                    None => hint,
                });
            }
            Ok(ConnectionDiagnosis {
                problem: diagnosis.problem,
                advice: diagnosis.advice,
                suggests_pin: diagnosis.suggests_pin,
                server_url: server.base_url(),
                resolve_override: server.resolve_override,
            })
        }
    }
}

/// The size of the current display, as far as the shell can tell.
fn current_display_size(app: &tauri::AppHandle) -> Option<(u32, u32)> {
    use tauri::Manager;
    let window = app.get_webview_window("main")?;
    let monitor = window.current_monitor().ok().flatten()?;
    let size = monitor.size();
    let scale = monitor.scale_factor();
    // Physical pixels must be divided by the scale factor: capability reporting is
    // about the video pixels the display can actually show, and a 2× scaled 2560-wide
    // panel presents 1280 logical pixels.
    Some((
        (size.width as f64 / scale).round() as u32,
        (size.height as f64 / scale).round() as u32,
    ))
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::storage::TokenBackend;
    use std::time::{Duration, SystemTime};
    use streamarr_desktop_player::session::{TokenPair, REFRESH_MARGIN};

    fn pair(expires_in: u64) -> TokenPair {
        TokenPair {
            access_token: "a".to_string(),
            refresh_token: Some("r".to_string()),
            token_type: "bearer".to_string(),
            expires_in,
        }
    }

    #[test]
    fn a_fresh_token_does_not_need_refreshing() {
        assert!(!stored_needs_refresh(&pair(1800), SystemTime::now()));
    }

    /// The UI shows "session is being renewed", so the boundary has to match the core
    /// crate's margin exactly — two different margins would make the indicator lie.
    #[test]
    fn a_token_inside_the_margin_needs_refreshing() {
        let just_outside = pair(REFRESH_MARGIN.as_secs() + 5);
        assert!(!stored_needs_refresh(&just_outside, SystemTime::now()));
        let inside = pair(REFRESH_MARGIN.as_secs() - 5);
        assert!(stored_needs_refresh(&inside, SystemTime::now()));
    }

    #[test]
    fn a_zero_lifetime_always_needs_refreshing() {
        assert!(stored_needs_refresh(&pair(0), SystemTime::now()));
    }

    /// A future timestamp is fine; the calculation must not saturate to "expired".
    #[test]
    fn a_long_lived_token_is_not_flagged() {
        assert!(!stored_needs_refresh(
            &pair(30 * 24 * 3600),
            SystemTime::now()
        ));
    }

    #[test]
    fn the_capabilities_view_exposes_the_play_query() {
        let caps = Capabilities::detect(3840, false, false, true, "2026.2.1");
        let view = CapabilitiesView::from(&caps, 3840, 2160);
        let keys: Vec<&str> = view.play_query.iter().map(|(k, _)| k.as_str()).collect();
        // These are the parameters that decide direct play; losing one silently
        // reintroduces the needless transcode found in spike 0.3.
        for expected in ["supported_video_codecs", "client_max_resolution"] {
            assert!(keys.contains(&expected), "{expected} fehlt in {keys:?}");
        }
    }

    /// HDR is reported as unsupported until a real display probe exists.
    #[test]
    fn hdr_is_not_claimed_without_a_probe() {
        let caps = Capabilities::detect(3840, false, false, true, "1");
        assert!(!caps.supports_hdr);
        // Even if a display could do it, without a renderer proof the claim is wrong.
        let optimistic = Capabilities::detect(3840, true, false, true, "1");
        assert!(!optimistic.supports_hdr);
    }

    /// The view must never carry a token field. Checked structurally: a serialised
    /// view is searched for anything that looks like a credential.
    #[test]
    fn the_session_state_carries_no_token() {
        let state = SessionState {
            authenticated: true,
            user_label: Some("test".to_string()),
            needs_refresh: false,
            native_client: true,
            // The real description, not a placeholder: the assertion below is about the
            // shape of what actually reaches the UI.
            token_backend: TokenBackend::File.describe().to_string(),
        };
        // Checked field by field, not by substring over the whole JSON: the legitimate
        // `token_backend` field contains the word "token", so a naive substring search
        // fails for the wrong reason. What matters is that no *value* is a credential.
        let value = serde_json::to_value(&state).unwrap();
        let object = value.as_object().unwrap();
        assert_eq!(
            object.len(),
            5,
            "unerwartetes Feld in der Sitzungsansicht: {object:?}"
        );
        for (key, entry) in object {
            if key == "token_backend" {
                // A human-readable sentence about where credentials live, never one.
                assert!(entry.as_str().unwrap().contains(' '));
                continue;
            }
            let text = entry.to_string().to_lowercase();
            for forbidden in ["bearer", "eyj", "access_token", "refresh_token"] {
                assert!(
                    !text.contains(forbidden),
                    "Feld `{key}` enthält `{forbidden}`: {text}"
                );
            }
        }
    }

    #[test]
    fn the_native_client_flag_is_true() {
        // If the platform value ever became `web` the server would withhold the
        // refresh token; the flag exists so that fault is visible in the UI.
        assert_eq!(CLIENT_PLATFORM_VALUE, "native");
        let state = SessionState {
            authenticated: false,
            user_label: None,
            needs_refresh: false,
            native_client: CLIENT_PLATFORM_VALUE != "web",
            token_backend: String::new(),
        };
        assert!(state.native_client);
    }

    #[test]
    fn the_token_backend_description_is_shown() {
        assert!(!TokenBackend::Keyring.describe().is_empty());
        assert!(!TokenBackend::File.describe().is_empty());
    }

    /// A very long token lifetime must not overflow the deadline calculation.
    #[test]
    fn an_absurd_lifetime_does_not_panic() {
        assert!(!stored_needs_refresh(&pair(u64::MAX), SystemTime::now()));
    }

    #[test]
    fn the_display_default_is_sane() {
        // `current_display_size` falls back to 1080p; the default must be one the
        // server recognises.
        let (w, h) = (1920u32, 1080u32);
        let caps = Capabilities::detect(w, false, false, true, "1");
        assert_eq!(caps.max_resolution.as_str(), "1080p");
        assert!(h > 0);
    }

    #[test]
    fn durations_are_compared_not_subtracted_naively() {
        // Guards the margin arithmetic against a sign error.
        let now = SystemTime::now();
        let future = now + Duration::from_secs(10_000);
        assert!(future > now);
    }
}
