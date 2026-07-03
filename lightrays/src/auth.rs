//! JWT verification, principal extraction, and WebSocket ticket minting.
//!
//! The HTTP layer in `server.rs` calls into this module; auth has no
//! dependency on `AppState` or `Session` so it can be unit-tested in
//! isolation.

use axum::{http::StatusCode, Json};
use jsonwebtoken::{DecodingKey, EncodingKey, Header, Validation};
use serde::{Deserialize, Serialize};
use std::time::{SystemTime, UNIX_EPOCH};

pub type AuthError = (StatusCode, Json<serde_json::Value>);

#[derive(Debug, Clone)]
pub struct Principal {
    pub subject: String,
    pub scopes: Vec<String>,
}

impl Principal {
    pub fn anonymous() -> Self {
        Self {
            subject: "anonymous".to_string(),
            scopes: vec!["lightrays:admin".to_string()],
        }
    }

    pub fn has_scope(&self, wanted: &str) -> bool {
        self.scopes.iter().any(|scope| scope == wanted)
    }

    /// Returns true if this principal owns the session or holds the admin
    /// scope. Callers pass `session.owner_sub` rather than the full
    /// `Session` to keep this module independent of session-store types.
    pub fn can_access(&self, owner_sub: &str) -> bool {
        self.subject == owner_sub || self.has_scope("lightrays:admin")
    }
}

/// JWT claims accepted by Lightrays. `sub` and `exp` are required so sessions
/// can be bound to an authenticated principal instead of merely a valid token.
#[derive(Debug, Clone, Deserialize, Serialize)]
pub struct JwtClaims {
    pub sub: String,
    pub exp: usize,
    #[serde(default)]
    pub iat: Option<usize>,
    #[serde(default)]
    pub scope: Option<String>,
    #[serde(default)]
    pub sid: Option<String>,
}

/// Validate a raw JWT string against the shared secret.
fn verify_jwt(token: &str, secret: &str) -> Result<JwtClaims, AuthError> {
    let key = DecodingKey::from_secret(secret.as_bytes());
    let mut validation = Validation::new(jsonwebtoken::Algorithm::HS256);
    validation.required_spec_claims = ["exp", "sub"].iter().map(|s| s.to_string()).collect();
    validation.validate_exp = true;
    validation.validate_aud = false;

    let data = jsonwebtoken::decode::<JwtClaims>(token, &key, &validation).map_err(|e| {
        log::warn!("JWT verification failed: {e}");
        (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "Invalid or expired token"})),
        )
    })?;
    Ok(data.claims)
}

fn principal_from_claims(claims: &JwtClaims) -> Principal {
    let scopes = claims
        .scope
        .as_deref()
        .unwrap_or("")
        .split_whitespace()
        .map(str::to_string)
        .collect();
    Principal {
        subject: claims.sub.clone(),
        scopes,
    }
}

/// Extract and verify a Bearer token from request headers.
/// If `secret` is empty, auth is disabled and this always succeeds with an
/// anonymous admin principal.
pub fn verify_bearer(
    headers: &axum::http::HeaderMap,
    secret: &str,
) -> Result<Principal, AuthError> {
    if secret.is_empty() {
        return Ok(Principal::anonymous());
    }

    let auth_header = headers
        .get("authorization")
        .and_then(|v| v.to_str().ok())
        .unwrap_or("");

    let token = auth_header.strip_prefix("Bearer ").ok_or_else(|| {
        (
            StatusCode::UNAUTHORIZED,
            Json(serde_json::json!({"error": "Missing Authorization header"})),
        )
    })?;

    let claims = verify_jwt(token, secret)?;
    Ok(principal_from_claims(&claims))
}

/// Extract and verify a WebSocket ticket from either Authorization or
/// Sec-WebSocket-Protocol. Query-string tokens are intentionally not accepted.
pub fn verify_ws_token(
    headers: &axum::http::HeaderMap,
    secret: &str,
    session_id: &str,
) -> Result<Principal, AuthError> {
    if secret.is_empty() {
        return Ok(Principal::anonymous());
    }

    // Try Authorization header first for non-browser clients.
    if let Some(auth) = headers.get("authorization").and_then(|v| v.to_str().ok()) {
        if let Some(token) = auth.strip_prefix("Bearer ") {
            let claims = verify_jwt(token, secret)?;
            return Ok(principal_from_claims(&claims));
        }
    }

    if let Some(protocols) = headers
        .get("sec-websocket-protocol")
        .and_then(|v| v.to_str().ok())
    {
        let ticket = protocols
            .split(',')
            .map(str::trim)
            .find(|value| !value.is_empty() && *value != "lightrays");
        if let Some(ticket) = ticket {
            let claims = verify_jwt(ticket, secret)?;
            let scopes = principal_from_claims(&claims);
            if !scopes.has_scope("lightrays:ws") {
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(serde_json::json!({"error": "Invalid WebSocket ticket scope"})),
                ));
            }
            if claims.sid.as_deref() != Some(session_id) {
                return Err((
                    StatusCode::UNAUTHORIZED,
                    Json(serde_json::json!({"error": "WebSocket ticket does not match session"})),
                ));
            }
            return Ok(scopes);
        }
    }

    Err((
        StatusCode::UNAUTHORIZED,
        Json(serde_json::json!({"error": "Missing WebSocket ticket"})),
    ))
}

