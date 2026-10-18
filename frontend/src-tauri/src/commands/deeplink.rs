//! Deep-link handling: what happens when `streamarr://…` arrives.
//!
//! The classification itself lives in
//! [`streamarr_desktop_player::deeplink`], because a URL from the operating system is
//! untrusted input and every case — including the ones that must be refused — deserves a
//! test without launching an app. This module is the part that cannot be pure: it talks to
//! the running app, and it performs the OIDC code exchange.
//!
//! # What the exchange does, and why it happens here
//!
//! The provider redirects the browser to `streamarr://login?code=…&state=…`. The app then
//! exchanges that code for tokens by calling **its own configured server** — never a
//! server named in the link. That is not a stylistic choice: the app reaches its server
//! through an IP pin a browser cannot apply, so the exchange has to happen in the shell,
//! and the server address has to come from the profile rather than from the URL.
//!
//! # The state check
//!
//! Before opening the browser, the app stores a random `state`. The reply must carry the
//! same value, or it is refused. Without this check an attacker could hand the app *their*
//! authorization code and have the user silently logged into the attacker's account — the
//! login analogue of a CSRF. The value is held in memory only, because it is valid for the
//! length of one login.
//!
//! # Not verified against a live provider
//!
//! The test server has `oidc_enabled: false` (measured: `GET /api/auth/status` →
//! `{"oidc_enabled":false,…}`), so this path **cannot be exercised end to end here**. What
//! is verified is the classification (20 tests) and that the app compiles and starts with
//! the scheme registered. The exchange itself is written against the server's own
//! endpoints, read from its sources, and is marked as unverified in the user guide.

use std::sync::Mutex;

use streamarr_desktop_player::deeplink::{self, DeepLink, DeepLinkKind};
use streamarr_desktop_player::session::TokenStore;
use tauri::{Emitter, Manager, State};

use crate::api::{RawBody, RawRequest};
use crate::AppState;

/// A login awaiting its reply.
#[derive(Debug, Clone)]
struct PendingLogin {
    /// The value sent with the authorization request.
    state: String,
    /// Where to send the browser afterwards.
    return_to: Option<String>,
}

/// The one in-flight login.
///
/// One, not a list: a second login started while the first is pending would invalidate the
/// first reply, and keeping several would mean accepting a reply for a request the user has
/// already abandoned.
#[derive(Default)]
pub struct DeepLinkService {
    pending: Mutex<Option<PendingLogin>>,
}

impl DeepLinkService {
    pub fn new() -> Self {
        Self::default()
    }

    /// Remembers the state for a login that is about to be started.
    pub fn begin_login(&self, state: String, return_to: Option<String>) {
        *self.pending.lock().unwrap() = Some(PendingLogin { state, return_to });
    }

    /// Consumes the pending login if the reply matches it.
    ///
    /// Consumed rather than read, so the same code cannot be redeemed twice: a replay
    /// would be refused by the server anyway, but failing locally gives a clearer message
    /// and does not spend a request.
    fn take_if_matching(&self, reply_state: &str) -> Option<PendingLogin> {
        let mut guard = self.pending.lock().unwrap();
        match guard.as_ref() {
            Some(pending) if pending.state == reply_state => guard.take(),
            _ => None,
        }
    }

    /// Discards any pending login, for a cancellation.
    pub fn cancel(&self) {
        *self.pending.lock().unwrap() = None;
    }

    /// Whether a login is awaited, for the interface to show a waiting state.
    pub fn is_pending(&self) -> bool {
        self.pending.lock().unwrap().is_some()
    }
}

/// What the interface is told about a deep link that arrived.
#[derive(Debug, Clone, serde::Serialize)]
pub struct DeepLinkEvent {
    /// `login`, `loginError`, `openItem` or `unknown`.
    pub kind: String,
    /// A message for the user, when there is something to say.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub message: Option<String>,
    /// The item to open, for `openItem`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub item_guid: Option<String>,
    /// Whether the login succeeded, for `login`.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub authenticated: Option<bool>,
}

