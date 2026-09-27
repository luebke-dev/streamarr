//! Update checks.
//!
//! This command reports whether an update is available. It does **not** install one: the
//! download and the signature check belong to Tauri's updater plugin, and doing them here
//! would mean a second code path whose verification could drift from the plugin's.
//!
//! # The endpoint is not the server
//!
//! A detail worth stating, because the intuitive assumption is the opposite: the update
//! feed does **not** come from the Streamarr instance the user is logged into.
//!
//! The app is a client. `ProfileStore` holds a list of servers, each with its own
//! `ServerAddress` (`desktop/player/src/profile.rs`), and the active one says where *media
//! and games* come from. The update endpoint, by contrast, is a static value compiled into
//! the bundle, and it has to point somewhere that exists independently of any instance:
//!
//!   * A feed served by the instance would mean the operator of whatever server a user
//!     typed in controls the code their machine runs. That is not a thing to build.
//!   * There is no canonical instance for the app to ask. With two profiles, which one?
//!   * Every self-hosted deployment would have to carry and maintain desktop bundles.
//!
//! Measured: the server does not even check the client's version (no `X-Client-Version`
//! handling in `backend/src/streamarr`), so app and server versions are genuinely
//! independent — both happen to read `2026.2.1`, but nothing couples them. An endpoint
//! tied to the instance would invent a dependency that does not exist.
//!
//! The endpoint is therefore the project's release feed, configured in `tauri.conf.json`.
//!
//! # Why a check can also say "cannot"
//!
//! Three answers are possible and they must not be conflated: an update is available; there
//! is none; or this build cannot check. The third is not an error to show — being offline
//! is normal — but it *is* worth a log line, because "this build was never configured for
//! updates" and "the feed is briefly unreachable" look identical from the outside and have
//! nothing in common.

use streamarr_desktop_player::updater::{
    is_configured, Channel, CheckOutcome, Release, UpdateDecision, UpdatePolicy,
};

use crate::api::ApiError;

/// What the frontend receives.
#[derive(Debug, Clone, serde::Serialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateCheck {
    /// Whether this build can update itself at all.
    pub configured: bool,
    /// Whether the user should be told something.
    pub user_visible: bool,
    /// A released version to install, when there is one.
    pub version: Option<String>,
    /// A line for the log, always present.
    pub detail: String,
}

/// The channel this build follows.
///
/// Read from the build's own version unless the user has chosen otherwise: a build whose
/// version carries a pre-release suffix is a beta build, and treating it as stable would
/// strand it — it would never receive the next beta, and would wait for a stable release
/// that may be weeks away.
pub fn channel_for_version(version: &str) -> Channel {
    let has_prerelease = version
        .split_once(['-', '+'])
        .map(|(_, suffix)| !suffix.to_ascii_lowercase().starts_with("release"))
        .unwrap_or(false);
    if has_prerelease {
        Channel::Beta
    } else {
        Channel::Stable
    }
}

/// Decides what the endpoint's answer means for this build.
///
/// Pure, so the decision can be tested without a network — and so the reason for "no
/// update" is available for the log rather than being inferred from silence.
pub fn evaluate(
    current_version: &str,
    channel: Channel,
    endpoint: Option<&str>,
    pubkey: Option<&str>,
    release: Option<&Release>,
) -> CheckOutcome {
    if !is_configured(endpoint, pubkey) {
        return CheckOutcome::NotConfigured {
            detail: match (endpoint, pubkey) {
                (None | Some(""), _) => "kein Update-Endpunkt im Bundle hinterlegt".to_string(),
                (_, None | Some("")) => "kein öffentlicher Signierschlüssel hinterlegt".to_string(),
                _ => "der hinterlegte Signierschlüssel ist noch der Platzhalter".to_string(),
            },
        };
    }

    let Some(release) = release else {
        // Configured, reachable, but the feed named no release. Not an error: a feed with
        // no releases yet is exactly what a project looks like before its first one.
        return CheckOutcome::Unavailable {
            detail: "der Update-Feed nennt keine Version".to_string(),
        };
    };

    match UpdatePolicy::new(current_version, channel).decide(release) {
        UpdateDecision::Update { version } => CheckOutcome::Available { version },
        UpdateDecision::NoUpdate { reason } => CheckOutcome::UpToDate { reason },
    }
}

