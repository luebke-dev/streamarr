//! The WebView's transport: authenticated HTTP, executed by the shell.
//!
//! This is the piece that makes the embedded web interface work at all, and the reason
//! is worth stating plainly. The interface is a browser application: it builds URLs
//! itself and calls the API with axios. On the web that is fine. Here it cannot work,
//! for two measured reasons:
//!
//! 1. **The webview cannot reach the server.** `streamarr.luebke.internal` resolves to
//!    an address that does not answer, so every request hung for 20 seconds. The app
//!    works around that with an IP pin, which the *shell* holds — the page has no way
//!    to apply it. Entering the IP directly instead is not an option either: the
//!    certificate covers `*.luebke.internal` only, so TLS fails (verified).
//! 2. **Two places holding credentials is two places to get it wrong.** The page keeps
//!    tokens in `localStorage`, where any script on the page can read them, and the
//!    shell keeps them in the OS keyring. Whichever wins, the other is a stale copy.
//!
//! So the requests are executed by the shell, which owns the address, the pin and the
//! credentials, and the page receives only what it asked for. The interface itself is
//! untouched: it still calls `fetch`, and this handler answers.
//!
//! # What this is not
//!
//! It is not a general-purpose proxy. The base URL is fixed to the active profile and a
//! page that asks for a different host is refused, so a compromised page cannot use the
//! app's credentials against someone else's server. Tokens are injected here and never
//! returned to the page.

use serde::Serialize;
use streamarr_desktop_player::session::TokenStore;
use tauri::State;

use crate::AppState;

/// A reply to the page, shaped like a `fetch` response.
#[derive(Debug, Clone, Serialize)]
pub struct BridgeResponse {
    pub status: u16,
    pub status_text: String,
    /// Headers as pairs, because a `Map` loses duplicates such as `Set-Cookie`.
    pub headers: Vec<(String, String)>,
    /// Present for textual bodies.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body: Option<String>,
    /// Present for binary bodies, base64-encoded.
    #[serde(skip_serializing_if = "Option::is_none")]
    pub body_base64: Option<String>,
}

impl BridgeResponse {
    /// A failure the page can display, in the shape of a response.
    ///
    /// Reported as HTTP 503 with a JSON body rather than as a thrown error, so the
    /// page's existing error handling treats it like any other server problem — and so
    /// the diagnosis reaches the user in a place the UI already renders. Status 0 would
    /// be more honest about "no response", but browsers and axios handle it
    /// inconsistently, and an unusable error path is worse than a slightly imprecise
    /// status.
    pub fn unreachable(problem: &str, advice: Option<&str>) -> Self {
        let detail = match advice {
            Some(advice) => format!("{problem} {advice}"),
            None => problem.to_string(),
        };
        let body = serde_json::json!({ "detail": detail }).to_string();
        Self {
            status: 503,
            status_text: "Service Unavailable".to_string(),
            headers: vec![("content-type".to_string(), "application/json".to_string())],
            body: Some(body),
            body_base64: None,
        }
    }
}

