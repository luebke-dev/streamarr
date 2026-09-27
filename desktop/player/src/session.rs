//! Authentication and session state: tokens, refresh rotation, device identity.
//!
//! Plan tasks 1.4 and 1.5. This module owns the *state machine* of a login and
//! knows nothing about how the tokens are stored or how a request is transported:
//! the shell injects both. That keeps the crate free of Tauri and HTTP dependencies
//! (ADR 001) and lets the whole thing be tested against recorded server behaviour.
//!
//! # The three rules this module exists to enforce
//!
//! 1. **A refresh token may be redeemed exactly once.** The server rotates it on
//!    every refresh (`POST /api/auth/refresh` calls `mark_refresh_rotated`) and
//!    rejects a second use with 401. A client that fires two refreshes in parallel
//!    — or retries a refresh whose response it never saw — destroys its own
//!    session. [`Session::refresh`] therefore serialises refreshes.
//! 2. **401 and 503 are not the same thing.** A 401 on refresh means the token is
//!    genuinely dead and the user must log in again. A 503 means the server's
//!    revocation store (Redis) is unreachable and the check is fail-closed
//!    (`token_revocation.py`), so the token may well still be valid. Treating a 503
//!    as a logout would throw the user out during a brief Redis outage — see
//!    [`RefreshError::Unavailable`].
//! 3. **Native clients must identify themselves.** Sending
//!    `X-Client-Platform: native` is what makes the server return the refresh token
//!    in the response body instead of an httpOnly cookie
//!    (`auth/cookies.py::client_wants_cookie` — only the literal value `web` gets a
//!    cookie). Without the header the app would receive no refresh token at all and
//!    silently lose the session on restart, which is exactly the phase-0.5 bug this
//!    header and the frontend fix address.

use std::fmt;
use std::time::{Duration, SystemTime};

use serde::{Deserialize, Serialize};

use crate::profile::{Preferences, Profile, ServerAddress};

/// Header that selects body tokens over the httpOnly cookie.
///
/// The value `native` is deliberate: the server only treats the literal `web` as
/// a cookie client, but naming the platform keeps the server-side logs meaningful
/// and matches what `frontend/src/boot/axios.js` already sends.
pub const CLIENT_PLATFORM_HEADER: &str = "X-Client-Platform";
pub const CLIENT_PLATFORM_VALUE: &str = "native";

/// Product name reported to the server for device registration (plan task 1.5).
pub const APP_NAME: &str = "Streamarr Desktop";

/// Refresh this long before the access token actually expires.
///
/// Not zero, because a token that expires while the request is in flight produces
/// a 401 that looks like a dead session. Thirty seconds is far more than any
/// request this client makes.
pub const REFRESH_MARGIN: Duration = Duration::from_secs(30);

/// A token pair as the server issues it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TokenPair {
    pub access_token: String,
    /// Absent for web clients (cookie) — a native client must always get one, and
    /// [`TokenPair::validate`] enforces that.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub refresh_token: Option<String>,
    #[serde(default = "default_token_type")]
    pub token_type: String,
    /// Lifetime of the access token in seconds, as reported by the server.
    #[serde(default)]
    pub expires_in: u64,
}

fn default_token_type() -> String {
    "bearer".to_string()
}

/// Why a token pair was rejected.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum TokenError {
    /// No refresh token in the body — the server thought we were a web client.
    NoRefreshTokenGiven,
    EmptyAccessToken,
    /// The server reported a token type we cannot use.
    UnsupportedType(String),
}

impl fmt::Display for TokenError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NoRefreshTokenGiven => write!(
                f,
                "Der Server hat kein Refresh-Token geliefert. Sendet die App den \
                 Header `{CLIENT_PLATFORM_HEADER}: {CLIENT_PLATFORM_VALUE}`?"
            ),
            Self::EmptyAccessToken => write!(f, "Der Server hat ein leeres Access-Token geliefert"),
            Self::UnsupportedType(t) => write!(f, "Unbekannter Token-Typ `{t}`"),
        }
    }
}