/// Mint a short-lived ticket scoped to a specific session. Returns `None`
/// when JWT auth is disabled or signing fails.
pub fn create_ws_ticket(
    secret: &str,
    ttl_secs: u64,
    principal: &Principal,
    session_id: &str,
) -> Option<String> {
    if secret.is_empty() {
        return None;
    }
    let now = unix_now();
    let claims = JwtClaims {
        sub: principal.subject.clone(),
        exp: (now + ttl_secs) as usize,
        iat: Some(now as usize),
        scope: Some("lightrays:ws".to_string()),
        sid: Some(session_id.to_string()),
    };
    jsonwebtoken::encode(
        &Header::new(jsonwebtoken::Algorithm::HS256),
        &claims,
        &EncodingKey::from_secret(secret.as_bytes()),
    )
    .map_err(|e| log::error!("Failed to create WebSocket ticket: {}", e))
    .ok()
}

fn unix_now() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

/// Legacy WebSocket query parameters. Tokens in the URL are rejected; this
/// exists only so old clients get a controlled 401 instead of a parse error.
#[derive(Deserialize)]
pub struct WsAuthQuery {
    #[allow(dead_code)]
    pub token: Option<String>,
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderMap;

    fn mint(secret: &str, sub: &str, scope: Option<&str>, sid: Option<&str>) -> String {
        let now = unix_now();
        let claims = JwtClaims {
            sub: sub.to_string(),
            exp: (now + 60) as usize,
            iat: Some(now as usize),
            scope: scope.map(str::to_string),
            sid: sid.map(str::to_string),
        };
        jsonwebtoken::encode(
            &Header::new(jsonwebtoken::Algorithm::HS256),
            &claims,
            &EncodingKey::from_secret(secret.as_bytes()),
        )
        .unwrap()
    }

    #[test]
    fn anonymous_principal_has_admin_scope() {
        let p = Principal::anonymous();
        assert!(p.has_scope("lightrays:admin"));
    }

    #[test]
    fn can_access_owner_or_admin() {
        let owner = Principal {
            subject: "alice".into(),
            scopes: vec![],
        };
        let stranger = Principal {
            subject: "bob".into(),
            scopes: vec![],
        };
        let admin = Principal {
            subject: "svc".into(),
            scopes: vec!["lightrays:admin".into()],
        };
        assert!(owner.can_access("alice"));
        assert!(!stranger.can_access("alice"));
        assert!(admin.can_access("alice"));
    }

    #[test]
    fn bearer_disabled_when_secret_empty() {
        let headers = HeaderMap::new();
        let p = verify_bearer(&headers, "").expect("auth disabled");
        assert_eq!(p.subject, "anonymous");
    }

    #[test]
    fn bearer_accepts_valid_token() {
        let token = mint("topsecret", "alice", Some("lightrays:user"), None);
        let mut headers = HeaderMap::new();
        headers.insert("authorization", format!("Bearer {token}").parse().unwrap());
        let p = verify_bearer(&headers, "topsecret").expect("token accepted");
        assert_eq!(p.subject, "alice");
        assert!(p.has_scope("lightrays:user"));
    }

    #[test]
    fn ws_ticket_rejects_wrong_session() {
        let ticket = mint("k", "alice", Some("lightrays:ws"), Some("session-a"));
        let mut headers = HeaderMap::new();
        headers.insert(
            "sec-websocket-protocol",
            format!("lightrays, {ticket}").parse().unwrap(),
        );
        let err = verify_ws_token(&headers, "k", "session-b").expect_err("sid mismatch");
        assert_eq!(err.0, StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn ws_ticket_rejects_missing_scope() {
        let ticket = mint("k", "alice", Some("other"), Some("s1"));
        let mut headers = HeaderMap::new();
        headers.insert(
            "sec-websocket-protocol",
            format!("lightrays, {ticket}").parse().unwrap(),
        );
        let err = verify_ws_token(&headers, "k", "s1").expect_err("missing scope");
        assert_eq!(err.0, StatusCode::UNAUTHORIZED);
    }

    #[test]
    fn ws_ticket_accepts_matched_subprotocol() {
        let ticket = mint("k", "alice", Some("lightrays:ws"), Some("s1"));
        let mut headers = HeaderMap::new();
        headers.insert(
            "sec-websocket-protocol",
            format!("lightrays, {ticket}").parse().unwrap(),
        );
        let p = verify_ws_token(&headers, "k", "s1").expect("ticket valid");
        assert_eq!(p.subject, "alice");
    }
}
