//! Update channels and the decision whether to offer an update.
//!
//! The mechanism (downloading, verifying the signature, replacing the binary) belongs to
//! Tauri's updater plugin. What lives here is the *policy*: which channel a build follows,
//! which release that channel is allowed to offer, and what happens when the update
//! endpoint cannot be reached.
//!
//! # Why the policy is not left to the plugin
//!
//! Two of these decisions are the kind that go wrong quietly.
//!
//! **A channel is a promise.** Somebody who installs the stable build has said they do not
//! want to be a beta tester. If a beta release can be offered to a stable build — because
//! the comparison only looks at version numbers, and a beta may well carry the higher
//! number — then that promise is broken silently, on machines the maintainer never sees.
//! So the channel is checked *before* the version, not after.
//!
//! **A build must not update itself backwards.** Version comparison by string is wrong:
//! `"2026.10.0" < "2026.9.0"` in lexicographic order, so a build would be told that an
//! older release is newer and install it. The comparison here is numeric per component.
//!
//! **A failed update check is not an error the user needs to see.** Being offline is
//! normal. But refusing to start because the update endpoint is unreachable would be far
//! worse than not updating — which is why [`UpdatePolicy`] separates "no update" from
//! "could not tell", and why the shell logs the second and shows nothing.
//!
//! # What is not here
//!
//! Signature verification. That is not a policy choice and must not become one: an update
//! the app installs is code it will run, so an unsigned or badly signed update must be
//! refused by the updater plugin, which is configured with a public key and has no
//! setting to skip the check. Deliberately absent from this module, because a field here
//! that could weaken it would eventually be used.

use serde::{Deserialize, Serialize};

/// Which releases a build follows.
#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Channel {
    /// Released versions only. The default, and the safe direction: a build that is
    /// uncertain which channel it follows updates *less*, never more.
    #[default]
    Stable,
    /// Release candidates and betas as well.
    Beta,
}

impl Channel {
    /// Reads a channel from configuration, falling back to stable.
    ///
    /// Falls back rather than failing: an unreadable or misspelled value must not leave a
    /// build with *no* channel, and the safe direction is the one that updates less.
    pub fn parse(value: &str) -> Self {
        match value.trim().to_ascii_lowercase().as_str() {
            "beta" | "testing" | "preview" => Self::Beta,
            _ => Self::Stable,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Stable => "stable",
            Self::Beta => "beta",
        }
    }

    /// Whether a release from `release_channel` may be offered to this channel.
    ///
    /// Stable accepts only stable; beta accepts both. A beta build that could not receive
    /// stable releases would be stranded the moment it wanted to come back.
    pub fn accepts(self, release_channel: Channel) -> bool {
        match self {
            Self::Stable => release_channel == Self::Stable,
            Self::Beta => true,
        }
    }
}

/// A version, split into numeric components.
///
/// The project's versions look like `2026.2.1`, but a pre-release suffix is possible in
/// principle, so it is stripped rather than rejected — a version the app cannot parse must
/// not stop it from updating.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Version {
    components: Vec<u64>,
    /// Whether this is a pre-release (`-beta.1`).
    prerelease: bool,
}

impl Version {
    /// Parses a version, or `None` when there is nothing numeric to compare.
    pub fn parse(text: &str) -> Option<Self> {
        let trimmed = text.trim().trim_start_matches('v');
        let (numbers, suffix) = match trimmed.split_once(['-', '+']) {
            Some((numbers, suffix)) => (numbers, Some(suffix)),
            None => (trimmed, None),
        };

        let components: Vec<u64> = numbers
            .split('.')
            .map_while(|part| part.trim().parse::<u64>().ok())
            .collect();
        if components.is_empty() {
            return None;
        }

        // No suffix at all, or an explicit release marker, counts as a release.
        let prerelease = suffix
            .map(|suffix| {
                let lower = suffix.to_ascii_lowercase();
                !(lower.starts_with("release") || lower.starts_with("final"))
            })
            .unwrap_or(false);

        Some(Self {
            components,
            prerelease,
        })
    }

    /// Compares two versions, numerically per component.
    ///
    /// Missing components count as zero, so `1.2` and `1.2.0` are the same version.
    pub fn is_newer_than(&self, other: &Self) -> bool {
        let length = self.components.len().max(other.components.len());
        for index in 0..length {
            let mine = self.components.get(index).copied().unwrap_or(0);
            let theirs = other.components.get(index).copied().unwrap_or(0);
            if mine != theirs {
                return mine > theirs;
            }
        }
        // Same numbers: a release beats a pre-release of the same version, so a beta build
        // is offered the final release of the version it is already on.
        other.prerelease && !self.prerelease
    }
}