impl std::error::Error for TokenError {}

impl TokenPair {
    /// Checks that this pair is actually usable by a native client.
    ///
    /// The missing-refresh-token case gets its own error variant because it is the
    /// fingerprint of a misconfigured client, and the message says so — a bare
    /// "no refresh token" would send the next reader hunting in the wrong place.
    pub fn validate(&self) -> Result<(), TokenError> {
        if self.access_token.trim().is_empty() {
            return Err(TokenError::EmptyAccessToken);
        }
        // Written as a `match` rather than `is_none_or`, which needs Rust 1.82 while
        // this crate declares 1.77.2 — clippy::incompatible_msrv enforces that, and
        // CI would reject the shorter form.
        match self.refresh_token.as_deref() {
            Some(token) if !token.trim().is_empty() => {}
            _ => return Err(TokenError::NoRefreshTokenGiven),
        }
        // Case-insensitive: the server sends lowercase, but the field is free text.
        if !self.token_type.eq_ignore_ascii_case("bearer") {
            return Err(TokenError::UnsupportedType(self.token_type.clone()));
        }
        Ok(())
    }

    /// When the access token stops being valid, given it was received now.
    pub fn access_expires_at(&self) -> SystemTime {
        SystemTime::now() + Duration::from_secs(self.expires_in)
    }
}

/// The outcome of a refresh attempt.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RefreshOutcome {
    /// New tokens; the old refresh token is now spent.
    Refreshed(TokenPair),
    /// The token is dead. The user has to log in again.
    ///
    /// Reached on 401 (rotated, revoked by cutoff, or expired). There is no point
    /// retrying: the server records spent tokens explicitly.
    NeedsLogin,
    /// The token may be fine, but the server could not check it.
    ///
    /// This is the 503 case from `token_revocation.py`: Redis was unreachable, so
    /// the check failed closed. The session must be kept and the attempt retried —
    /// logging the user out here would turn a recoverable server hiccup into lost
    /// work, and would do so precisely when the server is already unhappy.
    Unavailable,
}

/// What went wrong while refreshing.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum RefreshError {
    /// The transport itself failed; nothing is known about the token.
    Transport(String),
    /// The server answered with something unexpected.
    Unexpected(String),
}

impl fmt::Display for RefreshError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Transport(detail) => write!(f, "Verbindungsfehler beim Erneuern: {detail}"),
            Self::Unexpected(detail) => write!(f, "Unerwartete Antwort beim Erneuern: {detail}"),
        }
    }
}

impl std::error::Error for RefreshError {}

/// The server's answer to a login attempt, reduced to what the client needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct LoginResponse {
    pub tokens: TokenPair,
    pub user_guid: String,
    /// Display label, when the server provides one.
    pub user_label: Option<String>,
}

/// Why a login failed.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum LoginError {
    /// Wrong credentials, or an unknown account. Deliberately not distinguished:
    /// the server does not distinguish either, to avoid account enumeration.
    InvalidCredentials,
    /// The account exists but is not usable yet or any more.
    AccountNotUsable(String),
    /// Rate limited. `retry_after` is the server's hint in seconds, if given.
    ///
    /// The login endpoint allows five attempts per minute per IP
    /// (`api/v1/auth.py`). Worth its own variant so the UI can say "wait a moment"
    /// instead of implying the password was wrong.
    RateLimited { retry_after: Option<u64> },
    /// The server could not be reached or answered unusably.
    Transport(String),
}

impl fmt::Display for LoginError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidCredentials => write!(f, "E-Mail-Adresse oder Passwort ist falsch"),
            Self::AccountNotUsable(detail) => write!(f, "Das Konto ist nicht nutzbar: {detail}"),
            Self::RateLimited { retry_after } => match retry_after {
                Some(secs) => write!(
                    f,
                    "Zu viele Anmeldeversuche. Bitte in {secs} Sekunden erneut versuchen"
                ),
                None => write!(f, "Zu viele Anmeldeversuche. Bitte kurz warten"),
            },
            Self::Transport(detail) => write!(f, "Server nicht erreichbar: {detail}"),
        }
    }
}

