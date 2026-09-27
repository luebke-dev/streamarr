//! HTTP transport for the Streamarr REST API.
//!
//! This is the shell side of the boundary: it turns the shell-independent session
//! state (`streamarr_desktop_player::session`) into real requests. All the
//! *decisions* — when to refresh, what a 401 versus a 503 means, which headers a
//! native client must send — live in the core crate and are tested there. What
//! remains here is plumbing, and it is kept dull on purpose.
//!
//! # Two things this layer exists to get right
//!
//! 1. **The split-DNS pin.** Spike 0.1 found that `streamarr.luebke.internal`
//!    resolves to a Tailscale address that does not answer, while the real endpoint
//!    is reachable on the VLAN address — the reason `curl` needs `--resolve`.
//!    [`pinned_client`] reproduces that: it connects to the configured IP while
//!    keeping the hostname in the `Host` header and TLS SNI, so the certificate
//!    still validates. Repointing DNS would be the alternative, but an app cannot
//!    require the user to fix their resolver.
//! 2. **Sending the platform header.** `X-Client-Platform: native` is what makes
//!    the server return the refresh token in the body rather than an httpOnly
//!    cookie. Without it the app receives no refresh token at all and loses the
//!    session on restart. The header is applied to *every* request here, so no
//!    individual call can forget it.

use std::sync::Arc;
use std::time::Duration;

use serde_json::Value;
use streamarr_desktop_player::capabilities::Capabilities;
use streamarr_desktop_player::profile::ServerAddress;
use streamarr_desktop_player::session::{
    classify_login_status, classify_refresh_status, login_body, native_headers, DeviceIdentity,
    LoginError, LoginResponse, RefreshError, RefreshOutcome, TokenPair,
};

/// How long to wait for a connection. The server is on a LAN or VPN; a longer wait
/// only delays the error message.
const CONNECT_TIMEOUT: Duration = Duration::from_secs(10);
/// How long a normal API call may take.
const REQUEST_TIMEOUT: Duration = Duration::from_secs(30);

/// What can go wrong talking to the server.
#[derive(Debug, thiserror::Error)]
pub enum ApiError {
    #[error("Die Server-Adresse ist ungültig: {0}")]
    BadAddress(String),
    #[error("{0}")]
    Login(#[from] LoginError),
    #[error("{0}")]
    Refresh(#[from] RefreshError),
    #[error("Der Server hat unerwartet geantwortet: {0}")]
    Unexpected(String),
    #[error("Nicht angemeldet")]
    NotAuthenticated,
}

impl ApiError {
    /// The failure kind and detail, for turning into user-facing advice.
    pub fn failure(&self) -> (FailureKind, String) {
        match self {
            Self::BadAddress(detail) => (FailureKind::NameResolution, detail.clone()),
            Self::Login(LoginError::Transport(detail)) => {
                // The transport variant carries the status or the socket error text.
                (classify_text(detail), detail.clone())
            }
            Self::Login(LoginError::RateLimited { .. }) => {
                (FailureKind::Http(429), self.to_string())
            }
            Self::Login(other) => (FailureKind::Http(401), other.to_string()),
            Self::Refresh(RefreshError::Transport(detail)) => {
                (classify_text(detail), detail.clone())
            }
            Self::Refresh(other) => (FailureKind::Other, other.to_string()),
            Self::Unexpected(detail) => (classify_text(detail), detail.clone()),
            Self::NotAuthenticated => (FailureKind::Other, self.to_string()),
        }
    }
}

/// Records the full error chain when a debug log is enabled.
///
/// Kept separate from the user-facing text: the chain is what a developer needs, the
/// last entry is what the user is shown.
fn tracing_chain(error: &reqwest::Error) {
    if log::log_enabled!(log::Level::Debug) {
        log::debug!("Verbindungsfehler, Kette: {}", error_chain_text(error));
    }
}

/// Pulls an `HTTP <status>` out of a message, else classifies the text.
fn classify_text(text: &str) -> FailureKind {
    if let Some(rest) = text.split("HTTP ").nth(1) {
        if let Some(code) = rest
            .split(|c: char| !c.is_ascii_digit())
            .next()
            .and_then(|digits| digits.parse::<u16>().ok())
        {
            return FailureKind::Http(code);
        }
    }
    // The same rules as the reqwest path, on a plain string. Sharing them matters:
    // the live probe went through this function and classified a connect timeout as
    // `Other`, so the user got no advice.
    let lowered = text.to_ascii_lowercase();
    if lowered.contains("timed out")
        || lowered.contains("timeout")
        || lowered.contains("timedoute")
        || lowered.contains("zeitüberschreitung")
    {
        return FailureKind::Timeout;
    }
    if lowered.contains("certificate")
        || lowered.contains("zertifikat")
        || lowered.contains("tls")
        || lowered.contains("ssl")
    {
        return FailureKind::Tls;
    }
    if lowered.contains("dns")
        || lowered.contains("lookup")
        || lowered.contains("resolve")
        || lowered.contains("name or service not known")
    {
        return FailureKind::NameResolution;
    }
    if lowered.contains("refused") || lowered.contains("abgelehnt") {
        return FailureKind::ConnectionRefused;
    }
    FailureKind::Other
}

/// The result of an authenticated request.
pub enum Authed<T> {
    /// The request succeeded.
    Ok(T),
    /// The access token was renewed first; the caller should persist the new pair.
    ///
    /// Returned rather than stored directly so the caller keeps a single place where
    /// tokens are written, which is what makes the rotation rule auditable.
    Renewed(T, Box<TokenPair>),
}

impl<T> Authed<T> {
    pub fn into_parts(self) -> (T, Option<TokenPair>) {
        match self {
            Self::Ok(value) => (value, None),
            Self::Renewed(value, tokens) => (value, Some(*tokens)),
        }
    }
}

/// Why a request did not reach the server.
///
/// Structured rather than a string, so the advice can depend on the *kind* of failure.
/// This exists because of a measured live situation: `streamarr.luebke.internal`
/// resolves to a Tailscale address that does not answer, so every request hung for
/// **20 seconds** and then failed with no explanation. The name resolved, TLS was fine,
/// and the only way through was `curl --resolve` — knowledge the app has to hand the
/// user rather than expect them to have.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FailureKind {
    /// The name could not be resolved at all.
    NameResolution,
    /// The name resolved, but nothing answered. This is the split-DNS case.
    Timeout,
    /// Something answered and refused.
    ConnectionRefused,
    /// TLS failed — the internal certificate authority is the usual cause.
    Tls,
    /// The server answered with an error status.
    Http(u16),
    /// Anything else.
    Other,
}

/// What the user should do about it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Diagnosis {
    /// One sentence naming the problem, in German.
    pub problem: String,
    /// One sentence saying what to do. `None` when there is nothing useful to say.
    pub advice: Option<String>,
    /// Whether setting an IP pin is the likely fix, so the UI can offer the field.
    pub suggests_pin: bool,
}

