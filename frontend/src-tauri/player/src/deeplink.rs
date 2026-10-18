//! Deep links: `streamarr://…` URLs arriving from outside the app.
//!
//! The one that matters is the OIDC login return. With a browser-based identity provider
//! the flow is: the app opens the system browser, the user authenticates there, and the
//! provider redirects to a URL the *operating system* hands back to the app. That is the
//! only way a native app can receive a login from an external browser — and it is why
//! this exists rather than simply reading the tokens from a redirect inside the webview,
//! which would be a different (and less safe) flow.
//!
//! # Why the parsing is here and not in the shell's window code
//!
//! Because it is the part with decisions in it, and because a URL arriving from the
//! operating system is **untrusted input**. Any program on the machine can ask the
//! desktop environment to open `streamarr://…`, so the handler must assume the payload is
//! hostile until it has been classified. Keeping the classification pure means every case
//! — including the ones that should be rejected — is testable without launching the app.
//!
//! # What must never happen
//!
//! A deep link must not be able to make the app send credentials anywhere. So the links
//! this module accepts carry **no** tokens and **no** server addresses: a login link says
//! only "the user authenticated, go and finish the exchange". The exchange itself is a
//! code-for-token call the shell makes to *its own configured server*, with the state
//! value checked. A link that carries an access token, or a server address, is rejected
//! rather than honoured — that is the shape a phishing attempt would take, and the app
//! has no reason to ever receive one legitimately.

use std::collections::HashMap;

/// The scheme the app registers with the operating system.
pub const SCHEME: &str = "streamarr";

/// Where the app is listening and at what address.
///
/// The address matters for the same reason [`crate::plan`] cares: the app reaches its
/// server through an IP pin that a browser cannot apply. The OIDC exchange therefore
/// happens in the shell, not in the browser.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DeepLink {
    pub kind: DeepLinkKind,
    /// Raw parameters, kept for the state check and for logging.
    pub params: HashMap<String, String>,
}

/// What a link asks the app to do.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeepLinkKind {
    /// An OIDC login finished; exchange the code.
    ///
    /// Carries `code` and `state`; both are required, because an exchange without a state
    /// value cannot be checked against the one the app stored before opening the browser,
    /// and an unchecked exchange is a login-CSRF.
    Login,
    /// The user came back without completing authentication.
    LoginError {
        /// The provider's error code, e.g. `access_denied`.
        error: String,
    },
    /// A link to one item, `streamarr://item/<guid>`.
    OpenItem { guid: String },
    /// A recognised scheme with an unknown action.
    Unknown { action: String },
}

/// Why a link was refused.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DeepLinkError {
    /// Not the app's scheme at all, so it is not the app's business.
    WrongScheme { scheme: String },
    /// The scheme is right but there is nothing to do.
    Empty,
    /// A login link that carries something a login link must never carry.
    ///
    /// Named separately from a generic parse failure because it is a *security* outcome,
    /// and worth logging as one.
    Refused { reason: String },
    /// Malformed beyond classification.
    Malformed { reason: String },
}

impl std::fmt::Display for DeepLinkError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::WrongScheme { scheme } => {
                write!(
                    f,
                    "Der Link gehört nicht zu dieser App (Schema `{scheme}`)."
                )
            }
            Self::Empty => write!(f, "Der Link enthält keine Aktion."),
            Self::Refused { reason } => write!(f, "Der Link wurde abgelehnt: {reason}"),
            Self::Malformed { reason } => write!(f, "Der Link ist unlesbar: {reason}"),
        }
    }
}

impl std::error::Error for DeepLinkError {}

/// Parameters a login deep link must **never** carry.
///
/// A link with any of these is refused, and the refusal is a deliberate security decision
/// rather than tidiness. If a link could name a server, `streamarr://login?code=…` from a
/// hostile source could direct the code exchange at an attacker's endpoint. If it could
/// carry a token, the app would be accepting credentials over a channel that any local
/// program can write to.
const FORBIDDEN_LOGIN_PARAMS: [&str; 6] = [
    "access_token",
    "refresh_token",
    "token",
    "server",
    "server_url",
    "base_url",
];