/// A release as the update endpoint describes it.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Release {
    pub version: String,
    #[serde(default)]
    pub channel: Option<String>,
}

/// What to do about a release.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UpdateDecision {
    /// This release should be installed.
    Update { version: String },
    /// There is nothing to do, with the reason — so a log line explains a user's "it says
    /// it is up to date" instead of leaving them guessing.
    NoUpdate { reason: NoUpdateReason },
}

/// Why a release is not being offered.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase", tag = "kind")]
pub enum NoUpdateReason {
    /// The offered version is the same or older.
    NotNewer { offered: String, current: String },
    /// The release belongs to a channel this build does not follow.
    WrongChannel {
        offered: String,
        build_channel: String,
    },
    /// The offered version could not be read.
    UnreadableVersion { offered: String },
}

impl std::fmt::Display for NoUpdateReason {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NotNewer { offered, current } => write!(
                f,
                "Angeboten wird {offered}, installiert ist {current} — kein Update."
            ),
            Self::WrongChannel {
                offered,
                build_channel,
            } => write!(
                f,
                "Angeboten wird {offered}, dieser Build folgt aber dem Kanal \
                 `{build_channel}`. Beta-Versionen werden nur an Beta-Builds ausgeliefert."
            ),
            Self::UnreadableVersion { offered } => write!(
                f,
                "Die Versionsnummer `{offered}` ist nicht lesbar — es wird nichts \
                 installiert."
            ),
        }
    }
}

/// The policy for one build.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct UpdatePolicy {
    pub current_version: String,
    pub channel: Channel,
}

impl UpdatePolicy {
    pub fn new(current_version: impl Into<String>, channel: Channel) -> Self {
        Self {
            current_version: current_version.into(),
            channel,
        }
    }

    /// Decides whether to offer a release.
    ///
    /// The channel is checked **before** the version. The other order would let a beta
    /// with a higher number be offered to a stable build, which breaks the promise the
    /// channel makes — and does so silently.
    pub fn decide(&self, release: &Release) -> UpdateDecision {
        let release_channel = release
            .channel
            .as_deref()
            .map(Channel::parse)
            .unwrap_or(Channel::Stable);

        if !self.channel.accepts(release_channel) {
            return UpdateDecision::NoUpdate {
                reason: NoUpdateReason::WrongChannel {
                    offered: release.version.clone(),
                    build_channel: self.channel.as_str().to_string(),
                },
            };
        }

        let Some(offered) = Version::parse(&release.version) else {
            return UpdateDecision::NoUpdate {
                reason: NoUpdateReason::UnreadableVersion {
                    offered: release.version.clone(),
                },
            };
        };

        // An unreadable *current* version is not a reason to refuse an update: a build
        // that cannot read its own version is more in need of an update, not less. Any
        // readable offered version is then treated as newer.
        match Version::parse(&self.current_version) {
            Some(current) if !offered.is_newer_than(&current) => UpdateDecision::NoUpdate {
                reason: NoUpdateReason::NotNewer {
                    offered: release.version.clone(),
                    current: self.current_version.clone(),
                },
            },
            _ => UpdateDecision::Update {
                version: release.version.clone(),
            },
        }
    }
}

/// The placeholder that stands where the signing key's public half belongs.
///
/// Public keys are not secrets — this one is compiled into every bundle and is meant to be
/// readable. The placeholder exists because a release build must carry the *real* key, and
/// a build that shipped the placeholder would otherwise promise an update mechanism it
/// cannot honour: the updater would refuse every download at signature verification, and
/// the user would see a failure that looks like a broken server rather than an unconfigured
/// build.
pub const PUBKEY_PLACEHOLDER: &str = "PLACEHOLDER_REPLACE_WITH_THE_TAURI_UPDATER_PUBLIC_KEY";

/// Whether this build can update itself at all.
///
/// A separate question from "is there an update", and the answer must be honest: an app
/// that checks and fails on every start teaches users to ignore its messages.
pub fn is_configured(endpoint: Option<&str>, pubkey: Option<&str>) -> bool {
    let endpoint = endpoint.unwrap_or("").trim();
    let pubkey = pubkey.unwrap_or("").trim();

    !endpoint.is_empty()
        && !pubkey.is_empty()
        && pubkey != PUBKEY_PLACEHOLDER
        // A key that is still half-replaced is not a key. Checked because the failure mode
        // is a signature error at update time, far from the cause.
        && !pubkey.to_ascii_uppercase().contains("PLACEHOLDER")
}