/// Asks the release feed what the newest release is.
///
/// Kept separate from [`evaluate`] so the decision is testable without a network, and so a
/// failure to reach the feed cannot be mistaken for "no update available".
pub async fn fetch_release(endpoint: &str) -> Result<Option<Release>, ApiError> {
    // Deliberately its own client, with no token and no profile: the update feed belongs to
    // the project, not to whichever server the user happens to be logged into. Sending the
    // user's credentials there would leak them to a third party, and applying the profile's
    // `resolve_override` would be meaningless for a public host.
    let response = reqwest::Client::builder()
        .timeout(std::time::Duration::from_secs(20))
        .user_agent(concat!("Streamarr-Desktop/", env!("CARGO_PKG_VERSION")))
        .build()
        .map_err(|e| ApiError::Unexpected(e.to_string()))?
        .get(endpoint)
        .header("Accept", "application/json")
        .send()
        .await
        .map_err(|e| ApiError::Unexpected(e.to_string()))?;

    let status = response.status();
    if !status.is_success() {
        // A 404 is the normal answer for a project that has not published a release yet, so
        // it is reported as "no release" rather than as a failure. Anything else is a real
        // problem and travels as an error — the caller logs it either way.
        if status == reqwest::StatusCode::NOT_FOUND {
            return Ok(None);
        }
        return Err(ApiError::Unexpected(format!(
            "Der Update-Feed antwortete mit HTTP {status}."
        )));
    }

    let body = response
        .text()
        .await
        .map_err(|e| ApiError::Unexpected(e.to_string()))?;
    Ok(parse_feed(&body))
}

/// Reads the release out of the feed's JSON.
///
/// Tolerant on purpose. The feed format is Tauri's, and the field carrying the channel is
/// not part of it — a project that labels its releases does so in the version's suffix. So
/// the version is taken from `version`, the channel is inferred from that version, and a
/// feed the app cannot read yields `None` rather than an error, because the caller's answer
/// to both is the same: no update.
pub fn parse_feed(body: &str) -> Option<Release> {
    let value: serde_json::Value = serde_json::from_str(body).ok()?;
    let version = value.get("version")?.as_str()?.to_string();
    if version.trim().is_empty() {
        return None;
    }
    Some(Release {
        channel: Some(channel_for_version(&version).as_str().to_string()),
        version,
    })
}