impl std::error::Error for LoginError {}

/// The device record the server keeps for this installation (plan task 1.5).
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct DeviceIdentity {
    /// Server-assigned guid. `None` until the device has been registered or looked
    /// up, so the client can store an identity before its first contact.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub guid: Option<String>,
    /// Stable per-installation id the client generates and the server recognises.
    pub device_id: String,
    pub app_name: String,
    pub app_version: String,
    /// e.g. `linux`, `windows`.
    pub platform: String,
    /// Human-readable, shown in the server's device list.
    pub device_name: String,
}

impl DeviceIdentity {
    /// Builds the identity for a platform.
    ///
    /// `device_id` must be stable across restarts — otherwise every launch creates
    /// a new device entry on the server and the user's device list fills with
    /// duplicates, while capabilities and playback positions no longer line up.
    /// The shell is responsible for persisting it; this constructor only formats it.
    pub fn new(
        device_id: impl Into<String>,
        app_version: impl Into<String>,
        platform: impl Into<String>,
        device_name: impl Into<String>,
    ) -> Self {
        Self {
            guid: None,
            device_id: device_id.into(),
            app_name: APP_NAME.to_string(),
            app_version: app_version.into(),
            platform: platform.into(),
            device_name: device_name.into(),
        }
    }

    /// The `device_info` object the login request accepts.
    ///
    /// `LocalLoginRequest` has optional `device_id` and `device_info` fields; the
    /// server uses them to create or update the device record at login time, which
    /// means a device exists before the first library call.
    pub fn login_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "device_id": self.device_id,
            "device_info": {
                "app_name": self.app_name,
                "app_version": self.app_version,
                "platform": self.platform,
                "device_name": self.device_name,
            },
        })
    }
}

/// Where tokens are stored. Implemented by the shell.
///
/// Deliberately synchronous and infallible-on-read: a token store that fails on
/// read has to be treated as "logged out" anyway, and threading a `Result` through
/// every accessor would push that decision into every caller.
pub trait TokenStore: Send + Sync {
    /// Returns the stored pair, or `None` when nothing is stored.
    fn load(&self) -> Option<TokenPair>;
    /// Replaces the stored pair.
    fn save(&self, tokens: &TokenPair) -> Result<(), String>;
    /// Removes any stored pair.
    fn clear(&mut self) -> Result<(), String>;
}

/// An in-memory store, for tests and for shells that have not wired a real one.
#[derive(Debug, Default)]
pub struct MemoryTokenStore {
    tokens: std::sync::Mutex<Option<TokenPair>>,
}

impl MemoryTokenStore {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn with(tokens: TokenPair) -> Self {
        let store = Self::default();
        *store.tokens.lock().unwrap() = Some(tokens);
        store
    }
}

impl TokenStore for MemoryTokenStore {
    fn load(&self) -> Option<TokenPair> {
        self.tokens.lock().unwrap().clone()
    }

    fn save(&self, tokens: &TokenPair) -> Result<(), String> {
        *self.tokens.lock().unwrap() = Some(tokens.clone());
        Ok(())
    }

    fn clear(&mut self) -> Result<(), String> {
        *self.tokens.lock().unwrap() = None;
        Ok(())
    }
}

/// A logged-in session.
///
/// Holds the tokens and the device identity, and decides when a refresh is due.
/// The actual HTTP call is injected as a closure so this type stays transport-free
/// and the rotation rules can be tested against scripted server answers.
pub struct Session {
    profile: Profile,
    device: DeviceIdentity,
    tokens: TokenPair,
    /// Guards the refresh so two concurrent callers cannot spend the same token.
    ///
    /// Not a performance measure: a second concurrent refresh would present an
    /// already-rotated token and the server would answer 401, killing a session
    /// that was perfectly healthy.
    refresh_lock: std::sync::Mutex<()>,
}