/// What a check produced, including the possibility that it could not run.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum CheckOutcome {
    /// A release to install.
    Available { version: String },
    /// The check ran and there is nothing to install.
    UpToDate { reason: NoUpdateReason },
    /// The check could not run.
    ///
    /// Not an error to show the user. Being offline is normal, and an app that complains
    /// about a failed update check on every start is an app people learn to ignore — which
    /// is worse, because then a real problem is ignored too.
    Unavailable { detail: String },
    /// This build has no update endpoint or no signing key.
    ///
    /// Distinct from `Unavailable`, because it is not a transient condition: retrying will
    /// not help, and the reason — this build was not configured for updates — is something
    /// the maintainer needs in the log, not the user.
    NotConfigured { detail: String },
}

impl CheckOutcome {
    /// A one-line description for the log.
    pub fn describe(&self) -> String {
        match self {
            Self::Available { version } => format!("Update verfügbar: {version}"),
            Self::UpToDate { reason } => format!("Kein Update: {reason}"),
            Self::Unavailable { detail } => {
                format!("Update-Prüfung nicht möglich: {detail}")
            }
            Self::NotConfigured { detail } => {
                format!("Automatische Updates sind für diesen Build nicht eingerichtet: {detail}")
            }
        }
    }

    /// Whether this build can check for updates at all.
    pub fn is_configured(&self) -> bool {
        !matches!(self, Self::NotConfigured { .. })
    }