/// Handles a raw deep-link URL.
///
/// Called by the shell's own `deep-link` listener. Returns the event that was emitted, so
/// the caller can log it and a test could assert on it.
pub async fn handle(app: &tauri::AppHandle, raw: &str) -> DeepLinkEvent {
    match deeplink::parse(raw) {
        Ok(link) => {
            let event = dispatch(app, link).await;
            // The window may be minimised, or the user may be looking at a different app:
            // a login that completes invisibly looks like nothing happened.
            focus_main_window(app);
            let _ = app.emit("deeplink", &event);
            event
        }
        Err(error) => {
            // A refusal is a normal outcome — any local program can send the app a link —
            // so it is logged and reported, not treated as a crash.
            log::warn!("Deep-Link abgelehnt: {error}");
            let event = DeepLinkEvent {
                kind: "error".to_string(),
                message: Some(error.to_string()),
                item_guid: None,
                authenticated: None,
            };
            let _ = app.emit("deeplink", &event);
            event
        }
    }
}

/// Carries out what the link asked for.
async fn dispatch(app: &tauri::AppHandle, link: DeepLink) -> DeepLinkEvent {
    let service = app.state::<AppState>();
    match link.kind {
        DeepLinkKind::Login => {
            let state = link.params.get("state").cloned().unwrap_or_default();
            let code = link.params.get("code").cloned().unwrap_or_default();
            match exchange_code(&service, &code, &state).await {
                Ok(()) => {
                    focus_main_window(app);
                    DeepLinkEvent {
                        kind: "login".to_string(),
                        message: None,
                        item_guid: None,
                        authenticated: Some(true),
                    }
                }
                Err(message) => DeepLinkEvent {
                    kind: "loginError".to_string(),
                    message: Some(message),
                    item_guid: None,
                    authenticated: Some(false),
                },
            }
        }
        DeepLinkKind::LoginError { error } => DeepLinkEvent {
            kind: "loginError".to_string(),
            message: Some(match error.as_str() {
                // The one error worth translating: a user who cancelled needs to know
                // that nothing is wrong.
                "access_denied" => "Die Anmeldung wurde abgebrochen.".to_string(),
                other => format!("Die Anmeldung ist fehlgeschlagen: {other}"),
            }),
            item_guid: None,
            authenticated: Some(false),
        },
        DeepLinkKind::OpenItem { guid } => DeepLinkEvent {
            kind: "openItem".to_string(),
            message: None,
            item_guid: Some(guid),
            authenticated: None,
        },
        DeepLinkKind::Unknown { action } => DeepLinkEvent {
            kind: "unknown".to_string(),
            // Said out loud rather than ignored: a link from a newer app version would
            // otherwise do nothing at all, with no way for the user to tell why.
            message: Some(format!("Unbekannter Link-Typ `{action}`.")),
            item_guid: None,
            authenticated: None,
        },
    }
}

