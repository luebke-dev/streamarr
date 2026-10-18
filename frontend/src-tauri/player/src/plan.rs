//! From a play response to an actual mpv invocation.
//!
//! The pieces for this exist in three other modules — [`crate::playback`] decides *what*
//! to play and where to resume, [`crate::mpv`] builds the process arguments, and
//! [`crate::profile`] holds the user's preferences — but nothing joined them up. This
//! module is that join, and it is deliberately **pure**: it turns decisions into a plan
//! without starting a process or opening a socket, so the whole path is testable without
//! a server, without mpv and without a display.
//!
//! # Two problems it solves that are easy to get wrong
//!
//! ## The resume position must reach mpv, and there are two ways to do it
//!
//! `--start=<position>` is simple but makes mpv treat the file as seekable from the
//! start in a way that interacts badly with `--save-position-on-quit`; mpv's own
//! `start` property set *after* loading does the same job. More importantly, an
//! argument list is easy to test and hard to get subtly wrong, so the position goes in
//! as an argument — and a golden test pins that it is present, because a missing resume
//! argument silently restarts the film from the beginning, which looks like a feature
//! that "sometimes doesn't work".
//!
//! ## The server address must be reachable by a process that cannot be told about DNS
//!
//! This is the awkward one. The app's HTTP client applies the profile's IP pin by
//! connecting to a different address while keeping the hostname for TLS
//! ([`crate::profile::ServerAddress::resolve_pair`]). **mpv has no equivalent of curl's
//! `--resolve`** (checked against mpv 0.41: no such option), so a URL handed to mpv goes
//! through the system resolver, which for this deployment returns a dead address —
//! requests then hang. Spike 0.3 worked around it by bind-mounting a patched `/etc/hosts`
//! into a mount namespace, which needs root and is not something an application can do.
//!
//! So the plan states the problem instead of hiding it: [`PlaybackPlan::stream_host`]
//! and [`PlaybackPlan::resolve_target`] are both filled in, and the shell decides how to
//! reconcile them — today by writing a temporary `--hosts-entries` style override where
//! mpv supports one, or by asking the user to fix DNS. What must *not* happen is the
//! silent version, where the app knows the working address and streams anyway into a
//! twenty-second hang.

use serde::{Deserialize, Serialize};

use crate::mpv::{HdrMode, PlayerOptions};
use crate::playback::{PlayResponse, TrackPreference};
use crate::profile::{Preferences, Profile, ServerAddress};

/// Everything needed to start playback, decided in advance.
///
/// Kept as data rather than executed directly so the decision can be inspected — by
/// tests, by the UI and by the log — separately from the side effects.
#[derive(Debug, Clone, PartialEq)]
pub struct PlaybackPlan {
    /// The URL handed to mpv.
    pub url: String,
    /// The hostname inside that URL, which TLS must be validated against.
    pub stream_host: String,
    /// The address the connection must actually go to, when the profile pins one.
    pub resolve_target: Option<String>,
    /// Where playback starts, in seconds.
    pub start_position: f64,
    /// Whether the position came from a stored resume point, for the UI to mention.
    pub is_resuming: bool,
    /// Whether the server is re-encoding, which the UI should say out loud.
    pub is_transcode: bool,
    /// The user's language preferences, already resolved to concrete choices.
    pub tracks: TrackPreference,
    /// mpv arguments built from the plan.
    pub options: PlayerOptions,
}

impl PlaybackPlan {
    /// The `aid`/`sid` values mpv should be given, as property calls.
    ///
    /// Separate from `options` because mpv wants these *after* the file is loaded —
    /// the track list does not exist before that, which is defect 5 of spike 0.3.
    pub fn track_properties(&self) -> Vec<(&'static str, serde_json::Value)> {
        let mut out = Vec::new();
        if let Some(value) = self.tracks.audio_choice().mpv_value() {
            out.push(("aid", value));
        }
        if let Some(value) = self.tracks.subtitle_choice().mpv_value() {
            out.push(("sid", value));
        }
        out
    }

    /// Whether the app must do something about name resolution before playing.
    ///
    /// `true` means the URL's hostname does not resolve to the pinned address for an
    /// ordinary process, so handing the URL to mpv unchanged would hang. The shell must
    /// either make the name resolve or the user must be told.
    pub fn needs_resolution_help(&self) -> bool {
        self.resolve_target.is_some()
    }
}

/// Why a plan could not be made.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlanError {
    /// The response named no playable URL — normally a transcode without a session.
    NoUrl(String),
}