/// Turns a failure into an explanation and concrete advice.
///
/// Pure, so every case is testable without a broken network — and the cases matter,
/// because the wrong advice is worse than none: telling someone to check their
/// certificate when DNS is the problem sends them down a long path.
pub fn diagnose(server: &ServerAddress, kind: FailureKind, detail: &str) -> Diagnosis {
    let host = server.host().unwrap_or("den Server").to_string();
    let pinned = server.resolve_override.is_some();

    match kind {
        FailureKind::NameResolution => Diagnosis {
            problem: format!("Der Name `{host}` lässt sich nicht auflösen."),
            advice: Some(
                "Prüfen Sie die Schreibweise, oder tragen Sie im Profil die IP-Adresse des Servers ein."
                    .to_string(),
            ),
            suggests_pin: true,
        },
        // The measured case, and the one worth being precise about.
        FailureKind::Timeout => {
            let advice = if pinned {
                format!(
                    "Die Verbindung zu {} antwortet nicht. Prüfen Sie, ob der Server läuft und die eingetragene IP-Adresse stimmt.",
                    server.resolve_override.as_deref().unwrap_or("")
                )
            } else {
                format!(
                    "Der Name `{host}` wird aufgelöst, aber niemand antwortet. Das passiert, wenn der DNS-Eintrag auf eine nicht erreichbare Adresse zeigt (etwa eine inaktive VPN-Adresse). Tragen Sie im Profil unter „IP-Adresse“ die tatsächliche Adresse des Servers ein — der Name bleibt dabei erhalten, sodass das Zertifikat weiter passt."
                )
            };
            Diagnosis {
                problem: format!("`{host}` antwortet nicht (Zeitüberschreitung)."),
                advice: Some(advice),
                suggests_pin: !pinned,
            }
        }
        FailureKind::ConnectionRefused => Diagnosis {
            problem: format!("`{host}` hat die Verbindung abgelehnt."),
            advice: Some(
                "Der Server ist erreichbar, lehnt aber Verbindungen ab. Läuft der Dienst, und stimmt der Port?"
                    .to_string(),
            ),
            suggests_pin: false,
        },
        FailureKind::Tls => Diagnosis {
            problem: format!("Die verschlüsselte Verbindung zu `{host}` ist fehlgeschlagen."),
            advice: Some(
                "Das Zertifikat wird nicht akzeptiert. Bei einem selbst betriebenen Server muss die zugehörige Zertifizierungsstelle im System installiert sein — auf Linux etwa als Datei in /etc/pki/ca-trust/source/anchors/, gefolgt von `update-ca-trust`."
                    .to_string(),
            ),
            suggests_pin: false,
        },
        FailureKind::Http(status) => Diagnosis {
            // The host is named because a user may have several profiles, and "HTTP
 // 503" alone does not say which server answered.
            problem: format!("`{host}` hat mit HTTP {status} geantwortet."),
            // 5xx is the server's own problem, and the detail is worth showing because
            // it is often specific — a full disk produced "Rate limiter unavailable".
            advice: detail
                .trim()
                .is_empty()
                .then(|| "Der Server hat den Fehler nicht näher erklärt.".to_string()),
            suggests_pin: false,
        },
        FailureKind::Other => {
            // The detail is a raw error message that may or may not end in a full stop,
            // so one is appended only when it is missing — otherwise the sentence ends
            // in "..", which looks like a bug.
            let detail = detail.trim().trim_end_matches('.');
            Diagnosis {
                problem: format!("Die Anfrage an `{host}` ist fehlgeschlagen: {detail}."),
                advice: None,
                suggests_pin: false,
            }
        }
    }
}