impl Session {
    /// Starts a session from a completed login.
    pub fn new(profile: Profile, device: DeviceIdentity, tokens: TokenPair) -> Self {
        Self {
            profile,
            device,
            tokens,
            refresh_lock: std::sync::Mutex::new(()),
        }
    }

    pub fn profile(&self) -> &Profile {
        &self.profile
    }

    pub fn device(&self) -> &DeviceIdentity {
        &self.device
    }

    pub fn tokens(&self) -> &TokenPair {
        &self.tokens
    }

    pub fn preferences(&self) -> &Preferences {
        &self.profile.preferences
    }

    pub fn server(&self) -> &ServerAddress {
        &self.profile.server
    }

    /// Whether the access token should be renewed before the next request.
    pub fn needs_refresh(&self) -> bool {
        match self.tokens.access_expires_at().checked_sub(REFRESH_MARGIN) {
            Some(deadline) => SystemTime::now() >= deadline,
            // A zero or absurdly short `expires_in` means we are already inside the
            // margin, so refresh rather than send a token that expires in flight.
            None => true,
        }
    }

    /// Replaces the tokens, e.g. after a refresh or a re-login.
    pub fn set_tokens(&mut self, tokens: TokenPair) {
        self.tokens = tokens;
    }

    /// Refreshes if needed, serialising concurrent callers.
    ///
    /// `refresh` performs the actual request and returns the outcome. When another
    /// caller already refreshed while this one waited for the lock, the fresh token
    /// is reused and `refresh` is not called a second time — that is the whole point
    /// of the lock.
    pub fn refresh_if_needed<F>(&mut self, refresh: F) -> Result<Option<TokenPair>, RefreshError>
    where
        F: FnOnce(&TokenPair) -> Result<RefreshOutcome, RefreshError>,
    {
        if !self.needs_refresh() {
            return Ok(None);
        }
        // Held across the call on purpose: the request is bounded and the caller is
        // already waiting on its result.
        let _guard = self.refresh_lock.lock().unwrap();
        // Re-checked after acquiring: a caller that queued behind a successful
        // refresh must not spend the now-rotated token again.
        if !self.needs_refresh() {
            return Ok(None);
        }

        match refresh(&self.tokens)? {
            RefreshOutcome::Refreshed(pair) => {
                pair.validate()
                    .map_err(|e| RefreshError::Unexpected(e.to_string()))?;
                self.tokens = pair.clone();
                Ok(Some(pair))
            }
            RefreshOutcome::NeedsLogin => Err(RefreshError::Unexpected(
                "Das Refresh-Token ist nicht mehr gültig; erneute Anmeldung nötig".to_string(),
            )),
            // Deliberately an error and not a logout: the session is kept so the
            // caller can retry once the server's revocation store is back.
            RefreshOutcome::Unavailable => Err(RefreshError::Transport(
                "Der Server konnte das Token nicht prüfen; Sitzung bleibt erhalten".to_string(),
            )),
        }
    }

    /// Ends the session locally.
    ///
    /// The server call to `POST /api/auth/logout` is the shell's business; this
    /// only clears the state so a failed logout cannot leave the app believing it
    /// is still signed in.
    pub fn end(self, store: &mut dyn TokenStore) -> Result<(), String> {
        store.clear()
    }
}

/// Builds the headers a native client must send.
///
/// Separate from any HTTP client so both shells produce identical headers, and so
/// the phase-0.5 class of bug — a client that is native but does not say so — has
/// a single place to be right.
pub fn native_headers() -> Vec<(&'static str, &'static str)> {
    vec![
        (CLIENT_PLATFORM_HEADER, CLIENT_PLATFORM_VALUE),
        ("Accept", "application/json"),
    ]
}