/// Executes an API request for the WebView.
///
/// `path` is a path, never a full URL from the page's choosing: the origin comes from the
/// active profile. That is what lets the pin work for the embedded UI, and what stops the
/// page from pointing the app's credentials at another host.
#[tauri::command]
pub async fn api_request(
    state: State<'_, AppState>,
    method: String,
    path: String,
    headers: Option<Vec<(String, String)>>,
    body: Option<String>,
    timeout_ms: Option<u64>,
) -> Result<BridgeResponse, String> {
    let client = match state.api() {
        Ok(client) => client,
        Err(err) => {
            // No profile or a broken address: answer in the shape the page expects
            // rather than throwing, so it can show the message.
            let server = state.device_server();
            let (kind, detail) = err.failure();
            let diagnosis = crate::api::diagnose(&server, kind, &detail);
            // Logged, not just returned. This module had **no logging at all**, and
            // that is why a failure in the running app was undiagnosable: the page
            // showed a message, the shell's own log was silent, and there was no
            // way to tell a missing profile from an unreachable server. The method
            // and path are included because "which request failed" is the first
            // question, and the token is not — it never appears in a log line.
            log::warn!("API nicht erreichbar für {method} {path}: {kind:?}");
            return Ok(BridgeResponse::unreachable(
                &diagnosis.problem,
                diagnosis.advice.as_deref(),
            ));
        }
    };

    // Credentials are attached here and never handed to the page.
    let mut headers = headers.unwrap_or_default();

    // The refresh endpoint authenticates with the **refresh** token, not the access
    // token. The server's `verify_refresh_token` reads the httpOnly cookie or the
    // `Authorization` header, and a desktop client has no cookie — so the header is the
    // only way. Attaching the access token, which the generic branch below does, is why a
    // restart could not restore a session: the server answered `400`, the page reported
    // "Token refresh failed", and the user was back at the login form with a perfectly
    // good refresh token in the keyring.
    //
    // Matched on the path rather than on the method, because the shell is the only place
    // that knows which credential belongs to which endpoint — and it owns both.
    let refresh_path = is_refresh_path(&path);
    if refresh_path {
        if let Some(refresh) = current_refresh_token(&state)? {
            headers.push(("Authorization".to_string(), format!("Bearer {refresh}")));
        }
        // No refresh token: the branch below runs instead, so the server's own answer
        // (rather than a local guess) is what the page reports.
    }

    let already_authorised = headers
        .iter()
        .any(|(name, _)| name.eq_ignore_ascii_case("authorization"));
    if !already_authorised {
        if let Some(token) = current_access_token(&state)? {
            headers.push(("Authorization".to_string(), format!("Bearer {token}")));
        }
    }

    let request = crate::api::RawRequest {
        method,
        path,
        base_url: None,
        headers,
        body,
        timeout_ms,
    };

    match client.raw_request(&request).await {
        Ok(response) => {
            // Matched once: `response.body` cannot be read twice.
            let (body, body_base64) = match response.body {
                crate::api::RawBody::Text(text) => (Some(text), None),
                crate::api::RawBody::Empty => (Some(String::new()), None),
                crate::api::RawBody::Base64(data) => (None, Some(data)),
            };
            Ok(BridgeResponse {
                status: response.status,
                status_text: response.status_text,
                headers: response.headers,
                body,
                body_base64,
            })
        }
        Err(err) => {
            // A transport failure becomes a diagnosable response, so the page shows the
            // same concrete advice the app's own commands do.
            let server = state.device_server();
            let (kind, detail) = err.failure();
            let diagnosis = crate::api::diagnose(&server, kind, &detail);
            // The detail, not just the kind: the whole point of classifying the
            // error is that the *specific* reason reaches someone who can act on
            // it, and the page's message is written for a user, not a maintainer.
            log::warn!(
                "Transportfehler bei {} {}: {kind:?} — {detail}",
                request.method,
                request.path
            );
            Ok(BridgeResponse::unreachable(
                &diagnosis.problem,
                diagnosis.advice.as_deref(),
            ))
        }
    }
}

/// The stored access token, if there is one.
pub(crate) fn current_access_token_for_report(state: &AppState) -> Result<Option<String>, String> {
    // Same rule as every other command: the token is read here and never handed
    // to the page.
    current_access_token(state)
}

fn current_access_token(state: &AppState) -> Result<Option<String>, String> {
    let tokens = state.tokens.lock().unwrap();
    Ok(tokens.load().map(|pair| pair.access_token))
}

/// The long-lived token, which only the refresh endpoint may be given.
///
/// Kept apart from [`current_access_token`] deliberately: sending the refresh token to
/// every endpoint would hand a seven-day credential to requests that need a fifteen-minute
/// one, which is the same mistake as storing it in the page.
fn current_refresh_token(state: &AppState) -> Result<Option<String>, String> {
    let tokens = state.tokens.lock().unwrap();
    Ok(tokens.load().and_then(|pair| pair.refresh_token))
}