impl std::fmt::Display for PlanError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::NoUrl(method) => write!(
                f,
                "Für diese Wiedergabe gibt es keine abspielbare Adresse \
                 (Verfahren: {method}). Der Server hat die Datei abgelehnt und \
                 keinen Ersatz geliefert."
            ),
        }
    }
}

impl std::error::Error for PlanError {}

/// Builds the plan for one playback.
///
/// `stored_position` and `already_played` come from the user's viewing history for this
/// item; `duration` prefers the server's own value in the play response, falling back to
/// what the history reports.
#[allow(clippy::too_many_arguments)]
pub fn plan_playback(
    response: &PlayResponse,
    server: &ServerAddress,
    profile: &Profile,
    config_dir: &std::path::Path,
    stored_position: f64,
    stored_duration: Option<f64>,
    already_played: bool,
    hdr: HdrMode,
) -> Result<PlaybackPlan, PlanError> {
    let base = server.base_url();
    let url = response
        .url_for_player(&base)
        .map_err(|_| PlanError::NoUrl(response.method.as_str().to_string()))?;

    // The server's duration is the one that matches the stream being played; the stored
    // one may belong to a different file version.
    let duration = response.duration.or(stored_duration);

    // The policy is built from the user's preference rather than the default, so
    // "ask before transcoding" in the profile actually has an effect.
    let policy = crate::playback::ResumePolicy {
        confirm_transcode: profile.preferences.confirm_transcode,
        ..Default::default()
    };
    let decision = policy.decide(stored_position, duration, already_played);

    let preferences: &Preferences = &profile.preferences;
    let tracks = TrackPreference {
        audio_index: None,
        subtitle_index: None,
        audio_language: preferences.audio_language.clone(),
        subtitle_language: preferences.subtitle_language.clone(),
    };

    let mut options = PlayerOptions {
        config_dir: config_dir.to_path_buf(),
        fullscreen: preferences.fullscreen_on_play,
        hdr,
        ..Default::default()
    };
    if let Some(argument) = hls_auth_argument(response) {
        options.extra_args.push(argument);
    }

    Ok(PlaybackPlan {
        url,
        stream_host: server.host().unwrap_or_default().to_string(),
        resolve_target: resolve_target_for(server),
        start_position: decision.position(),
        is_resuming: decision.is_resuming(),
        is_transcode: !response.is_direct_play(),
        tracks,
        options,
    })
}

/// The address mpv should be sent to, when the profile pins one.
///
/// `None` when the profile has no pin: then the system resolver is the only authority,
/// which is correct for a normally-configured server.
pub fn resolve_target_for(server: &ServerAddress) -> Option<String> {
    server
        .resolve_pair()
        .and_then(|pair| pair.rsplit_once(':').map(|(_, ip)| ip.to_string()))
}

/// The mpv argument that carries the play token to *every* request of a transcoded
/// stream, when one is needed.
///
/// `None` for direct play, where the URL's own `?token=` is enough.
///
/// # Why a header, and why this is not optional
///
/// Transcoding produces an HLS manifest, and the server serves it **byte for byte as
/// ffmpeg wrote it** — it does not rewrite anything. The segment URIs inside are plain
/// relative names (`<session>_000.ts`). A relative reference resolved against a base
/// that has a query string **drops the query** (RFC 3986, §5.3), so every segment
/// request arrives without a token and is answered with `401 No play token provided`.
///
/// Measured rather than deduced: with the manifest loaded, all 124 segment attempts of
/// one playback were refused, and mpv's log ends with `avformat_open_input() failed`
/// while the position never left 0. The manifest itself has `?token=` and loads fine,
/// which is what makes this so easy to miss — the picture is simply black and nothing
/// says why.
///
/// The server's `_verify_play_token` accepts the token from an `Authorization: Bearer`
/// header as well as from the query, and ffmpeg applies the headers given here to every
/// request in the HLS chain rather than to the manifest alone. So one argument closes the
/// gap without touching the server.
///
/// The token is the **play** token, not the account token: it is scoped to this session
/// and expires, which is why handing it to mpv is not the same as handing over a session.
pub fn hls_auth_argument(response: &PlayResponse) -> Option<String> {
    if response.is_direct_play() {
        return None;
    }
    Some(format!(
        "--http-header-fields=Authorization: Bearer {}",
        response.token
    ))
}