/// Splits a URL into scheme, action and parameters.
///
/// Written by hand rather than with a URL crate because the forms that arrive here are not
/// all valid URLs: `streamarr://item/abc` has an empty authority, and some desktop
/// environments append a trailing slash or pass the whole thing percent-encoded. Being
/// strict about URL syntax would reject links that are in fact fine.
fn split(raw: &str) -> Result<(String, String, HashMap<String, String>), DeepLinkError> {
    let trimmed = raw.trim();
    if trimmed.is_empty() {
        return Err(DeepLinkError::Empty);
    }

    let without_scheme = match trimmed.split_once("://") {
        Some((scheme, rest)) => {
            let scheme = scheme.to_ascii_lowercase();
            if scheme != SCHEME {
                return Err(DeepLinkError::WrongScheme { scheme });
            }
            rest
        }
        // `streamarr:item/abc` is a valid form too; the `//` is only a convention.
        None => match trimmed.split_once(':') {
            Some((scheme, rest)) => {
                let scheme = scheme.to_ascii_lowercase();
                if scheme != SCHEME {
                    return Err(DeepLinkError::WrongScheme { scheme });
                }
                rest.trim_start_matches("//")
            }
            None => {
                return Err(DeepLinkError::Malformed {
                    reason: "kein Schema".to_string(),
                })
            }
        },
    };

    // Parameters first, so the action is what is left.
    let (path_part, query) = match without_scheme.split_once('?') {
        Some((path, query)) => (path, query),
        None => (without_scheme, ""),
    };
    let params = parse_query(query);

    // A `#` fragment behaves like a query for OIDC responses, because the fragment is what
    // the provider uses for implicit-flow replies. Both are read.
    let (path_part, fragment) = match path_part.split_once('#') {
        Some((path, fragment)) => (path, fragment),
        None => (path_part, ""),
    };
    let mut params = params;
    params.extend(parse_query(fragment));

    let path = path_part.trim_matches('/');
    // The first segment is the action; the rest belongs to it.
    let (action, remainder) = match path.split_once('/') {
        Some((action, rest)) => (action.to_string(), rest.to_string()),
        None => (path.to_string(), String::new()),
    };

    if action.is_empty() {
        return Err(DeepLinkError::Empty);
    }
    Ok((action.to_ascii_lowercase(), remainder, params))
}

/// Reads `a=1&b=2`, percent-decoding both sides.
///
/// A malformed pair is skipped rather than failing the whole link: a provider appending
/// something unexpected should not stop a login that is otherwise complete.
fn parse_query(query: &str) -> HashMap<String, String> {
    let mut out = HashMap::new();
    for pair in query.split('&') {
        let Some((key, value)) = pair.split_once('=') else {
            continue;
        };
        let key = percent_decode(key);
        if key.is_empty() {
            continue;
        }
        out.insert(key, percent_decode(value));
    }
    out
}

/// Decodes `%XX` and `+`.
///
/// `+` as space is technically form encoding rather than URL encoding, but providers use
/// it and refusing to would break some of them for no benefit.
fn percent_decode(value: &str) -> String {
    let bytes = value.as_bytes();
    let mut out: Vec<u8> = Vec::with_capacity(bytes.len());
    let mut index = 0;
    while index < bytes.len() {
        match bytes[index] {
            b'%' if index + 2 < bytes.len() => {
                let hex = std::str::from_utf8(&bytes[index + 1..index + 3]).unwrap_or("");
                match u8::from_str_radix(hex, 16) {
                    Ok(byte) => {
                        out.push(byte);
                        index += 3;
                    }
                    Err(_) => {
                        // Not a valid escape: keep it literally, so a stray `%` in a title
                        // does not swallow the characters after it.
                        out.push(bytes[index]);
                        index += 1;
                    }
                }
            }
            b'+' => {
                out.push(b' ');
                index += 1;
            }
            byte => {
                out.push(byte);
                index += 1;
            }
        }
    }
    String::from_utf8_lossy(&out).to_string()
}