/// Whether a path authenticates with the refresh token rather than the access token.
///
/// The shell owns both credentials, so it is the only layer that can make this decision —
/// and getting it wrong is invisible from the page: a `400` from the refresh endpoint
/// looks like an expired session, and the user is shown the login form while holding a
/// perfectly good refresh token.
fn is_refresh_path(path: &str) -> bool {
    // The query and the fragment are stripped first: matching on a bare prefix would also
    // catch `/api/auth/refreshless` and hand *that* the seven-day token. My own test
    // found this — the assertion for `refreshless` failed on the first version.
    let without_query = path.split(['?', '#']).next().unwrap_or("");
    without_query.trim_end_matches('/') == "/api/auth/refresh"
}

/// Stores the token pair the page obtained by logging in.
///
/// The page performs the login itself (it renders the form and knows the credentials),
/// but the tokens must not stay in its `localStorage` — that is where a cross-site
/// scripting bug reads them from. So the page hands them straight here and keeps nothing.
///
/// # What is missing, and should not be papered over
///
/// The tokens still pass *through* the page during login, because the page is what talks
/// to the login command. Removing even that would mean the shell renders the login form,
/// which is a larger change than this step. What is fixed is persistence: after this
/// call the page holds nothing durable, and a restart restores the session from the
/// keyring.
#[tauri::command]
pub fn store_tokens(state: State<'_, AppState>, tokens: serde_json::Value) -> Result<(), String> {
    let pair = streamarr_desktop_player::session::TokenPair {
        access_token: tokens
            .get("access_token")
            .and_then(|v| v.as_str())
            .unwrap_or_default()
            .to_string(),
        refresh_token: tokens
            .get("refresh_token")
            .and_then(|v| v.as_str())
            .map(str::to_string),
        token_type: tokens
            .get("token_type")
            .and_then(|v| v.as_str())
            .unwrap_or("bearer")
            .to_string(),
        expires_in: tokens
            .get("expires_in")
            .and_then(|v| v.as_u64())
            .unwrap_or(0),
    };
    // Logged, and without a single value from the pair. This path had **no** logging, and
    // that cost an afternoon: the keyring stayed empty, the app worked for one session and
    // forgot it on the next start, and nothing anywhere said why. Which of the three
    // fields was missing is the whole diagnosis, and it is not secret.
    log::info!(
        "Anmeldung erhalten: access={} refresh={} type={} expires={}",
        !pair.access_token.trim().is_empty(),
        pair.refresh_token
            .as_deref()
            .is_some_and(|t| !t.trim().is_empty()),
        pair.token_type,
        pair.expires_in
    );

    // The core crate owns the rule for what a usable pair is; a login that arrived
    // without a refresh token means the platform header did not reach the server, and
    // that is a bug worth surfacing rather than storing a session that dies on restart.
    if let Err(error) = pair.validate() {
        log::warn!("Anmeldung abgelehnt, nichts gespeichert: {error}");
        return Err(error.to_string());
    }

    let backend = state.tokens.lock().unwrap().backend();
    match state.tokens.lock().unwrap().save(&pair) {
        Ok(()) => {
            log::info!("Sitzung gespeichert ({})", backend.describe());
            Ok(())
        }
        Err(error) => {
            log::warn!("Sitzung konnte nicht gespeichert werden: {error}");
            Err(format!("Token konnten nicht gespeichert werden: {error}"))
        }
    }
}

/// Handing the access token back to the page, for its own header building.
///
/// Deliberately only the *access* token, which is short-lived and which the page needs
/// for its in-memory state. The refresh token stays in the shell: it is the long-lived
/// credential, and it is the one worth protecting.
#[tauri::command]
pub fn stored_access_token(state: State<'_, AppState>) -> Result<Option<String>, String> {
    current_access_token(&state)
}