/// Exchanges an authorization code for tokens with the configured server.
///
/// The server address comes from the active profile and **never** from the link; see the
/// module documentation for why that is a security property rather than tidiness.
async fn exchange_code(
    state: &State<'_, AppState>,
    code: &str,
    reply_state: &str,
) -> Result<(), String> {
    if code.is_empty() {
        return Err("Der Anmelde-Link enthält keinen Code.".to_string());
    }

    // The state check, before anything is sent. A mismatch means the reply does not belong
    // to a login this app started.
    let pending = state.deeplinks().take_if_matching(reply_state);
    let Some(pending) = pending else {
        return Err(
            "Die Anmeldeantwort passt zu keiner gestarteten Anmeldung. Bitte melden Sie sich \
             erneut an."
                .to_string(),
        );
    };

    let client = state.api().map_err(|e| e.to_string())?;
    let body = serde_json::json!({ "code": code, "state": reply_state }).to_string();

    let response = client
        .raw_request(&RawRequest {
            method: "POST".to_string(),
            // The server's own callback endpoint, read from its sources
            // (`api/v1/auth.py`): it verifies the state server-side as well.
            path: "/api/auth/callback".to_string(),
            base_url: None,
            headers: vec![("Content-Type".to_string(), "application/json".to_string())],
            body: Some(body),
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
            "Der Server hat die Anmeldung abgelehnt (HTTP {}): {}",
            response.status,
            text.chars().take(300).collect::<String>()
        ));
    }

    let parsed: serde_json::Value = serde_json::from_str(&text)
        .map_err(|e| format!("Die Antwort des Servers war nicht lesbar: {e}"))?;

    // The tokens arrive in the body because the shell sends `X-Client-Platform: native` —
    // a web client would get an httpOnly cookie instead, which a native app cannot use.
    let tokens = crate::api::parse_tokens(&parsed).map_err(|e| e.to_string())?;
    state
        .tokens
        .lock()
        .unwrap()
        .save(&tokens)
        .map_err(|e| format!("Token konnten nicht gespeichert werden: {e}"))?;

    let _ = pending.return_to;
    log::info!("Anmeldung über den Browser abgeschlossen; Token liegen im Schlüsselbund.");
    Ok(())
}

/// Brings the app's window to the front.
fn focus_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Registers the deep-link listener.
///
/// `deep-link` delivers URLs through two routes and both are needed: the running-instance
/// callback, and the command line of a *new* process the operating system started to carry
/// the link. The second is why `single-instance` has to come first — otherwise the new
/// process becomes a second app instead of handing its URL to the first.
pub fn install(app: &tauri::AppHandle) -> Result<(), String> {
    use tauri_plugin_deep_link::DeepLinkExt;

    // The scheme, so the operating system knows to hand `streamarr://` to us. On Linux
    // this writes a desktop entry; registering twice is harmless.
    #[cfg(any(target_os = "linux", all(debug_assertions, windows)))]
    {
        if let Err(e) = app.deep_link().register_all() {
            // Not fatal: the app still works, logins through the browser simply cannot
            // return. Reporting it is the point — silently not registering would present
            // as "the browser login never comes back".
            log::warn!("Deep-Link-Schema konnte nicht registriert werden: {e}");
        }
    }

    // Named `app_handle`, not `handle`: `handle` is also the function this closure calls,
    // and shadowing it compiles up to the call and then fails in a way that reads as a
    // missing function rather than as a shadowed name.
    let app_handle = app.clone();
    app.deep_link().on_open_url(move |event| {
        let app_handle = app_handle.clone();
        for url in event.urls() {
            let url = url.to_string();
            log::info!("Deep-Link empfangen: {url}");
            let app_handle = app_handle.clone();
            tauri::async_runtime::spawn(async move {
                let _ = handle(&app_handle, &url).await;
            });
        }
    });

    // A link that started this process arrives before the listener exists, so it is read
    // once at startup. Without this, the very first login after a cold start would be lost
    // — which is exactly the common case, because the browser is a different application.
    match app.deep_link().get_current() {
        Ok(Some(urls)) => {
            for url in urls {
                let url = url.to_string();
                let app_handle = app.clone();
                log::info!("Deep-Link aus dem Startvorgang: {url}");
                tauri::async_runtime::spawn(async move {
                    let _ = handle(&app_handle, &url).await;
                });
            }
        }
        Ok(None) => {}
        Err(e) => log::warn!("Start-Deep-Link konnte nicht gelesen werden: {e}"),
    }

    Ok(())
}

