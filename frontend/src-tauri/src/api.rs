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
            .map_err(|e| ApiError::Unexpected(e.to_string()))?;
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
            .map_err(|e| LoginError::Transport(e.to_string()))?;

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
            .map_err(|e| RefreshError::Transport(e.to_string()))?;

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