/// The mpv arguments for a plan, ready to spawn.
///
/// Built here rather than in the shell so the URL and the resume position cannot be
/// forgotten by a caller that only remembered the options.
pub fn arguments_for(plan: &PlaybackPlan) -> Vec<String> {
    let mut args = plan.options.to_args();
    if plan.start_position > 0.0 {
        args.push(format!("--start={:.3}", plan.start_position));
    }
    args.push(plan.url.clone());
    args
}

/// Something the user should be told before or during playback.
///
/// **Why these are variants and not sentences.** The first version returned finished
/// German sentences from the core crate, which was wrong on two counts: the interface's
/// default language is `en-US`, so most users would have read German; and a sentence
/// cannot be translated once it has been assembled, because word order and the position
/// of the number differ between languages. A variant carries the *fact*; the interface
/// renders it in the user's language.
///
/// Keeping them typed also means a new case cannot be added without the interface's
/// translation files being visibly incomplete — a stringly-typed `Vec<String>` would
/// simply show up as untranslated text.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind")]
pub enum PlaybackNotice {
    /// Playback continues from a stored position.
    ///
    /// The serialised tag is the interface's translation key — see [`Self::key`] — so
    /// there is exactly **one** name for each case. A second spelling (say
    /// `resolutionMismatch` on the wire and `resolution` in the key) would be a bug
    /// waiting to happen, and it nearly was: the first version of this enum had exactly
    /// that split.
    #[serde(rename = "resuming")]
    Resuming {
        /// Position in seconds; the interface formats it for the locale.
        position_seconds: f64,
    },
    /// The server must re-encode, which costs it capacity.
    #[serde(rename = "transcode")]
    Transcode,
    /// The name mpv would resolve does not lead to the pinned address.
    ///
    /// Worth naming plainly, because the symptom is confusing: the stream never starts
    /// and reports no error, while the rest of the app works normally.
    #[serde(rename = "resolution")]
    ResolutionMismatch,
}

impl PlaybackNotice {
    /// The key the interface looks up, under `playPage.nativePlayback.notice`.
    ///
    /// Kept in step with the serialised tag by a test, because two names for one thing is
    /// how a translation goes missing without anything failing.
    pub fn key(&self) -> &'static str {
        match self {
            Self::Resuming { .. } => "resuming",
            Self::Transcode => "transcode",
            Self::ResolutionMismatch => "resolution",
        }
    }
}

/// What the UI should tell the user about this playback.
///
/// Structured rather than textual: see [`PlaybackNotice`]. An empty list means there is
/// nothing to say, which is the normal case for a direct play from the beginning.
pub fn notices_for(plan: &PlaybackPlan) -> Vec<PlaybackNotice> {
    let mut notices = Vec::new();
    if plan.is_resuming {
        notices.push(PlaybackNotice::Resuming {
            position_seconds: plan.start_position,
        });
    }
    if plan.is_transcode {
        notices.push(PlaybackNotice::Transcode);
    }
    if plan.needs_resolution_help() {
        notices.push(PlaybackNotice::ResolutionMismatch);
    }
    notices
}

/// `H:MM:SS` or `M:SS`.
///
/// Used for log lines. The *user-facing* formatting happens in the interface, because the
/// position must be rendered per locale — this cannot be handed over as a finished
/// string without fixing the number format.
pub fn format_position(seconds: f64) -> String {
    let total = seconds.max(0.0).round() as u64;
    let (h, m, s) = (total / 3600, (total % 3600) / 60, total % 60);
    if h > 0 {
        format!("{h}:{m:02}:{s:02}")
    } else {
        format!("{m}:{s:02}")
    }
}