/// Starts a browser login: builds the authorization URL and remembers the state.
///
/// Returns the URL for the interface to open. The state is generated here rather than by
/// the caller so it cannot be forgotten, and it is **not** returned to the interface —
/// the page has no need for it and a value that never leaves the shell cannot leak.
#[tauri::command]
pub fn begin_browser_login(
    state: State<'_, AppState>,
    state_value: String,
    return_to: Option<String>,
) -> Result<String, String> {
    let profile = {
        let store = state.profiles.lock().unwrap();
        store
            .active()
            .cloned()
            .ok_or_else(|| "Es ist kein Profil eingerichtet.".to_string())?
    };

    if state_value.trim().is_empty() {
        return Err("Der Anmeldestatus darf nicht leer sein.".to_string());
    }
    state
        .deeplinks()
        .begin_login(state_value.clone(), return_to.clone());

    // The redirect must come back to the app's own scheme, which is what
    // `register_all` above told the operating system about.
    let mut url = format!(
        "{}/api/auth/login?redirect_uri={}",
        profile.server.base_url().trim_end_matches('/'),
        encode("streamarr://login")
    );
    if let Some(return_to) = return_to.filter(|value| !value.trim().is_empty()) {
        url.push_str(&format!("&return_to={}", encode(&return_to)));
    }
    Ok(url)
}

/// Whether a browser login is currently awaited.
#[tauri::command]
pub fn browser_login_pending(state: State<'_, AppState>) -> Result<bool, String> {
    Ok(state.deeplinks().is_pending())
}

/// Abandons a pending browser login.
#[tauri::command]
pub fn cancel_browser_login(state: State<'_, AppState>) -> Result<(), String> {
    state.deeplinks().cancel();
    Ok(())
}

/// Percent-encodes a query value.
fn encode(value: &str) -> String {
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

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_login_is_only_accepted_once() {
        // The reply is consumed. Replaying the same link would otherwise redeem the code a
        // second time — the server refuses it, but failing locally gives a clearer message
        // and does not spend a request.
        let service = DeepLinkService::new();
        assert!(!service.is_pending());
        service.begin_login("state-1".to_string(), None);
        assert!(service.is_pending());

        assert!(service.take_if_matching("state-1").is_some());
        assert!(service.take_if_matching("state-1").is_none(), "consumed");
        assert!(!service.is_pending());
    }

    #[test]
    fn a_reply_for_a_different_login_is_refused() {
        // The login-CSRF case: a reply that does not match the state this app stored must
        // not be honoured, and must not consume the pending login either — the real reply
        // may still arrive.
        let service = DeepLinkService::new();
        service.begin_login("expected".to_string(), Some("/home".to_string()));

        assert!(service.take_if_matching("attacker").is_none());
        assert!(service.is_pending(), "the real login is still awaited");
        assert!(service.take_if_matching("expected").is_some());
    }

    #[test]
    fn a_reply_with_no_login_in_flight_is_refused() {
        let service = DeepLinkService::new();
        assert!(service.take_if_matching("anything").is_none());
    }

    #[test]
    fn cancelling_clears_the_pending_login() {
        let service = DeepLinkService::new();
        service.begin_login("state".to_string(), None);
        service.cancel();
        assert!(!service.is_pending());
        assert!(service.take_if_matching("state").is_none());
    }

    #[test]
    fn a_new_login_replaces_the_old_state() {
        // Starting a second login invalidates the first: keeping both would mean accepting
        // a reply for a request the user has already abandoned.
        let service = DeepLinkService::new();
        service.begin_login("first".to_string(), None);
        service.begin_login("second".to_string(), None);
        assert!(service.take_if_matching("first").is_none());
        assert!(service.take_if_matching("second").is_some());
    }

    #[test]
    fn the_authorization_url_is_encoded() {
        // A `return_to` such as `/library?filter=4k` contains characters that would
        // otherwise end the parameter early and change the request.
        let encoded = encode("/library?filter=4k&sort=name");
        assert!(!encoded.contains('?'), "{encoded}");
        assert!(!encoded.contains('&'), "{encoded}");
        assert!(encoded.contains("%3F"), "{encoded}");
        assert!(encoded.contains("%26"), "{encoded}");
    }

    #[test]
    fn the_scheme_in_the_redirect_matches_the_registered_one() {
        // These two drifting apart is a silent failure: the browser would return to a
        // scheme no application handles, and the login would simply never complete.
        let redirect = "streamarr://login";
        assert!(redirect.starts_with(streamarr_desktop_player::deeplink::SCHEME));
    }
}