/// Removes the stored tokens, for a logout initiated by the page.
#[tauri::command]
pub fn forget_tokens(state: State<'_, AppState>) -> Result<(), String> {
    state.tokens.lock().unwrap().clear()
}

#[cfg(test)]
mod tests {
    use super::*;

    /// A transport failure must arrive as a response the page already knows how to
    /// render, carrying the concrete advice rather than a bare status.
    #[test]
    fn an_unreachable_server_produces_a_readable_response() {
        let response = BridgeResponse::unreachable(
            "`host` antwortet nicht.",
            Some("Tragen Sie die IP-Adresse ein."),
        );
        assert_eq!(response.status, 503);
        let body = response.body.unwrap();
        assert!(body.contains("antwortet nicht"));
        assert!(body.contains("IP-Adresse"));
        // And it is JSON with a `detail`, which is what the page's error handling reads.
        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert!(parsed.get("detail").is_some());
    }

    #[test]
    fn an_unreachable_server_without_advice_still_reads_well() {
        let response = BridgeResponse::unreachable("Fehlgeschlagen.", None);
        let body = response.body.unwrap();
        let parsed: serde_json::Value = serde_json::from_str(&body).unwrap();
        assert_eq!(parsed["detail"], "Fehlgeschlagen.");
    }

    /// The page must be able to tell text from binary; sending both would be ambiguous.
    #[test]
    fn a_bridge_response_carries_exactly_one_body() {
        let text = BridgeResponse {
            status: 200,
            status_text: "OK".to_string(),
            headers: vec![],
            body: Some("{}".to_string()),
            body_base64: None,
        };
        let json = serde_json::to_value(&text).unwrap();
        assert!(json.get("body").is_some());
        assert!(json.get("body_base64").is_none(), "{json}");

        let binary = BridgeResponse {
            status: 200,
            status_text: "OK".to_string(),
            headers: vec![],
            body: None,
            body_base64: Some("AAEC".to_string()),
        };
        let json = serde_json::to_value(&binary).unwrap();
        assert!(json.get("body").is_none(), "{json}");
        assert!(json.get("body_base64").is_some());
    }

    /// Headers stay a list of pairs so a repeated header is not silently collapsed.
    #[test]
    fn headers_keep_their_order_and_duplicates() {
        let response = BridgeResponse {
            status: 200,
            status_text: "OK".to_string(),
            headers: vec![
                ("set-cookie".to_string(), "a=1".to_string()),
                ("set-cookie".to_string(), "b=2".to_string()),
            ],
            body: None,
            body_base64: None,
        };
        assert_eq!(response.headers.len(), 2);
    }
}

#[cfg(test)]
mod bridge_tests {
    //! Which credential belongs to which endpoint.
    //!
    //! The shell owns both tokens, so this decision can only be made here — and getting it
    //! wrong is invisible from the page. A `400` from the refresh endpoint looks like an
    //! expired session, so the user is shown the login form while a perfectly good
    //! refresh token sits in the keyring. Measured: that is exactly what happened, and
    //! the stored token worked against the server as soon as it was sent
    //! (`POST /api/auth/refresh` → 200).

    use super::is_refresh_path;

    #[test]
    fn the_refresh_endpoint_is_recognised() {
        assert!(is_refresh_path("/api/auth/refresh"));
        assert!(is_refresh_path("/api/auth/refresh/"));
        assert!(is_refresh_path("/api/auth/refresh?x=1"));
    }

    #[test]
    fn every_other_path_is_not_the_refresh_endpoint() {
        // `starts_with` on the bare prefix would also catch these, and the first one
        // would then be sent the long-lived token instead of the short-lived one.
        assert!(!is_refresh_path("/api/auth/refreshless"));
        assert!(!is_refresh_path("/api/auth/me"));
        assert!(!is_refresh_path("/api/auth/local/login"));
        assert!(!is_refresh_path("/api/auth/status"));
        assert!(!is_refresh_path(""));
    }
}