/// The request body for a local login, including the device record.
pub fn login_body(email: &str, password: &str, device: &DeviceIdentity) -> serde_json::Value {
    let mut body = device.login_payload();
    let object = body.as_object_mut().expect("built above as an object");
    object.insert(
        "email".to_string(),
        serde_json::Value::String(email.to_string()),
    );
    object.insert(
        "password".to_string(),
        serde_json::Value::String(password.to_string()),
    );
    body
}

/// Maps an HTTP status from the auth endpoints to a login error.
///
/// Extracted so the mapping is testable without a server: getting these wrong is
/// how a rate limit ends up displayed as "wrong password".
pub fn classify_login_status(status: u16, detail: Option<&str>) -> LoginError {
    match status {
        200..=299 => LoginError::Transport("unerwarteter Erfolgscode".to_string()),
        401 | 403 => LoginError::InvalidCredentials,
        429 => LoginError::RateLimited { retry_after: None },
        400 | 422 => LoginError::AccountNotUsable(
            detail
                .unwrap_or("Die Anmeldedaten wurden abgelehnt")
                .to_string(),
        ),
        _ => LoginError::Transport(format!("HTTP {status}")),
    }
}

/// Maps an HTTP status from the refresh endpoint to an outcome.
pub fn classify_refresh_status(status: u16) -> RefreshOutcome {
    match status {
        200..=299 => RefreshOutcome::Refreshed(TokenPair {
            // Filled in by the caller from the response body; the status alone only
            // tells us that a refresh happened.
            access_token: String::new(),
            refresh_token: None,
            token_type: default_token_type(),
            expires_in: 0,
        }),
        // Rotated, revoked by cutoff, or expired: the server is certain.
        401 | 403 => RefreshOutcome::NeedsLogin,
        // Fail-closed revocation check: the token may be fine.
        503 => RefreshOutcome::Unavailable,
        _ => RefreshOutcome::Unavailable,
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::profile::ServerAddress;

    fn tokens(access: &str, refresh: &str, expires_in: u64) -> TokenPair {
        TokenPair {
            access_token: access.to_string(),
            refresh_token: Some(refresh.to_string()),
            token_type: "bearer".to_string(),
            expires_in,
        }
    }

    fn session_with(expires_in: u64) -> Session {
        let profile = Profile::new("test", "Test", ServerAddress::default());
        let device = DeviceIdentity::new("dev-1", "2026.2.1", "linux", "Testgerät");
        Session::new(profile, device, tokens("a", "r", expires_in))
    }

    // ── Token validation ──

    #[test]
    fn a_complete_pair_validates() {
        assert!(tokens("a", "r", 1800).validate().is_ok());
    }

    /// The fingerprint of a client that forgot the platform header. The error
    /// message must name the header, or the next reader looks in the wrong place.
    #[test]
    fn a_missing_refresh_token_is_reported_as_such() {
        let pair = TokenPair {
            access_token: "a".to_string(),
            refresh_token: None,
            token_type: "bearer".to_string(),
            expires_in: 1800,
        };
        let err = pair.validate().unwrap_err();
        assert_eq!(err, TokenError::NoRefreshTokenGiven);
        assert!(
            err.to_string().contains(CLIENT_PLATFORM_HEADER),
            "die Meldung muss den Header nennen: {err}"
        );
    }

    #[test]
    fn empty_tokens_are_rejected() {
        assert_eq!(
            TokenPair {
                access_token: "  ".to_string(),
                refresh_token: Some("r".to_string()),
                token_type: "bearer".to_string(),
                expires_in: 1,
            }
            .validate(),
            Err(TokenError::EmptyAccessToken)
        );
        let mut pair = tokens("a", "r", 1);
        pair.refresh_token = Some(String::new());
        assert_eq!(pair.validate(), Err(TokenError::NoRefreshTokenGiven));
    }

    #[test]
    fn token_type_is_checked_case_insensitively() {
        let mut pair = tokens("a", "r", 1);
        pair.token_type = "Bearer".to_string();
        assert!(pair.validate().is_ok());

        pair.token_type = "mac".to_string();
        assert_eq!(
            pair.validate(),
            Err(TokenError::UnsupportedType("mac".to_string()))
        );
    }

    // ── Refresh timing ──

    #[test]
    fn a_fresh_token_does_not_need_refreshing() {
        assert!(!session_with(1800).needs_refresh());
    }

    /// The margin exists so a token cannot expire mid-request.
    #[test]
    fn a_token_inside_the_margin_is_refreshed() {
        assert!(session_with(REFERENCE_MARGIN_SECS - 1).needs_refresh());
        assert!(session_with(REFERENCE_MARGIN_SECS).needs_refresh());
    }

    /// `expires_in: 0` would otherwise produce a token that is already dead.
    #[test]
    fn a_zero_lifetime_always_refreshes() {
        assert!(session_with(0).needs_refresh());
    }

    const REFERENCE_MARGIN_SECS: u64 = 30;

    #[test]
    fn the_margin_is_thirty_seconds() {
        assert_eq!(REFRESH_MARGIN, Duration::from_secs(REFERENCE_MARGIN_SECS));
    }

    // ── Refresh behaviour, including the rotation trap ──

    #[test]
    fn refresh_is_skipped_when_not_needed() {
        let mut session = session_with(1800);
        let result = session
            .refresh_if_needed(|_| panic!("refresh must not be called for a fresh token"))
            .unwrap();
        assert_eq!(result, None);
    }

    #[test]
    fn a_successful_refresh_replaces_the_tokens() {
        let mut session = session_with(0);
        let new = tokens("a2", "r2", 1800);
        let new_clone = new.clone();
        let returned = session
            .refresh_if_needed(move |_| Ok(RefreshOutcome::Refreshed(new_clone.clone())))
            .unwrap();
        assert_eq!(returned, Some(new.clone()));
        assert_eq!(session.tokens(), &new);
        assert!(!session.needs_refresh(), "the new token must be usable");
    }

    /// The caller has to present the *current* refresh token — the spent one must
    /// never be reused.
    #[test]
    fn the_refresh_call_receives_the_current_token() {
        let mut session = session_with(0);
        session.set_tokens(tokens("a-old", "r-old", 0));
        session
            .refresh_if_needed(|presented| {
                assert_eq!(presented.refresh_token.as_deref(), Some("r-old"));
                Ok(RefreshOutcome::Refreshed(tokens("a-new", "r-new", 1800)))
            })
            .unwrap();
    }

    /// A refresh that answers with an unusable pair (e.g. no refresh token) must
    /// not leave the session holding it.
    #[test]
    fn a_malformed_refresh_response_is_rejected() {
        let mut session = session_with(0);
        let err = session
            .refresh_if_needed(|_| {
                Ok(RefreshOutcome::Refreshed(TokenPair {
                    access_token: "a".to_string(),
                    refresh_token: None,
                    token_type: "bearer".to_string(),
                    expires_in: 10,
                }))
            })
            .unwrap_err();
        assert!(matches!(err, RefreshError::Unexpected(_)));
        assert_eq!(
            session.tokens().refresh_token.as_deref(),
            Some("r"),
            "die Sitzung darf die alten Token behalten"
        );
    }

    /// 401 means the token is genuinely gone — the caller must be told to log in,
    /// and must not be left thinking a retry could help.
    #[test]
    fn a_dead_token_surfaces_as_an_error() {
        let mut session = session_with(0);
        let err = session
            .refresh_if_needed(|_| Ok(RefreshOutcome::NeedsLogin))
            .unwrap_err();
        let message = err.to_string();
        assert!(
            message.contains("Anmeldung"),
            "die Meldung muss zur erneuten Anmeldung führen: {message}"
        );
    }

    /// The important one: a 503 from the revocation store must *not* be a logout.
    /// The session has to survive so the caller can retry.
    #[test]
    fn an_unavailable_revocation_store_keeps_the_session() {
        let mut session = session_with(0);
        let err = session
            .refresh_if_needed(|_| Ok(RefreshOutcome::Unavailable))
            .unwrap_err();
        assert!(matches!(err, RefreshError::Transport(_)));
        assert_eq!(
            session.tokens().refresh_token.as_deref(),
            Some("r"),
            "bei 503 darf die Sitzung nicht verworfen werden"
        );
        assert!(
            err.to_string().contains("erhalten"),
            "die Meldung muss sagen, dass die Sitzung bleibt: {err}"
        );
    }

    #[test]
    fn a_transport_failure_keeps_the_tokens() {
        let mut session = session_with(0);
        let err = session
            .refresh_if_needed(|_| Err(RefreshError::Transport("timeout".to_string())))
            .unwrap_err();
        assert_eq!(err, RefreshError::Transport("timeout".to_string()));
        assert_eq!(session.tokens().refresh_token.as_deref(), Some("r"));
    }

    /// Serialisation: while one caller refreshes, a second must wait and then reuse
    /// the fresh token instead of spending the rotated one. Getting this wrong is
    /// the classic self-inflicted logout.
    #[test]
    fn concurrent_callers_do_not_spend_the_token_twice() {
        use std::sync::atomic::{AtomicUsize, Ordering};
        use std::sync::{Arc, Mutex};

        let calls = Arc::new(AtomicUsize::new(0));
        let session = Arc::new(Mutex::new(session_with(0)));

        let handles: Vec<_> = (0..4)
            .map(|_| {
                let calls = calls.clone();
                let session = session.clone();
                std::thread::spawn(move || {
                    let mut guard = session.lock().unwrap();
                    guard
                        .refresh_if_needed(|_| {
                            calls.fetch_add(1, Ordering::SeqCst);
                            // A little work while holding the lock, to give the other
                            // threads a chance to pile up behind it.
                            std::thread::sleep(Duration::from_millis(20));
                            Ok(RefreshOutcome::Refreshed(tokens("a2", "r2", 1800)))
                        })
                        .unwrap()
                })
            })
            .collect();

        for handle in handles {
            handle.join().unwrap();
        }
        assert_eq!(
            calls.load(Ordering::SeqCst),
            1,
            "das Refresh-Token darf nur einmal eingelöst werden"
        );
    }

    // ── Status classification ──

    #[test]
    fn wrong_credentials_are_not_confused_with_a_rate_limit() {
        assert_eq!(
            classify_login_status(401, None),
            LoginError::InvalidCredentials
        );
        assert_eq!(
            classify_login_status(403, None),
            LoginError::InvalidCredentials
        );
        assert_eq!(
            classify_login_status(429, None),
            LoginError::RateLimited { retry_after: None }
        );
    }

    #[test]
    fn a_rate_limit_reads_differently_from_bad_credentials() {
        let limited = LoginError::RateLimited {
            retry_after: Some(42),
        };
        assert!(limited.to_string().contains("42"));
        assert!(!limited.to_string().contains("Passwort"));
        assert!(LoginError::InvalidCredentials
            .to_string()
            .contains("Passwort"));
    }

    #[test]
    fn validation_errors_become_a_usability_message() {
        let err = classify_login_status(422, Some("E-Mail nicht bestätigt"));
        assert!(matches!(err, LoginError::AccountNotUsable(_)));
        assert!(err.to_string().contains("E-Mail nicht bestätigt"));
    }

    #[test]
    fn server_errors_are_transport_failures() {
        for status in [500, 502, 504, 418] {
            assert!(matches!(
                classify_login_status(status, None),
                LoginError::Transport(_)
            ));
        }
    }

    /// 401 on refresh is final, 503 is not. This distinction is the reason the enum
    /// has a third variant; a two-variant result would force one of them wrong.
    #[test]
    fn refresh_status_separates_final_from_temporary() {
        assert_eq!(classify_refresh_status(401), RefreshOutcome::NeedsLogin);
        assert_eq!(classify_refresh_status(403), RefreshOutcome::NeedsLogin);
        assert_eq!(classify_refresh_status(503), RefreshOutcome::Unavailable);
        // Unknown codes are treated as temporary: retrying is recoverable, throwing
        // the user out is not.
        assert_eq!(classify_refresh_status(500), RefreshOutcome::Unavailable);
        assert_eq!(classify_refresh_status(502), RefreshOutcome::Unavailable);
    }

    // ── Headers and device identity ──

    #[test]
    fn native_headers_announce_the_platform() {
        let headers = native_headers();
        assert!(headers.contains(&(CLIENT_PLATFORM_HEADER, CLIENT_PLATFORM_VALUE)));
        assert_eq!(CLIENT_PLATFORM_VALUE, "native");
    }

    /// The server only withholds the refresh token for the literal value `web`
    /// (`auth/cookies.py`). If this ever became `web`, the session would vanish on
    /// restart — silently, and only for native builds.
    #[test]
    fn the_platform_value_is_never_web() {
        assert_ne!(CLIENT_PLATFORM_VALUE, "web");
    }

    #[test]
    fn device_login_payload_carries_the_expected_fields() {
        let device = DeviceIdentity::new("dev-42", "2026.2.1", "windows", "Wohnzimmer-PC");
        let body = login_body("a@b.de", "geheim", &device);
        assert_eq!(body["email"], "a@b.de");
        assert_eq!(body["password"], "geheim");
        assert_eq!(body["device_id"], "dev-42");
        assert_eq!(body["device_info"]["app_name"], APP_NAME);
        assert_eq!(body["device_info"]["app_version"], "2026.2.1");
        assert_eq!(body["device_info"]["platform"], "windows");
    }

    /// Plan task 1.5 fixes the app name; the server stores it for the device list.
    #[test]
    fn the_app_name_matches_the_plan() {
        assert_eq!(APP_NAME, "Streamarr Desktop");
        let device = DeviceIdentity::new("d", "1", "linux", "n");
        assert_eq!(device.app_name, APP_NAME);
    }

    #[test]
    fn a_device_has_no_guid_before_registration() {
        let device = DeviceIdentity::new("d", "1", "linux", "n");
        assert_eq!(device.guid, None);
    }

    // ── Session accessors ──

    #[test]
    fn a_session_exposes_its_profile_and_device() {
        let profile = Profile::new("home", "Zuhause", ServerAddress::new("https://example.org"));
        let device = DeviceIdentity::new("d", "1", "linux", "n");
        let session = Session::new(profile.clone(), device.clone(), tokens("a", "r", 1800));
        assert_eq!(session.profile(), &profile);
        assert_eq!(session.device(), &device);
        assert_eq!(session.server().host(), Some("example.org"));
    }

    #[test]
    fn ending_a_session_clears_the_store() {
        let mut store = MemoryTokenStore::with(tokens("a", "r", 1800));
        let session = session_with(1800);
        session.end(&mut store).unwrap();
        assert_eq!(store.load(), None);
    }

    #[test]
    fn the_memory_store_round_trips() {
        let mut store = MemoryTokenStore::new();
        assert_eq!(store.load(), None);
        let pair = tokens("a", "r", 1800);
        store.save(&pair).unwrap();
        assert_eq!(store.load(), Some(pair.clone()));
        store.clear().unwrap();
        assert_eq!(store.load(), None);
    }

    #[test]
    fn errors_do_not_leak_internal_type_names() {
        for err in [
            LoginError::InvalidCredentials,
            LoginError::RateLimited { retry_after: None },
            LoginError::AccountNotUsable("x".to_string()),
            LoginError::Transport("y".to_string()),
        ] {
            assert!(!err.to_string().contains("LoginError"));
            assert!(!err.to_string().is_empty());
        }
    }
}