/// Whether a position is worth remembering on exit.
///
/// Wraps [`crate::playback::PlaybackReport::should_send`] so the shell has one place to
/// ask. The end-of-file case matters most: mpv reports a position equal to the duration
/// when it finishes, and reporting that would mark the item as played even when the user
/// only watched two minutes of the credits.
pub fn position_to_store(
    position: f64,
    duration: f64,
    ended: bool,
    resume_policy: &crate::playback::ResumePolicy,
) -> Option<f64> {
    if ended {
        return Some(0.0);
    }
    if !position.is_finite() || position < 0.0 {
        return None;
    }
    if duration > 0.0 && position >= duration - resume_policy.finished_margin_seconds {
        // Inside the end margin: the user has effectively finished it.
        return Some(0.0);
    }
    Some(position)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::mpv::HdrMode;
    use crate::playback::PlaybackMethod;
    use crate::profile::{Profile, ServerAddress};

    fn server() -> ServerAddress {
        ServerAddress::new("https://streamarr.luebke.internal")
    }

    fn profile() -> Profile {
        Profile::new("standard", "Standard", server())
    }

    fn response(method: PlaybackMethod) -> PlayResponse {
        let direct = matches!(method, PlaybackMethod::DirectPlay);
        PlayResponse {
            token: "t0ken".to_string(),
            session_id: Some("sess-1".to_string()),
            media_source_id: None,
            method,
            direct_stream: direct,
            duration: Some(3600.0),
            width: Some(1920),
            height: Some(1080),
            reasons: Default::default(),
        }
    }

    /// The defect this argument exists for, at unit level.
    ///
    /// The live run found it: the HLS manifest loaded and every segment was answered
    /// with `401 No play token provided`, because the manifest's relative segment URIs
    /// drop the `?token=` of the manifest URL. Nothing about the response says so.
    #[test]
    fn a_transcoded_plan_carries_the_play_token_as_a_header() {
        let response = response(PlaybackMethod::Transcode);
        let plan = plan_playback(
            &response,
            &server(),
            &profile(),
            std::path::Path::new("/tmp/conf"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .expect("Plan");

        assert!(plan.is_transcode);
        assert_eq!(
            hls_auth_argument(&response),
            Some("--http-header-fields=Authorization: Bearer t0ken".to_string())
        );
        // The argument must actually reach mpv, not merely exist as a helper: a plan
        // that computed it and dropped it would leave the same black picture.
        assert!(
            plan.options
                .extra_args
                .iter()
                .any(|a| a == "--http-header-fields=Authorization: Bearer t0ken"),
            "der Header fehlt in den mpv-Argumenten: {:?}",
            plan.options.extra_args
        );
    }

    #[test]
    fn a_direct_play_is_not_given_a_header_it_does_not_need() {
        // Direct play's URL carries `?token=` itself, and the file endpoint reads it from
        // there. Sending a header anyway would also work, which is exactly why the
        // distinction has to be asserted: without this test the `None` branch could be
        // deleted and nothing would fail.
        let response = response(PlaybackMethod::DirectPlay);
        assert_eq!(hls_auth_argument(&response), None);
    }

    #[test]
    fn the_header_argument_has_the_shape_mpv_expects() {
        // `--http-header-fields` takes a comma-separated list, so a malformed value here
        // is not rejected by mpv — it is silently ignored, and the stream fails with the
        // same 401 as if the argument were absent.
        let argument = hls_auth_argument(&response(PlaybackMethod::Transcode)).expect("Argument");
        let value = argument
            .strip_prefix("--http-header-fields=")
            .expect("das Argument muss die Option selbst tragen");
        let (name, token) = value
            .split_once(": ")
            .expect("Header im Format `Name: Wert`");
        assert_eq!(name, "Authorization");
        assert_eq!(token, "Bearer t0ken");
    }

    #[test]
    fn a_direct_play_is_planned_at_the_stream_endpoint() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        // The direct-file endpoint, not the HLS transcode path.
        assert!(
            plan.url.contains("/api/stream/file?token=t0ken"),
            "{}",
            plan.url
        );
        assert!(!plan.is_transcode);
        assert_eq!(plan.start_position, 0.0);
    }

    #[test]
    fn a_transcode_is_planned_and_flagged() {
        let plan = plan_playback(
            &response(PlaybackMethod::Transcode),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        assert!(plan.url.contains("playlist.m3u8"), "{}", plan.url);
        assert!(plan.is_transcode, "the UI must be able to say so");
    }

    #[test]
    fn a_transcode_without_a_session_is_an_error_and_not_a_black_window() {
        let mut resp = response(PlaybackMethod::Transcode);
        resp.session_id = None;
        let result = plan_playback(
            &resp,
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        );

        let err = result.unwrap_err();
        // The message must name the cause, because "playback failed" is not actionable.
        let text = err.to_string();
        assert!(text.contains("transcode"), "{text}");
    }

    #[test]
    fn a_stored_position_becomes_a_resume_and_reaches_the_arguments() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            600.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        assert_eq!(plan.start_position, 600.0);
        assert!(plan.is_resuming);
        // The argument must be there: without it the film silently restarts, which
        // looks like "resume sometimes doesn't work".
        let args = arguments_for(&plan);
        assert!(args.iter().any(|a| a == "--start=600.000"), "{args:?}");
        // And the URL still comes last, so mpv cannot mistake it for an option value.
        assert_eq!(args.last().unwrap(), &plan.url);
    }

    #[test]
    fn a_position_below_the_minimum_does_not_resume() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            5.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        assert_eq!(plan.start_position, 0.0);
        assert!(!plan.is_resuming);
        // And no `--start` argument at all, rather than `--start=0`.
        let args = arguments_for(&plan);
        assert!(!args.iter().any(|a| a.starts_with("--start")), "{args:?}");
    }

    #[test]
    fn a_played_item_starts_over_even_with_a_stored_position() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            1800.0,
            None,
            true,
            HdrMode::Auto,
        )
        .unwrap();
        assert_eq!(plan.start_position, 0.0, "the user's own action wins");
    }

    #[test]
    fn a_position_inside_the_credits_starts_over() {
        // 3600 - 120 = 3480 is inside the end margin.
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            3500.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();
        assert_eq!(plan.start_position, 0.0);
    }

    #[test]
    fn the_servers_duration_wins_over_the_stored_one() {
        // The stored duration may belong to a different file; the play response
        // describes what is actually being streamed. Here the stored value would make
        // 3500 look mid-film, the server's value puts it in the credits.
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            3500.0,
            Some(20000.0),
            false,
            HdrMode::Auto,
        )
        .unwrap();
        assert_eq!(plan.start_position, 0.0);
    }

    #[test]
    fn the_profile_decides_fullscreen_and_the_config_directory() {
        let mut prof = profile();
        prof.preferences.fullscreen_on_play = false;
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &prof,
            std::path::Path::new("/home/u/.config/media.streamarr.desktop"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        assert!(!plan.options.fullscreen);
        let args = arguments_for(&plan);
        // `--no-fullscreen` rather than nothing, so the profile's mpv.conf cannot
        // turn fullscreen back on against the user's wish.
        assert!(args.iter().any(|a| a == "--no-fullscreen"), "{args:?}");
        assert!(
            args.iter().any(|a| a.contains("media.streamarr.desktop")),
            "{args:?}"
        );
    }

    #[test]
    fn language_preferences_become_track_choices_applied_after_loading() {
        let mut prof = profile();
        prof.preferences.audio_language = Some("de".to_string());
        prof.preferences.subtitle_language = Some("de".to_string());
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &prof,
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        // A language is resolved by mpv after the file is loaded, so it must not be an
        // argument — mpv cannot match a language before it knows the tracks.
        assert!(
            plan.track_properties().is_empty(),
            "a language needs a lookup first"
        );
        assert!(plan.tracks.audio_choice().needs_lookup());
    }

    #[test]
    fn subtitles_off_stays_off() {
        let mut prof = profile();
        prof.preferences.subtitle_language = Some("none".to_string());
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &prof,
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        // `sid=no` is a property mpv accepts immediately, so it belongs in the
        // post-load calls.
        let props = plan.track_properties();
        assert_eq!(props.len(), 1, "{props:?}");
        assert_eq!(props[0].0, "sid");
        assert_eq!(props[0].1, serde_json::json!("no"));
    }

    #[test]
    fn the_pin_is_separated_from_the_hostname_so_tls_still_validates_it() {
        let mut srv = server();
        srv.resolve_override = Some("10.10.60.30:443".to_string());
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &srv,
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        // The hostname stays in the URL, because the certificate covers only
        // `*.luebke.internal` — putting the IP there would break TLS.
        assert!(
            plan.url.starts_with("https://streamarr.luebke.internal/"),
            "{}",
            plan.url
        );
        assert_eq!(plan.stream_host, "streamarr.luebke.internal");
        assert_eq!(plan.resolve_target.as_deref(), Some("10.10.60.30"));
        assert!(plan.needs_resolution_help());
    }

    #[test]
    fn without_a_pin_nothing_needs_resolution_help() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();
        assert_eq!(plan.resolve_target, None);
        assert!(!plan.needs_resolution_help());
    }

    #[test]
    fn the_hdr_mode_reaches_the_options() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Passthrough,
        )
        .unwrap();
        let args = arguments_for(&plan);
        assert!(
            args.iter().any(|a| a == "--target-colorspace-hint=yes"),
            "{args:?}"
        );
    }

    #[test]
    fn a_resume_is_announced_and_a_transcode_too() {
        let mut resp = response(PlaybackMethod::Transcode);
        resp.direct_stream = false;
        let plan = plan_playback(
            &resp,
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            600.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();

        let notices = notices_for(&plan);
        assert_eq!(notices.len(), 2, "{notices:?}");
        // The *fact* is reported, with the number as a number: the interface renders it
        // per locale, so a finished sentence here would be untranslatable.
        assert!(
            matches!(
                notices[0],
                PlaybackNotice::Resuming { position_seconds }
                    if (position_seconds - 600.0).abs() < 0.01
            ),
            "{notices:?}"
        );
        assert_eq!(notices[1], PlaybackNotice::Transcode);
    }

    #[test]
    fn a_plain_direct_play_from_the_start_has_nothing_to_say() {
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &server(),
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();
        assert!(notices_for(&plan).is_empty(), "no news is good news");
    }

    #[test]
    fn the_resolution_trouble_is_reported_as_its_own_case() {
        let mut srv = server();
        srv.resolve_override = Some("10.10.60.30:443".to_string());
        let plan = plan_playback(
            &response(PlaybackMethod::DirectPlay),
            &srv,
            &profile(),
            std::path::Path::new("/tmp/p"),
            0.0,
            None,
            false,
            HdrMode::Auto,
        )
        .unwrap();
        assert_eq!(notices_for(&plan), vec![PlaybackNotice::ResolutionMismatch]);
    }

    #[test]
    fn every_notice_has_a_translation_key() {
        // The interface looks these up in `playPage.nativePlayback.notice`. A new variant
        // without a key would render as a missing translation, so the keys are pinned
        // here — and a frontend test checks each key exists in every locale.
        for (notice, expected) in [
            (PlaybackNotice::Transcode, "transcode"),
            (PlaybackNotice::ResolutionMismatch, "resolution"),
            (
                PlaybackNotice::Resuming {
                    position_seconds: 1.0,
                },
                "resuming",
            ),
        ] {
            assert_eq!(notice.key(), expected);
        }
    }

    #[test]
    fn a_notice_serialises_with_its_key_as_the_tag() {
        // The interface switches on `kind` and then looks up exactly that key, so the two
        // must be the same string. A rename that touched only one of them would render as
        // a missing translation with nothing failing.
        let notices = [
            PlaybackNotice::Resuming {
                position_seconds: 300.0,
            },
            PlaybackNotice::Transcode,
            PlaybackNotice::ResolutionMismatch,
        ];
        for notice in notices {
            let json = serde_json::to_value(&notice).unwrap();
            assert_eq!(json["kind"], notice.key(), "{json}");
        }

        // The number stays a number under a snake_case name, matching the rest of the
        // wire contract (`item_guid`, `start_position`).
        let json = serde_json::to_value(PlaybackNotice::Resuming {
            position_seconds: 300.0,
        })
        .unwrap();
        assert_eq!(json["position_seconds"], 300.0);
    }

    #[test]
    fn positions_are_formatted_for_reading() {
        assert_eq!(format_position(0.0), "0:00");
        assert_eq!(format_position(9.0), "0:09");
        assert_eq!(format_position(600.0), "10:00");
        assert_eq!(format_position(3725.0), "1:02:05");
        // A negative or unusable value must not produce nonsense.
        assert_eq!(format_position(-5.0), "0:00");
    }

    #[test]
    fn reaching_the_end_stores_zero_so_the_item_is_not_marked_watched_by_the_credits() {
        let policy = crate::playback::ResumePolicy::default();
        // mpv reports position == duration when the file ends.
        assert_eq!(position_to_store(3600.0, 3600.0, true, &policy), Some(0.0));
        // Watching two minutes of credits is not watching the film.
        assert_eq!(position_to_store(3500.0, 3600.0, false, &policy), Some(0.0));
        // A real position in the middle is kept.
        assert_eq!(
            position_to_store(1200.0, 3600.0, false, &policy),
            Some(1200.0)
        );
        // Nothing usable reported yet.
        assert_eq!(position_to_store(f64::NAN, 3600.0, false, &policy), None);
    }

    #[test]
    fn the_confirmation_preference_is_honoured() {
        let mut prof = profile();
        prof.preferences.confirm_transcode = false;
        let mut resp = response(PlaybackMethod::Transcode);
        resp.direct_stream = false;

        // The policy built for the plan must carry the user's setting, otherwise the
        // preference exists but does nothing.
        let policy = crate::playback::ResumePolicy {
            confirm_transcode: prof.preferences.confirm_transcode,
            ..Default::default()
        };
        assert!(!resp.needs_transcode_confirmation(&policy));
    }
}