    /// Whether the user should be told anything.
    ///
    /// Only an available update is worth interrupting for. The other two are log lines.
    pub fn is_user_visible(&self) -> bool {
        matches!(self, Self::Available { .. })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn release(version: &str, channel: Option<&str>) -> Release {
        Release {
            version: version.to_string(),
            channel: channel.map(str::to_string),
        }
    }

    #[test]
    fn a_newer_stable_release_is_offered() {
        let policy = UpdatePolicy::new("2026.2.1", Channel::Stable);
        assert_eq!(
            policy.decide(&release("2026.3.0", Some("stable"))),
            UpdateDecision::Update {
                version: "2026.3.0".to_string()
            }
        );
    }

    #[test]
    fn a_release_is_compared_numerically_not_as_text() {
        // The bug this prevents: `"2026.10.0" < "2026.9.0"` in lexicographic order, so a
        // string comparison would tell a build that an *older* release is newer and it
        // would install it — a silent downgrade.
        let policy = UpdatePolicy::new("2026.9.0", Channel::Stable);
        assert_eq!(
            policy.decide(&release("2026.10.0", Some("stable"))),
            UpdateDecision::Update {
                version: "2026.10.0".to_string()
            }
        );

        // And the reverse must not be offered.
        let policy = UpdatePolicy::new("2026.10.0", Channel::Stable);
        assert!(matches!(
            policy.decide(&release("2026.9.0", Some("stable"))),
            UpdateDecision::NoUpdate {
                reason: NoUpdateReason::NotNewer { .. }
            }
        ));
    }

    #[test]
    fn a_beta_is_never_offered_to_a_stable_build() {
        // The promise the stable channel makes. Checked *before* the version, because a
        // beta may well carry the higher number.
        let policy = UpdatePolicy::new("2026.2.1", Channel::Stable);
        let decision = policy.decide(&release("2026.3.0-beta.1", Some("beta")));

        // Refused for the channel reason, not the version reason — the distinction is what
        // makes the log line actionable.
        match decision {
            UpdateDecision::NoUpdate {
                reason: NoUpdateReason::WrongChannel { .. },
            } => {}
            other => panic!("expected a channel refusal, got {other:?}"),
        }
    }

    #[test]
    fn a_beta_build_accepts_both_channels() {
        // A beta build that could not receive stable releases would be stranded the moment
        // it wanted to come back to stable.
        let policy = UpdatePolicy::new("2026.2.1-beta.1", Channel::Beta);
        assert!(matches!(
            policy.decide(&release("2026.2.2-beta.1", Some("beta"))),
            UpdateDecision::Update { .. }
        ));
        assert!(matches!(
            policy.decide(&release("2026.3.0", Some("stable"))),
            UpdateDecision::Update { .. }
        ));
    }

    #[test]
    fn a_release_without_a_channel_is_treated_as_stable() {
        // The safer direction, and the common case for an endpoint that does not label
        // its releases.
        let policy = UpdatePolicy::new("2026.2.1", Channel::Beta);
        assert!(matches!(
            policy.decide(&release("2026.3.0", None)),
            UpdateDecision::Update { .. }
        ));
    }

    #[test]
    fn the_same_version_is_not_an_update() {
        let policy = UpdatePolicy::new("2026.2.1", Channel::Stable);
        assert!(matches!(
            policy.decide(&release("2026.2.1", Some("stable"))),
            UpdateDecision::NoUpdate {
                reason: NoUpdateReason::NotNewer { .. }
            }
        ));
    }

    #[test]
    fn trailing_zero_components_do_not_make_a_version_newer() {
        // `1.2` and `1.2.0` are the same release, and offering "an update" that changes
        // nothing would train users to ignore the prompt.
        assert!(!Version::parse("1.2")
            .unwrap()
            .is_newer_than(&Version::parse("1.2.0").unwrap()));
        assert!(!Version::parse("1.2.0")
            .unwrap()
            .is_newer_than(&Version::parse("1.2").unwrap()));
        assert!(Version::parse("1.2.1")
            .unwrap()
            .is_newer_than(&Version::parse("1.2").unwrap()));
    }

    #[test]
    fn a_release_beats_a_pre_release_of_the_same_version() {
        // A build on `1.2.0-beta.1` should be offered `1.2.0` — otherwise it would never
        // reach the final release of the version it is already on.
        let beta = Version::parse("1.2.0-beta.1").unwrap();
        let final_release = Version::parse("1.2.0").unwrap();
        assert!(final_release.is_newer_than(&beta));
        assert!(!beta.is_newer_than(&final_release));
    }

    #[test]
    fn an_unreadable_offered_version_installs_nothing() {
        // The safe direction: an endpoint returning nonsense must not lead to installing
        // something the app could not evaluate.
        let policy = UpdatePolicy::new("2026.2.1", Channel::Stable);
        let decision = policy.decide(&release("not-a-version", Some("stable")));
        assert!(matches!(
            decision,
            UpdateDecision::NoUpdate {
                reason: NoUpdateReason::UnreadableVersion { .. }
            }
        ));
    }

    #[test]
    fn an_unreadable_current_version_still_allows_an_update() {
        // A build that cannot read its own version is more in need of updating, not less.
        let policy = UpdatePolicy::new("kaputt", Channel::Stable);
        assert!(matches!(
            policy.decide(&release("2026.3.0", Some("stable"))),
            UpdateDecision::Update { .. }
        ));
    }

    #[test]
    fn a_leading_v_is_accepted() {
        // A tag is often written `v2026.2.1`; refusing it would break updates for a
        // cosmetic reason.
        let policy = UpdatePolicy::new("v2026.2.1", Channel::Stable);
        assert!(matches!(
            policy.decide(&release("v2026.3.0", Some("stable"))),
            UpdateDecision::Update { .. }
        ));
    }

    #[test]
    fn a_channel_is_read_leniently_and_defaults_to_stable() {
        assert_eq!(Channel::parse("beta"), Channel::Beta);
        assert_eq!(Channel::parse("BETA"), Channel::Beta);
        assert_eq!(Channel::parse(" beta "), Channel::Beta);
        assert_eq!(Channel::parse("preview"), Channel::Beta);
        assert_eq!(Channel::parse("testing"), Channel::Beta);

        // An unknown or empty value must not leave a build without a channel, and the safe
        // direction is the one that updates less.
        assert_eq!(Channel::parse(""), Channel::Stable);
        assert_eq!(Channel::parse("stable"), Channel::Stable);
        assert_eq!(Channel::parse("nonsense"), Channel::Stable);
        assert_eq!(Channel::default(), Channel::Stable);
    }

    #[test]
    fn the_channel_names_round_trip() {
        for channel in [Channel::Stable, Channel::Beta] {
            assert_eq!(Channel::parse(channel.as_str()), channel);
        }
    }

    #[test]
    fn an_unavailable_check_is_not_shown_to_the_user() {
        // An app that complains about a failed update check on every start is an app whose
        // warnings people learn to ignore — and then a real one is ignored too.
        let offline = CheckOutcome::Unavailable {
            detail: "Zeitüberschreitung".to_string(),
        };
        assert!(!offline.is_user_visible());
        assert!(offline.describe().contains("nicht möglich"));
    }

    #[test]
    fn only_an_available_update_is_user_visible() {
        assert!(CheckOutcome::Available {
            version: "2026.3.0".to_string()
        }
        .is_user_visible());

        assert!(!CheckOutcome::UpToDate {
            reason: NoUpdateReason::NotNewer {
                offered: "2026.2.1".to_string(),
                current: "2026.2.1".to_string(),
            }
        }
        .is_user_visible());
    }

    #[test]
    fn every_outcome_describes_itself_for_the_log() {
        // So "it says it is up to date" can be answered from a log file rather than by
        // guessing.
        let outcomes = [
            CheckOutcome::Available {
                version: "2026.3.0".to_string(),
            },
            CheckOutcome::UpToDate {
                reason: NoUpdateReason::NotNewer {
                    offered: "2026.2.1".to_string(),
                    current: "2026.2.1".to_string(),
                },
            },
            CheckOutcome::UpToDate {
                reason: NoUpdateReason::WrongChannel {
                    offered: "2026.3.0-beta.1".to_string(),
                    build_channel: "stable".to_string(),
                },
            },
            CheckOutcome::Unavailable {
                detail: "offline".to_string(),
            },
        ];
        for outcome in outcomes {
            let text = outcome.describe();
            assert!(!text.trim().is_empty(), "{outcome:?}");
        }
    }

    #[test]
    fn the_reason_names_both_versions() {
        // "No update" without the numbers is unanswerable; with them the user can see that
        // their build is simply current.
        let policy = UpdatePolicy::new("2026.2.1", Channel::Stable);
        let text = policy
            .decide(&release("2026.2.0", Some("stable")))
            .to_string_for_test();
        assert!(text.contains("2026.2.0"), "{text}");
        assert!(text.contains("2026.2.1"), "{text}");
    }

    /// A small helper so the test above can read the reason as text.
    trait DescribeForTest {
        fn to_string_for_test(&self) -> String;
    }

    impl DescribeForTest for UpdateDecision {
        fn to_string_for_test(&self) -> String {
            match self {
                UpdateDecision::NoUpdate { reason } => reason.to_string(),
                UpdateDecision::Update { version } => format!("Update auf {version}"),
            }
        }
    }

    #[test]
    fn a_build_without_a_signing_key_does_not_pretend_to_update() {
        // The placeholder case: a bundle that carries the placeholder promises an update
        // mechanism it cannot honour. Saying so plainly is better than a signature error at
        // download time, which reads like a broken server.
        assert!(!is_configured(
            Some("https://example.test/latest.json"),
            Some(PUBKEY_PLACEHOLDER)
        ));
        // Any half-replaced variant counts as unconfigured too.
        assert!(!is_configured(
            Some("https://example.test/latest.json"),
            Some("PLACEHOLDER")
        ));
        // A key that was only half replaced, e.g. by a sed that missed the suffix.
        assert!(!is_configured(
            Some("https://example.test/latest.json"),
            Some("placeholder-2026")
        ));
        assert!(!is_configured(
            Some("https://example.test/latest.json"),
            Some("rwq_placeholder_key_data")
        ));
    }

    #[test]
    fn a_build_without_an_endpoint_does_not_pretend_to_update() {
        assert!(!is_configured(None, Some("RWQsomethingreal")));
        assert!(!is_configured(Some(""), Some("RWQsomethingreal")));
        assert!(!is_configured(Some("   "), Some("RWQsomethingreal")));
        assert!(!is_configured(Some("https://example.test/x.json"), None));
        assert!(!is_configured(
            Some("https://example.test/x.json"),
            Some("")
        ));
    }

    #[test]
    fn a_configured_build_is_recognised() {
        assert!(is_configured(
            Some("https://example.test/latest.json"),
            Some("RWQsomeBase64LookingPublicKey")
        ));
    }

    #[test]
    fn not_configured_is_never_shown_to_the_user_and_never_retried() {
        let outcome = CheckOutcome::NotConfigured {
            detail: "kein Signierschlüssel hinterlegt".to_string(),
        };
        assert!(!outcome.is_configured());
        assert!(!outcome.is_user_visible());
        // The log line must name the actual reason, so a maintainer can act on it.
        assert!(
            outcome.describe().contains("nicht eingerichtet"),
            "{outcome:?}"
        );
    }

    #[test]
    fn a_stable_build_walks_forward_through_a_sequence_of_releases() {
        // The realistic case, as a sequence: a build at 2026.2.1 must be offered the next
        // stable release and must not be offered a beta that appears in between.
        let mut current = "2026.2.1".to_string();
        let releases = [
            ("2026.3.0-beta.1", "beta"),
            ("2026.3.0", "stable"),
            ("2026.4.0-beta.2", "beta"),
            ("2026.4.0", "stable"),
        ];

        let mut installed = Vec::new();
        for (version, channel) in releases {
            let policy = UpdatePolicy::new(current.clone(), Channel::Stable);
            if let UpdateDecision::Update { version } =
                policy.decide(&release(version, Some(channel)))
            {
                current = version.clone();
                installed.push(version);
            }
        }

        assert_eq!(
            installed,
            vec!["2026.3.0".to_string(), "2026.4.0".to_string()],
            "only the stable releases, and each exactly once"
        );
    }
}