/// Checks for an update and reports the outcome without installing anything.
#[tauri::command]
pub async fn check_for_update(app: tauri::AppHandle) -> Result<UpdateCheck, String> {
    let current = app.package_info().version.to_string();

    let config = app
        .config()
        .plugins
        .0
        .get("updater")
        .cloned()
        .unwrap_or_default();

    let endpoint = config
        .get("endpoints")
        .and_then(|v| v.as_array())
        .and_then(|v| v.first())
        .and_then(|v| v.as_str())
        .map(str::to_string);
    let pubkey = config
        .get("pubkey")
        .and_then(|v| v.as_str())
        .map(str::to_string);

    let channel = channel_for_version(&current);

    let release = match endpoint.as_deref() {
        Some(endpoint) if is_configured(endpoint.into(), pubkey.as_deref()) => {
            fetch_release(endpoint).await.ok().flatten()
        }
        _ => None,
    };

    let outcome = evaluate(
        &current,
        channel,
        endpoint.as_deref(),
        pubkey.as_deref(),
        release.as_ref(),
    );

    // Always logged, never thrown: "it says it is up to date" should be answerable from a
    // log file rather than by guessing which of the three cases occurred.
    log::info!("{}", outcome.describe());

    Ok(UpdateCheck {
        configured: outcome.is_configured(),
        user_visible: outcome.is_user_visible(),
        version: match &outcome {
            CheckOutcome::Available { version } => Some(version.clone()),
            _ => None,
        },
        detail: outcome.describe(),
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    const REAL_KEY: &str = "RWQsomeBase64LookingPublicKey";
    const ENDPOINT: &str = "https://example.test/latest.json";

    #[test]
    fn a_release_build_follows_the_stable_channel() {
        assert_eq!(channel_for_version("2026.2.1"), Channel::Stable);
        assert_eq!(channel_for_version("v2026.2.1"), Channel::Stable);
        // An explicit release marker is a release, not a pre-release.
        assert_eq!(channel_for_version("2026.2.1-release"), Channel::Stable);
    }

    #[test]
    fn a_beta_build_follows_the_beta_channel() {
        // Otherwise a beta build waits for a stable release instead of receiving the next
        // beta, which is the opposite of why anyone installs one.
        assert_eq!(channel_for_version("2026.3.0-beta.1"), Channel::Beta);
        assert_eq!(channel_for_version("2026.3.0-rc.2"), Channel::Beta);
    }

    #[test]
    fn an_unconfigured_build_reports_that_plainly() {
        let outcome = evaluate("2026.2.1", Channel::Stable, Some(ENDPOINT), None, None);
        assert!(matches!(outcome, CheckOutcome::NotConfigured { .. }));
        assert!(!outcome.is_configured());
        assert!(!outcome.is_user_visible());
    }

    #[test]
    fn a_placeholder_key_counts_as_unconfigured() {
        let outcome = evaluate(
            "2026.2.1",
            Channel::Stable,
            Some(ENDPOINT),
            Some(streamarr_desktop_player::updater::PUBKEY_PLACEHOLDER),
            None,
        );
        assert!(!outcome.is_configured());
    }

    #[test]
    fn a_configured_build_with_a_newer_release_offers_it() {
        let release = Release {
            version: "2026.3.0".to_string(),
            channel: Some("stable".to_string()),
        };
        let outcome = evaluate(
            "2026.2.1",
            Channel::Stable,
            Some(ENDPOINT),
            Some(REAL_KEY),
            Some(&release),
        );
        assert_eq!(
            outcome,
            CheckOutcome::Available {
                version: "2026.3.0".to_string()
            }
        );
        assert!(outcome.is_user_visible());
    }

    #[test]
    fn a_configured_build_up_to_date_explains_why() {
        let release = Release {
            version: "2026.2.1".to_string(),
            channel: Some("stable".to_string()),
        };
        let outcome = evaluate(
            "2026.2.1",
            Channel::Stable,
            Some(ENDPOINT),
            Some(REAL_KEY),
            Some(&release),
        );
        assert!(matches!(outcome, CheckOutcome::UpToDate { .. }));
        assert!(!outcome.is_user_visible());
        // The detail names the numbers, so a user asking "why does it say up to date" can
        // be answered from a log.
        assert!(outcome.describe().contains("2026.2.1"));
    }

    #[test]
    fn a_feed_without_a_release_is_not_an_error() {
        // A project before its first release.
        let outcome = evaluate(
            "2026.2.1",
            Channel::Stable,
            Some(ENDPOINT),
            Some(REAL_KEY),
            None,
        );
        assert!(matches!(outcome, CheckOutcome::Unavailable { .. }));
        assert!(!outcome.is_user_visible());
    }

    #[test]
    fn the_feed_version_is_read_and_its_channel_inferred() {
        let release = parse_feed(r#"{"version":"2026.3.0","notes":"x","pub_date":"y"}"#)
            .expect("a plain feed");
        assert_eq!(release.version, "2026.3.0");
        assert_eq!(release.channel.as_deref(), Some("stable"));

        let beta = parse_feed(r#"{"version":"2026.3.0-beta.1"}"#).expect("a beta feed");
        assert_eq!(beta.channel.as_deref(), Some("beta"));
    }

    #[test]
    fn an_unreadable_feed_yields_nothing_rather_than_an_error() {
        // The caller's answer to "unreadable" and "no update" is the same, and a feed the
        // app cannot parse must not become an install.
        assert!(parse_feed("not json").is_none());
        assert!(parse_feed("{}").is_none());
        assert!(parse_feed(r#"{"version":""}"#).is_none());
        assert!(parse_feed(r#"{"version":42}"#).is_none());
    }

    #[test]
    fn a_beta_release_is_never_offered_to_a_release_build() {
        // The whole point of the channel, checked through this module's own entry point.
        let release = Release {
            version: "2026.3.0-beta.1".to_string(),
            channel: Some("beta".to_string()),
        };
        let outcome = evaluate(
            "2026.2.1",
            Channel::Stable,
            Some(ENDPOINT),
            Some(REAL_KEY),
            Some(&release),
        );
        assert!(!outcome.is_user_visible());
        assert!(matches!(outcome, CheckOutcome::UpToDate { .. }));
    }
}