/// Classifies a transport error.
///
/// The classification uses reqwest's own flags first and falls back to the message,
/// because the flags cover the cases that matter most (timeout, refused) while the
/// message is the only place a TLS or DNS failure is named.
pub fn classify_error(error: &reqwest::Error) -> FailureKind {
    // The whole chain, not just the top message. A live probe against the real server
    // returned the top-level text "error sending request for url (…)" with nothing
    // else — and classifying that as `Other` meant the user got no advice at all,
    // which is exactly the failure this function exists to prevent. The actual cause
    // (a connect timeout) sits in the source chain.
    let text = error_chain_text(error);

    // Flags first: they are authoritative where they apply.
    if error.is_timeout() {
        return FailureKind::Timeout;
    }
    // A bare `is_connect()` is not enough either — the wrapper above did not report the
    // connect phase, so the text decides.
    if text.contains("timed out") || text.contains("timeout") {
        return FailureKind::Timeout;
    }
    if text.contains("certificate") || text.contains("tls") || text.contains("ssl") {
        return FailureKind::Tls;
    }
    if text.contains("dns")
        || text.contains("lookup")
        || text.contains("resolve")
        || text.contains("name or service not known")
        || text.contains("nodename nor servname")
    {
        return FailureKind::NameResolution;
    }
    if text.contains("refused") || text.contains("connection reset") {
        return FailureKind::ConnectionRefused;
    }
    if error.is_connect() {
        return FailureKind::ConnectionRefused;
    }
    FailureKind::Other
}