/// Classifies a deep link.
///
/// Returns a [`DeepLinkKind`] for a link worth acting on, or a [`DeepLinkError`] for one
/// that must be refused. A refusal is a normal outcome, not a crash: any local program can
/// send the app a link, so hostile input is expected rather than exceptional.
pub fn parse(raw: &str) -> Result<DeepLink, DeepLinkError> {
    let (action, remainder, params) = split(raw)?;

    let kind = match action.as_str() {
        // Spelled several ways by different providers and by the server's own redirect
        // helper, so several are accepted for the same thing.
        "login" | "auth" | "callback" => {
            if let Some(error) = params.get("error") {
                return Ok(DeepLink {
                    kind: DeepLinkKind::LoginError {
                        error: error.clone(),
                    },
                    params,
                });
            }

            // The security check. A link that names a token or a server is refused, and
            // the message says which field, so the log explains a real attempt rather than
            // looking like a parsing bug.
            for forbidden in FORBIDDEN_LOGIN_PARAMS {
                if params.contains_key(forbidden) {
                    return Err(DeepLinkError::Refused {
                        reason: format!(
                            "Ein Anmelde-Link darf `{forbidden}` nicht enthalten — die \
                             Anmeldung wird ausschließlich mit dem konfigurierten Server \
                             abgeschlossen."
                        ),
                    });
                }
            }

            // Both are required: without `state` the reply cannot be checked against what
            // the app sent before opening the browser, which is a login-CSRF.
            match (params.get("code"), params.get("state")) {
                (Some(_), Some(_)) => DeepLinkKind::Login,
                (None, _) => {
                    return Err(DeepLinkError::Malformed {
                        reason: "kein `code` im Anmelde-Link".to_string(),
                    })
                }
                (_, None) => {
                    return Err(DeepLinkError::Malformed {
                        reason: "kein `state` im Anmelde-Link — die Antwort wäre nicht \
                                 prüfbar"
                            .to_string(),
                    })
                }
            }
        }
        // `streamarr://item/<guid>` and `streamarr://open/<guid>` — the action may carry
        // the id as its remainder.
        "item" | "open" => {
            let guid = if !remainder.is_empty() {
                remainder.trim_matches('/').to_string()
            } else {
                params.get("guid").cloned().unwrap_or_default()
            };
            if guid.is_empty() {
                return Err(DeepLinkError::Malformed {
                    reason: "keine Kennung im Link".to_string(),
                });
            }
            DeepLinkKind::OpenItem { guid }
        }
        other => DeepLinkKind::Unknown {
            action: other.to_string(),
        },
    };

    Ok(DeepLink { kind, params })
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_login_link_is_recognised() {
        let link = parse("streamarr://login?code=abc123&state=xyz").unwrap();
        assert_eq!(link.kind, DeepLinkKind::Login);
        assert_eq!(link.params.get("code").unwrap(), "abc123");
        assert_eq!(link.params.get("state").unwrap(), "xyz");
    }

    #[test]
    fn the_alternate_spellings_are_all_accepted() {
        // The server's redirect helper and various providers use different paths for the
        // same thing; refusing two of the three would break a working configuration.
        for url in [
            "streamarr://login?code=c&state=s",
            "streamarr://auth?code=c&state=s",
            "streamarr://callback?code=c&state=s",
            "streamarr:login?code=c&state=s",
        ] {
            assert_eq!(parse(url).unwrap().kind, DeepLinkKind::Login, "{url}");
        }
    }

    #[test]
    fn the_scheme_is_checked_case_insensitively() {
        // Operating systems are inconsistent about the case they hand back.
        assert_eq!(
            parse("Streamarr://login?code=c&state=s").unwrap().kind,
            DeepLinkKind::Login
        );
    }

    #[test]
    fn another_apps_link_is_not_our_business() {
        // Registering the scheme means other apps' links arrive here too; they must be
        // declined without noise rather than treated as an error to report.
        let error = parse("https://example.com/login?code=c&state=s").unwrap_err();
        assert!(
            matches!(error, DeepLinkError::WrongScheme { ref scheme } if scheme == "https"),
            "{error:?}"
        );
    }

    #[test]
    fn a_login_link_without_a_state_is_refused() {
        // Without `state` the reply cannot be matched to the request the app made before
        // opening the browser. Accepting it would be a login-CSRF: an attacker could hand
        // the app their own authorization code and have the user logged into the
        // attacker's account.
        let error = parse("streamarr://login?code=abc").unwrap_err();
        assert!(
            matches!(error, DeepLinkError::Malformed { ref reason } if reason.contains("state")),
            "{error:?}"
        );
    }

    #[test]
    fn a_login_link_without_a_code_is_refused() {
        let error = parse("streamarr://login?state=xyz").unwrap_err();
        assert!(
            matches!(error, DeepLinkError::Malformed { ref reason } if reason.contains("code")),
            "{error:?}"
        );
    }

    #[test]
    fn a_login_link_carrying_a_token_is_refused() {
        // The shape a phishing attempt takes. Any local program can open the app with a
        // link, so the app must never accept credentials over that channel.
        for url in [
            "streamarr://login?code=c&state=s&access_token=stolen",
            "streamarr://login?code=c&state=s&refresh_token=stolen",
            "streamarr://login?code=c&state=s&token=stolen",
        ] {
            let error = parse(url).unwrap_err();
            assert!(
                matches!(error, DeepLinkError::Refused { .. }),
                "{url} should be refused, got {error:?}"
            );
        }
    }

    #[test]
    fn a_login_link_naming_a_server_is_refused() {
        // The important one. If a link could choose the server, it could direct the
        // code-for-token exchange at an attacker's endpoint, which would hand them the
        // authorization code.
        for url in [
            "streamarr://login?code=c&state=s&server=https://evil.example",
            "streamarr://login?code=c&state=s&server_url=https://evil.example",
            "streamarr://login?code=c&state=s&base_url=https://evil.example",
        ] {
            let error = parse(url).unwrap_err();
            assert!(
                matches!(error, DeepLinkError::Refused { .. }),
                "{url} should be refused, got {error:?}"
            );
        }
    }

    #[test]
    fn the_refusal_names_the_field_so_the_log_is_useful() {
        let error = parse("streamarr://login?code=c&state=s&server=x").unwrap_err();
        let text = error.to_string();
        assert!(text.contains("server"), "{text}");
        assert!(
            text.contains("konfigurierten Server"),
            "the message must say what happens instead: {text}"
        );
    }

    #[test]
    fn a_provider_error_is_reported_as_such_rather_than_as_a_parse_failure() {
        // `access_denied` is a normal outcome when a user cancels at the provider, and the
        // interface should say so rather than showing "malformed link".
        let link = parse("streamarr://login?error=access_denied&error_description=Nope").unwrap();
        assert_eq!(
            link.kind,
            DeepLinkKind::LoginError {
                error: "access_denied".to_string()
            }
        );
        // And an error link does not need a code, because there is nothing to exchange.
        assert!(link.params.contains_key("error_description"));
    }

    #[test]
    fn an_item_link_is_recognised_in_both_shapes() {
        let by_path = parse("streamarr://item/9b0308f3-9426-4e92-b765-1b05d87ed656").unwrap();
        assert_eq!(
            by_path.kind,
            DeepLinkKind::OpenItem {
                guid: "9b0308f3-9426-4e92-b765-1b05d87ed656".to_string()
            }
        );

        let by_query = parse("streamarr://open?guid=abc-123").unwrap();
        assert_eq!(
            by_query.kind,
            DeepLinkKind::OpenItem {
                guid: "abc-123".to_string()
            }
        );
    }

    #[test]
    fn an_item_link_without_an_id_is_refused() {
        assert!(matches!(
            parse("streamarr://item").unwrap_err(),
            DeepLinkError::Malformed { .. }
        ));
        assert!(matches!(
            parse("streamarr://item/").unwrap_err(),
            DeepLinkError::Malformed { .. }
        ));
    }

    #[test]
    fn an_unknown_action_is_reported_rather_than_ignored() {
        // So a newer app version's link does not fail silently in an older build.
        let link = parse("streamarr://settings/audio").unwrap();
        assert_eq!(
            link.kind,
            DeepLinkKind::Unknown {
                action: "settings".to_string()
            }
        );
    }

    #[test]
    fn percent_encoded_values_are_decoded() {
        // A `return_to` path arrives encoded, and a state value may contain anything.
        let link = parse("streamarr://login?code=a%2Fb%2Bc&state=x%3Dy").unwrap();
        assert_eq!(link.kind, DeepLinkKind::Login);
        assert_eq!(link.params.get("code").unwrap(), "a/b+c");
        assert_eq!(link.params.get("state").unwrap(), "x=y");
    }

    #[test]
    fn a_lone_percent_sign_does_not_swallow_what_follows() {
        // A malformed escape must not eat the rest of the value.
        let link = parse("streamarr://login?code=100%&state=s").unwrap();
        assert_eq!(link.params.get("code").unwrap(), "100%");
    }

    #[test]
    fn a_fragment_is_read_like_a_query() {
        // Implicit-flow replies put the parameters in the fragment.
        let link = parse("streamarr://login#code=abc&state=xyz").unwrap();
        assert_eq!(link.kind, DeepLinkKind::Login);
        assert_eq!(link.params.get("state").unwrap(), "xyz");
    }

    #[test]
    fn a_trailing_slash_does_not_change_the_action() {
        assert_eq!(
            parse("streamarr://login/?code=c&state=s").unwrap().kind,
            DeepLinkKind::Login
        );
    }

    #[test]
    fn an_empty_or_foreign_link_is_refused_without_panicking() {
        assert!(matches!(parse("").unwrap_err(), DeepLinkError::Empty));
        assert!(matches!(parse("   ").unwrap_err(), DeepLinkError::Empty));
        assert!(matches!(
            parse("streamarr://").unwrap_err(),
            DeepLinkError::Empty
        ));
        assert!(matches!(
            parse("nonsense").unwrap_err(),
            DeepLinkError::Malformed { .. }
        ));
    }

    #[test]
    fn a_link_with_an_unexpected_extra_parameter_is_still_accepted() {
        // Providers add parameters at will; refusing over one would break logins for
        // reasons no user could act on.
        let link = parse("streamarr://login?code=c&state=s&session_state=abc&iss=https%3A%2F%2Fx")
            .unwrap();
        assert_eq!(link.kind, DeepLinkKind::Login);
    }

    #[test]
    fn the_scheme_constant_matches_what_is_registered() {
        // The shell registers the scheme with the operating system; this is the one place
        // the two could drift apart, and a mismatch means deep links silently never
        // arrive.
        assert_eq!(SCHEME, "streamarr");
    }
}