/// Every message in the error's source chain, lower-cased and joined.
///
/// reqwest wraps its causes, so the specific text is rarely at the top. Without
/// walking the chain, "connection timed out" is invisible behind "error sending
/// request".
pub fn error_chain_text(error: &reqwest::Error) -> String {
    let mut parts = vec![error.to_string()];
    let mut source: Option<&(dyn std::error::Error + 'static)> = std::error::Error::source(error);
    // Bounded: a cyclic chain would otherwise hang the diagnostics.
    for _ in 0..8 {
        let Some(current) = source else { break };
        parts.push(current.to_string());
        source = current.source();
    }
    parts.join(" | ").to_ascii_lowercase()
}

/// The readable detail for a failure, preferring the most specific message.
pub fn error_detail(error: &reqwest::Error) -> String {
    let mut detail = error.to_string();
    let mut source: Option<&(dyn std::error::Error + 'static)> = std::error::Error::source(error);
    for _ in 0..8 {
        let Some(current) = source else { break };
        detail = current.to_string();
        source = current.source();
    }
    detail
}

/// Builds the HTTP client for a server address, honouring the resolve pin.
///
/// The pin is expressed with `resolve()`, which is the same mechanism as
/// `curl --resolve`: the connection goes to the given address while the URL keeps
/// its hostname. That is what keeps `Host` and TLS SNI correct, so the internal CA
/// still validates.
pub fn pinned_client(server: &ServerAddress) -> Result<reqwest::Client, ApiError> {
    server
        .validate()
        .map_err(|e| ApiError::BadAddress(e.to_string()))?;

    let mut builder = reqwest::Client::builder()
        .connect_timeout(CONNECT_TIMEOUT)
        .timeout(REQUEST_TIMEOUT)
        // The API is same-origin in spirit; no other host is contacted.
        .redirect(reqwest::redirect::Policy::none());

    if let Some(pair) = server.resolve_pair() {
        // `host:port:ip` -> reqwest wants (hostname, socket address).
        if let Some((host, port, ip)) = split_resolve_pair(&pair) {
            let socket = format!("{ip}:{port}");
            builder = builder.resolve(
                &host,
                socket.parse().map_err(|_| {
                    ApiError::BadAddress(format!("`{ip}` ist keine gültige IP-Adresse"))
                })?,
            );
        }
    }

    builder
        .build()
        .map_err(|e| ApiError::Unexpected(e.to_string()))
}

/// Splits a `host:port:ip` triple.
///
/// Written out rather than using `split(':')` because the host can be an IPv6
/// literal. The IP is taken from the right, which is unambiguous for the
/// `host:port:ip` shape the core crate produces.
fn split_resolve_pair(pair: &str) -> Option<(String, u16, String)> {
    // The IP may itself contain colons (IPv6); the trailing port is numeric, so
    // splitting from the left twice is the safe direction.
    let (host, rest) = pair.split_once(':')?;
    let (port, ip) = rest.split_once(':')?;
    Some((host.to_string(), port.parse().ok()?, ip.to_string()))
}

/// An API client bound to one server.
#[derive(Clone)]
pub struct ApiClient {
    http: reqwest::Client,
    base_url: String,
}

impl ApiClient {
    pub fn new(server: &ServerAddress) -> Result<Self, ApiError> {
        Ok(Self {
            http: pinned_client(server)?,
            base_url: server.base_url(),
        })
    }

    fn url(&self, path: &str) -> String {
        format!("{}{}", self.base_url, path)
    }

    /// Applies the headers every native request needs.
    ///
    /// Centralised so the platform header cannot be forgotten at a call site —
    /// forgetting it is silent and only shows up as a lost session after a restart.
    fn request(&self, method: reqwest::Method, path: &str) -> reqwest::RequestBuilder {
        let mut builder = self.http.request(method, self.url(path));
        for (name, value) in native_headers() {
            builder = builder.header(name, value);
        }
        builder
    }

    fn bearer(&self, mut builder: reqwest::RequestBuilder, token: &str) -> reqwest::RequestBuilder {
        builder = builder.bearer_auth(token);
        builder
    }

    // ── Auth ──

    /// Server capabilities and login options. Needs no token.
    pub async fn auth_status(&self) -> Result<Value, ApiError> {
        let response = self
            .request(reqwest::Method::GET, "/api/auth/status")
            .send()
            .await
            .map_err(|e| {
                // The full chain, not just the top message: reqwest's outer text says
                // only "error sending request for url (…)", and classifying that gave
                // `Other`, i.e. no advice at all. Measured against the real server.
                tracing_chain(&e);
                ApiError::Unexpected(error_detail(&e))
            })?;
        read_json(response).await
    }

    /// Exchanges credentials for tokens.
    ///
    /// The device identity travels with the login so the server creates the device
    /// record immediately; without it the app would appear as an unknown client
    /// until it happened to register one.
    pub async fn login(
        &self,
        email: &str,
        password: &str,
        device: &DeviceIdentity,
    ) -> Result<LoginResponse, ApiError> {
        let response = self
            .request(reqwest::Method::POST, "/api/auth/local/login")
            .json(&login_body(email, password, device))
            .send()
            .await
            .map_err(|e| LoginError::Transport(error_detail(&e)))?;

        let status = response.status().as_u16();
        let body: Value = response
            .json()
            .await
            .map_err(|e| LoginError::Transport(e.to_string()))?;

        if !(200..=299).contains(&status) {
            let detail = extract_detail(&body);
            return Err(classify_login_status(status, detail.as_deref()).into());
        }

        let tokens = parse_tokens(&body)?;
        // The server may or may not echo the user; the status endpoint is the
        // reliable source, but a guid in the response saves a round trip.
        let user_guid = body
            .get("user")
            .and_then(|u| u.get("guid"))
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string();
        let user_label = body
            .get("user")
            .and_then(|u| {
                u.get("preferred_username")
                    .or_else(|| u.get("email"))
                    .and_then(Value::as_str)
            })
            .map(str::to_string);

        Ok(LoginResponse {
            tokens,
            user_guid,
            user_label,
        })
    }

    /// Renews an access token. Spends the presented refresh token.
    pub async fn refresh(&self, refresh_token: &str) -> Result<RefreshOutcome, RefreshError> {
        let response = self
            .request(reqwest::Method::POST, "/api/auth/refresh")
            .bearer_auth(refresh_token)
            .send()
            .await
            .map_err(|e| RefreshError::Transport(error_detail(&e)))?;

        let status = response.status().as_u16();
        let body: Value = response
            .json()
            .await
            .map_err(|e| RefreshError::Transport(e.to_string()))?;

        match classify_refresh_status(status) {
            // The status only says that a refresh happened; the tokens come from the
            // body, so a success is re-parsed rather than trusted from the status.
            RefreshOutcome::Refreshed(_) => {
                let mut tokens =
                    parse_tokens(&body).map_err(|e| RefreshError::Unexpected(e.to_string()))?;
                tokens.token_type = "bearer".to_string();
                Ok(RefreshOutcome::Refreshed(tokens))
            }
            other => Ok(other),
        }
    }

    /// Ends the session server-side. Failures are the caller's to ignore: the local
    /// state must be cleared either way.
    pub async fn logout(&self, access_token: &str) -> Result<(), ApiError> {
        let response = self
            .bearer(
                self.request(reqwest::Method::POST, "/api/auth/logout"),
                access_token,
            )
            .send()
            .await
            .map_err(|e| ApiError::Unexpected(e.to_string()))?;
        if response.status().is_success() {
            Ok(())
        } else {
            Err(ApiError::Unexpected(format!(
                "HTTP {}",
                response.status().as_u16()
            )))
        }
    }

    // ── Device registration (plan task 1.5) ──

    /// Reports this client's capabilities for a device.
    pub async fn put_capabilities(
        &self,
        access_token: &str,
        device_guid: &str,
        capabilities: &Capabilities,
    ) -> Result<Value, ApiError> {
        let response = self
            .bearer(
                self.request(
                    reqwest::Method::PUT,
                    &format!("/api/devices/me/{device_guid}/capabilities"),
                ),
                access_token,
            )
            .json(&capabilities.device_payload())
            .send()
            .await
            .map_err(|e| ApiError::Unexpected(e.to_string()))?;
        read_json(response).await
    }

    /// Fetches the capabilities the server has stored for a device.
    pub async fn get_capabilities(
        &self,
        access_token: &str,
        device_guid: &str,
    ) -> Result<Value, ApiError> {
        let response = self
            .bearer(
                self.request(
                    reqwest::Method::GET,
                    &format!("/api/devices/me/{device_guid}/capabilities"),
                ),
                access_token,
            )
            .send()
            .await
            .map_err(|e| ApiError::Unexpected(e.to_string()))?;
        read_json(response).await
    }
}

/// Pulls `detail` out of a FastAPI error body, which may be a string or a list of
/// validation objects.
fn extract_detail(body: &Value) -> Option<String> {
    match body.get("detail") {
        Some(Value::String(text)) => Some(text.clone()),
        // A 422 gives `[{loc: [...], msg: "..."}]`; the messages are what matter.
        Some(Value::Array(items)) => {
            let messages: Vec<String> = items
                .iter()
                .filter_map(|item| item.get("msg").and_then(Value::as_str))
                .map(str::to_string)
                .collect();
            if messages.is_empty() {
                None
            } else {
                Some(messages.join("; "))
            }
        }
        _ => None,
    }
}

/// A response as the transport layer sees it, *without* turning a non-success status
/// into an error.
///
/// This exists for the WebView proxy. The browser's own HTTP layer hands a 401 or a 500
/// to the page as a normal response and lets the application decide — and the page's
/// existing interceptors rely on that, including the retry-after-refresh path. Raising
/// an error here would bypass all of it.
#[derive(Debug, Clone)]
pub struct RawResponse {
    pub status: u16,
    pub status_text: String,
    pub headers: Vec<(String, String)>,
    /// The body. `Text` for anything textual (JSON included), `Base64` for binary such
    /// as artwork, so the WebView can rebuild a blob.
    pub body: RawBody,
}

#[derive(Debug, Clone)]
pub enum RawBody {
    Text(String),
    Base64(String),
    Empty,
}

/// What a proxied request needs.
#[derive(Debug, Clone)]
pub struct RawRequest {
    pub method: String,
    /// Path, e.g. `/api/auth/status`.
    pub path: String,
    /// Absolute base URL the page asked for. `None` uses the active profile's server —
    /// which is the point of the proxy: the page no longer has to know the address, and
    /// the pin is applied here.
    pub base_url: Option<String>,
    pub headers: Vec<(String, String)>,
    pub body: Option<String>,
    /// Per-request timeout in milliseconds, mirroring axios's `timeout`.
    pub timeout_ms: Option<u64>,
}

impl ApiClient {
    /// Performs a request and returns the response as it came, errors and all.
    ///
    /// Used by the WebView proxy. The address and the resolve pin come from the client,
    /// never from the page — so a page cannot be tricked into talking to another host,
    /// and the pin works for the embedded UI exactly as it does for the app.
    pub async fn raw_request(&self, request: &RawRequest) -> Result<RawResponse, ApiError> {
        let method = reqwest::Method::from_bytes(request.method.to_ascii_uppercase().as_bytes())
            .map_err(|_| ApiError::Unexpected(format!("unbekannte Methode {}", request.method)))?;

        // A per-request base URL is honoured only if it matches the configured server.
        // Otherwise a page could redirect the app's credentials elsewhere.
        let client = match &request.base_url {
            Some(base) => {
                if !self.accepts_base_url(base) {
                    return Err(ApiError::Unexpected(format!(
                        "Die Adresse `{base}` gehört nicht zum aktiven Profil."
                    )));
                }
                self.clone()
            }
            None => self.clone(),
        };

        let mut builder = client
            .http
            .request(method, client.url(&request.path))
            .timeout(std::time::Duration::from_millis(
                request
                    .timeout_ms
                    .unwrap_or(REQUEST_TIMEOUT.as_millis() as u64),
            ));

        // The platform header is applied here as well, so a page cannot omit it. It is
        // what makes the server hand out a refresh token in the body; without it the
        // session dies on restart.
        for (name, value) in native_headers() {
            builder = builder.header(name, value);
        }
        // Page headers are applied afterwards, so a page may override `Accept` but not
        // add a second platform header.
        for (name, value) in &request.headers {
            let lowered = name.to_ascii_lowercase();
            if lowered == "host" || lowered == "content-length" || lowered == "connection" {
                continue;
            }
            builder = builder.header(name, value);
        }
        if let Some(body) = &request.body {
            builder = builder.body(body.clone());
        }

        let response = builder.send().await.map_err(|e| {
            tracing_chain(&e);
            ApiError::Unexpected(error_detail(&e))
        })?;

        let status = response.status();
        let headers: Vec<(String, String)> = response
            .headers()
            .iter()
            .map(|(name, value)| {
                (
                    name.as_str().to_string(),
                    value.to_str().unwrap_or_default().to_string(),
                )
            })
            .collect();

        // Binary is base64-encoded so the page can rebuild a blob; text is passed
        // through. Decided by content type, and bounded so a large download cannot be
        // pulled into memory through this path — playback never goes through here.
        let content_type = response
            .headers()
            .get(reqwest::header::CONTENT_TYPE)
            .and_then(|value| value.to_str().ok())
            .unwrap_or("")
            .to_ascii_lowercase();
        let is_textual = content_type.starts_with("text/")
            || content_type.contains("json")
            || content_type.contains("xml")
            || content_type.contains("javascript")
            || content_type.is_empty();

        let bytes = response
            .bytes()
            .await
            .map_err(|e| ApiError::Unexpected(e.to_string()))?;
        let body = if bytes.is_empty() {
            RawBody::Empty
        } else if is_textual {
            RawBody::Text(String::from_utf8_lossy(&bytes).to_string())
        } else {
            RawBody::Base64(base64_encode(&bytes))
        };

        Ok(RawResponse {
            status: status.as_u16(),
            status_text: status.canonical_reason().unwrap_or("").to_string(),
            headers,
            body,
        })
    }

    /// Whether an absolute base URL refers to this client's own server.
    ///
    /// Compared by host and explicit port, ignoring the scheme, because the page may
    /// hold `http://` while the profile uses `https://` — and a mismatch there is a
    /// configuration accident, not an attack. A *different host*, however, is refused.
    fn accepts_base_url(&self, base: &str) -> bool {
        let host_of = |url: &str| -> Option<(String, Option<String>)> {
            let rest = url.split("://").nth(1).unwrap_or(url);
            let authority = rest.split('/').next()?;
            match authority.rsplit_once(':') {
                Some((host, port)) => Some((host.to_ascii_lowercase(), Some(port.to_string()))),
                None => Some((authority.to_ascii_lowercase(), None)),
            }
        };
        let (self_host, _) = match host_of(&self.base_url) {
            Some(parts) => parts,
            None => return false,
        };
        match host_of(base) {
            Some((host, _)) => host == self_host,
            None => false,
        }
    }
}

/// Standard base64, for the binary path of the WebView proxy.
///
/// Hand-written for the same reason the URL parsing is: a dependency for thirty lines
/// would be out of proportion in this crate, and the alphabet is fixed.
fn base64_encode(input: &[u8]) -> String {
    const ALPHABET: &[u8; 64] = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/";
    let mut out = String::with_capacity(input.len().div_ceil(3) * 4);
    for chunk in input.chunks(3) {
        let b = [
            chunk[0],
            *chunk.get(1).unwrap_or(&0),
            *chunk.get(2).unwrap_or(&0),
        ];
        let triple = ((b[0] as u32) << 16) | ((b[1] as u32) << 8) | (b[2] as u32);
        out.push(ALPHABET[(triple >> 18) as usize & 0x3f] as char);
        out.push(ALPHABET[(triple >> 12) as usize & 0x3f] as char);
        out.push(if chunk.len() > 1 {
            ALPHABET[(triple >> 6) as usize & 0x3f] as char
        } else {
            '='
        });
        out.push(if chunk.len() > 2 {
            ALPHABET[triple as usize & 0x3f] as char
        } else {
            '='
        });
    }
    out
}

/// Reads a JSON body, turning a non-success status into an error that keeps the
/// server's explanation.
async fn read_json(response: reqwest::Response) -> Result<Value, ApiError> {
    let status = response.status().as_u16();
    let body: Value = response
        .json()
        .await
        .map_err(|e| ApiError::Unexpected(e.to_string()))?;
    if (200..=299).contains(&status) {
        Ok(body)
    } else {
        match extract_detail(&body) {
            Some(detail) => Err(ApiError::Unexpected(format!("HTTP {status}: {detail}"))),
            None => Err(ApiError::Unexpected(format!("HTTP {status}"))),
        }
    }
}

/// Parses a token pair out of a login or refresh response.
fn parse_tokens(body: &Value) -> Result<TokenPair, LoginError> {
    let pair = TokenPair {
        access_token: body
            .get("access_token")
            .and_then(Value::as_str)
            .unwrap_or_default()
            .to_string(),
        refresh_token: body
            .get("refresh_token")
            .and_then(Value::as_str)
            .map(str::to_string),
        token_type: body
            .get("token_type")
            .and_then(Value::as_str)
            .unwrap_or("bearer")
            .to_string(),
        expires_in: body.get("expires_in").and_then(Value::as_u64).unwrap_or(0),
    };
    // The core crate owns the rules for what a usable pair is; this only fills the
    // struct. A missing refresh token here means the platform header did not reach
    // the server, and the error says so.
    pair.validate().map_err(|_| {
        LoginError::Transport(
            "Der Server hat kein Refresh-Token geliefert — sendet die App den Header \
         `X-Client-Platform: native`?"
                .to_string(),
        )
    })?;
    Ok(pair)
}

/// Shared handle, so windows can hold the client without cloning the connection pool.
pub type SharedApi = Arc<ApiClient>;

#[cfg(test)]
mod tests {
    use super::*;

    // ── Resolve pin parsing ──

    #[test]
    fn a_resolve_pair_splits_into_its_three_parts() {
        assert_eq!(
            split_resolve_pair("streamarr.luebke.internal:443:10.10.60.30"),
            Some((
                "streamarr.luebke.internal".to_string(),
                443,
                "10.10.60.30".to_string()
            ))
        );
    }

    /// The IP is taken from the right so an IPv6 literal survives: only the port is
    /// known to be numeric, everything after it belongs to the address.
    #[test]
    fn an_ipv6_pin_keeps_its_address_intact() {
        assert_eq!(
            split_resolve_pair("host:8443:fd00::1"),
            Some(("host".to_string(), 8443, "fd00::1".to_string()))
        );
    }

    #[test]
    fn a_malformed_pair_is_rejected() {
        for bad in ["host", "host:notaport:1.2.3.4", "host:443"] {
            assert_eq!(split_resolve_pair(bad), None, "`{bad}` should not parse");
        }
    }

    // ── Client construction ──

    #[test]
    fn a_valid_address_builds_a_client() {
        let server = ServerAddress::new("https://streamarr.luebke.internal");
        assert!(pinned_client(&server).is_ok());
    }

    #[test]
    fn a_pinned_address_builds_a_client() {
        let mut server = ServerAddress::new("https://streamarr.luebke.internal");
        server.resolve_override = Some("10.10.60.30:443".to_string());
        assert!(pinned_client(&server).is_ok());
    }

    #[test]
    fn an_invalid_address_is_refused() {
        let server = ServerAddress::new("nicht-valid");
        assert!(matches!(
            pinned_client(&server),
            Err(ApiError::BadAddress(_))
        ));
    }

    /// A pin that is not a valid IP has to be caught when the client is built, not
    /// silently ignored — otherwise the app would talk to whatever DNS says and the
    /// user's correction would appear to do nothing.
    #[test]
    fn a_pin_that_is_not_an_ip_is_refused() {
        let mut server = ServerAddress::new("https://host");
        server.resolve_override = Some("keine-ip:443".to_string());
        assert!(matches!(
            pinned_client(&server),
            Err(ApiError::BadAddress(_))
        ));
    }

    // ── Failure diagnosis ──

    /// The measured case. Getting this wrong sends the user looking in the wrong place,
    /// so the advice must name the actual cause: a name that resolves to an address
    /// nobody answers on, and the IP pin as the way through.
    #[test]
    fn a_timeout_on_an_unpinned_address_suggests_the_ip_pin() {
        let server = ServerAddress::new("https://streamarr.luebke.internal");
        let diagnosis = diagnose(&server, FailureKind::Timeout, "");
        assert!(diagnosis.suggests_pin, "der Pin ist hier die Lösung");
        let advice = diagnosis.advice.unwrap();
        assert!(advice.contains("IP-Adresse"), "{advice}");
        assert!(
            advice.contains("Zertifikat"),
            "der Name muss erhalten bleiben"
        );
        // And it must not blame the certificate, which was fine.
        assert!(!diagnosis.problem.to_lowercase().contains("zertifikat"));
    }

    #[test]
    fn a_timeout_on_a_pinned_address_does_not_suggest_pinning_again() {
        let mut server = ServerAddress::new("https://host");
        server.resolve_override = Some("10.0.0.1:443".to_string());
        let diagnosis = diagnose(&server, FailureKind::Timeout, "");
        assert!(!diagnosis.suggests_pin);
        let advice = diagnosis.advice.unwrap();
        assert!(
            advice.contains("10.0.0.1"),
            "die eingetragene IP nennen: {advice}"
        );
    }

    #[test]
    fn a_missing_name_suggests_the_pin_too() {
        let server = ServerAddress::new("https://tippfehler.invalid");
        let diagnosis = diagnose(&server, FailureKind::NameResolution, "");
        assert!(diagnosis.suggests_pin);
        assert!(diagnosis.problem.contains("tippfehler.invalid"));
    }

    /// A certificate problem must not be answered with "check your DNS".
    #[test]
    fn a_tls_failure_points_at_the_certificate_authority() {
        let server = ServerAddress::new("https://host");
        let diagnosis = diagnose(&server, FailureKind::Tls, "");
        let advice = diagnosis.advice.unwrap();
        assert!(advice.contains("ca-trust") || advice.contains("Zertifizierungsstelle"));
        assert!(
            !diagnosis.suggests_pin,
            "ein Zertifikatsproblem ist kein DNS-Problem"
        );
    }

    #[test]
    fn a_refused_connection_is_not_a_dns_problem() {
        let server = ServerAddress::new("https://host");
        let diagnosis = diagnose(&server, FailureKind::ConnectionRefused, "");
        assert!(diagnosis.problem.contains("abgelehnt"));
        assert!(!diagnosis.suggests_pin);
    }

    /// A 5xx keeps the server's own explanation, because it is often specific — a full
    /// disk produced "Rate limiter unavailable" rather than anything about capacity.
    #[test]
    fn an_http_error_carries_the_server_explanation() {
        let server = ServerAddress::new("https://host");
        let diagnosis = diagnose(&server, FailureKind::Http(503), "Rate limiter unavailable");
        assert!(diagnosis.problem.contains("503"));
        // A 5xx is the server's own problem; pinning the IP cannot help.
        assert!(!diagnosis.suggests_pin);
        assert_eq!(diagnosis.advice, None, "der Servertext steht im Problem");
    }

    /// A Python edit once collapsed the line continuations in these strings and baked
    /// the source indentation into the user-facing text: "Das                      passiert".
    /// The mistake was invisible in the code and obvious only at runtime, so it is
    /// checked here.
    #[test]
    fn diagnosis_texts_have_no_stray_gaps() {
        let server = ServerAddress::new("https://host");
        let mut texts = Vec::new();
        for kind in [
            FailureKind::NameResolution,
            FailureKind::Timeout,
            FailureKind::ConnectionRefused,
            FailureKind::Tls,
            FailureKind::Http(500),
            FailureKind::Other,
        ] {
            let diagnosis = diagnose(&server, kind, "detail");
            texts.push(diagnosis.problem);
            if let Some(advice) = diagnosis.advice {
                texts.push(advice);
            }
        }
        // The pinned variant has its own wording.
        let mut pinned = ServerAddress::new("https://host");
        pinned.resolve_override = Some("10.0.0.1:443".to_string());
        if let Some(advice) = diagnose(&pinned, FailureKind::Timeout, "").advice {
            texts.push(advice);
        }

        for text in texts {
            assert!(
                !text.contains("  "),
                "doppelte Leerzeichen im Nutzertext: {text:?}"
            );
            assert!(
                !text.contains("\n"),
                "Zeilenumbruch im Nutzertext: {text:?}"
            );
            // A complete sentence. A question mark counts — one of the diagnoses ends
            // in a question ("Läuft der Dienst, und stimmt der Port?"), and demanding a
            // full stop would have been a wrong rule rather than a strict one.
            assert!(
                text.ends_with('.') || text.ends_with('!') || text.ends_with('?'),
                "{text:?}"
            );
            // (No check for a space after a full stop: that is ordinary German
            // punctuation. An earlier version flagged it and was simply wrong.)
        }
    }

    #[test]
    fn every_diagnosis_has_a_problem_sentence() {
        let server = ServerAddress::new("https://host");
        for kind in [
            FailureKind::NameResolution,
            FailureKind::Timeout,
            FailureKind::ConnectionRefused,
            FailureKind::Tls,
            FailureKind::Http(500),
            FailureKind::Other,
        ] {
            let diagnosis = diagnose(&server, kind, "detail");
            assert!(!diagnosis.problem.is_empty(), "{kind:?} ohne Problemtext");
            // The host must be named, so the user knows which server is meant.
            assert!(
                diagnosis.problem.contains("host"),
                "{kind:?}: {}",
                diagnosis.problem
            );
        }
    }

    /// The live case: the top-level reqwest message says nothing useful, and the
    /// cause is buried in the source chain. Classifying on the top message alone gave
    /// `Other`, which means no advice — verified against the real server.
    #[test]
    fn a_timeout_is_recognised_from_the_error_text() {
        assert_eq!(
            classify_text("error sending request: connection timed out"),
            FailureKind::Timeout
        );
        assert_eq!(
            classify_text("HTTP 503: Rate limiter unavailable"),
            FailureKind::Http(503)
        );
    }

    #[test]
    fn a_certificate_problem_is_recognised_from_the_text() {
        assert_eq!(
            classify_text("error sending request: invalid peer certificate"),
            FailureKind::Tls
        );
    }

    #[test]
    fn name_resolution_is_recognised_from_the_text() {
        for text in [
            "dns error: failed to lookup address information",
            "Name or service not known",
            "failed to resolve address",
        ] {
            assert_eq!(classify_text(text), FailureKind::NameResolution, "{text}");
        }
    }

    #[test]
    fn a_refused_connection_is_recognised_from_the_text() {
        assert_eq!(
            classify_text("error sending request: connection refused"),
            FailureKind::ConnectionRefused
        );
    }

    /// The status code must win over incidental words in the body: a 503 whose text
    /// mentions "timeout" is still an HTTP failure with the server's explanation.
    #[test]
    fn an_http_status_wins_over_words_in_the_detail() {
        assert_eq!(
            classify_text("HTTP 504: upstream timeout"),
            FailureKind::Http(504)
        );
    }

    // ── Error-body parsing ──

    #[test]
    fn a_string_detail_is_extracted() {
        let body = serde_json::json!({"detail": "Rate limiter unavailable"});
        assert_eq!(
            extract_detail(&body),
            Some("Rate limiter unavailable".to_string())
        );
    }

    /// FastAPI returns validation errors as a list; the messages are what the user
    /// needs, not the raw structure.
    #[test]
    fn a_validation_detail_is_flattened() {
        let body = serde_json::json!({"detail": [
            {"loc": ["body", "email"], "msg": "value is not a valid email address"},
            {"loc": ["body", "password"], "msg": "field required"}
        ]});
        let detail = extract_detail(&body).unwrap();
        assert!(detail.contains("not a valid email address"));
        assert!(detail.contains("field required"));
    }

    #[test]
    fn a_body_without_detail_yields_nothing() {
        assert_eq!(extract_detail(&serde_json::json!({})), None);
        assert_eq!(extract_detail(&serde_json::json!({"detail": []})), None);
        assert_eq!(extract_detail(&serde_json::json!({"detail": 42})), None);
    }

    // ── Token parsing ──

    #[test]
    fn a_login_response_is_parsed() {
        let body = serde_json::json!({
            "access_token": "eyJhbGciOi",
            "refresh_token": "eyJyZWZyZXNo",
            "token_type": "bearer",
            "expires_in": 1800
        });
        let tokens = parse_tokens(&body).unwrap();
        assert_eq!(tokens.access_token, "eyJhbGciOi");
        assert_eq!(tokens.refresh_token.as_deref(), Some("eyJyZWZyZXNo"));
        assert_eq!(tokens.expires_in, 1800);
    }

    /// A web-style response with no refresh token must be an error, and the message
    /// must point at the platform header — that is the actual cause.
    #[test]
    fn a_missing_refresh_token_mentions_the_platform_header() {
        let body = serde_json::json!({
            "access_token": "a",
            "token_type": "bearer",
            "expires_in": 1800
        });
        let err = parse_tokens(&body).unwrap_err();
        assert!(
            err.to_string().contains("X-Client-Platform"),
            "die Meldung muss die Ursache nennen: {err}"
        );
    }

    #[test]
    fn default_token_type_is_assumed_when_absent() {
        let body = serde_json::json!({
            "access_token": "a", "refresh_token": "r", "expires_in": 60
        });
        assert_eq!(parse_tokens(&body).unwrap().token_type, "bearer");
    }
}
