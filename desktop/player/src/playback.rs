//! Playback decisions: direct play versus transcode, resume, progress reporting.
//!
//! Plan tasks 2.3, 2.5 and 2.9. This module is the *decision* layer between the REST
//! API, the mpv core and the UI. It holds no transport and no process, so all of it is
//! testable without a server — which matters, because the rules here are the ones that
//! silently get media wrong: resuming a film somebody already finished, or starting a
//! transcode the server did not need.
//!
//! # Why "resume" needs rules at all
//!
//! Three cases make the naive "start where the user stopped" wrong:
//!
//! * **A few seconds in.** The user opened it, watched the studio logos, closed it.
//!   Resuming at 0:07 is worse than starting over.
//! * **Almost at the end.** The last minutes are the credits. Resuming there means the
//!   film appears to end instantly and the user has to hunt for the start.
//! * **Marked as played.** The server already knows it is finished; resuming would
//!   contradict the user's own "mark as unwatched" action.
//!
//! The thresholds are [`ResumePolicy`] rather than constants so a viewer can change
//! them, and so each rule has a test that names the case it exists for.

use std::fmt;

use serde::{Deserialize, Serialize};

/// How the server wants this item delivered.
///
/// Derived from `playback_method` in the play response. The string is free-form on
/// the wire, so an unknown value is kept rather than rejected — a new server-side
/// method must not make the client refuse to play.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum PlaybackMethod {
    /// The original file, byte for byte. The goal: no server CPU, no quality loss.
    DirectPlay,
    /// The container or a track is remuxed without re-encoding the video.
    DirectStream,
    /// The server re-encodes. Costs the server a lot; the plan wants this confirmed
    /// rather than started silently.
    Transcode,
    /// A method this build does not know.
    Unknown(String),
}

impl PlaybackMethod {
    pub fn from_wire(value: &str) -> Self {
        // Normalised the way the server writes it: lower case, separators collapsed,
        // so `direct_play`, `DirectPlay` and `direct-play` are one method.
        let normalised: String = value
            .trim()
            .to_ascii_lowercase()
            .chars()
            .filter(|c| c.is_ascii_alphanumeric())
            .collect();
        match normalised.as_str() {
            "directplay" => Self::DirectPlay,
            "directstream" => Self::DirectStream,
            "transcode" => Self::Transcode,
            _ => Self::Unknown(value.to_string()),
        }
    }

    pub fn as_str(&self) -> &str {
        match self {
            Self::DirectPlay => "direct_play",
            Self::DirectStream => "direct_stream",
            Self::Transcode => "transcode",
            Self::Unknown(raw) => raw,
        }
    }

    /// Whether the server has to do work for this playback.
    ///
    /// Used by the UI to warn before starting, and by the tests that assert a
    /// direct-play request really produced a direct play.
    pub fn costs_server_cpu(&self) -> bool {
        matches!(self, Self::Transcode)
    }
}

/// Why a transcode was chosen, as far as the server reported it.
///
/// Kept as a list of strings with a classification helper rather than an enum of
/// reasons: the server's reasons are free text (`playback_decision.py` builds them with
/// f-strings), so an enum would reject a reason it did not anticipate and lose the
/// explanation the user needs.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TranscodeReasons {
    pub reasons: Vec<String>,
}

impl TranscodeReasons {
    pub fn new(reasons: Vec<String>) -> Self {
        Self { reasons }
    }

    pub fn is_empty(&self) -> bool {
        self.reasons.is_empty()
    }

    /// A sentence for the UI, or `None` when there is nothing to say.
    pub fn describe(&self) -> Option<String> {
        if self.reasons.is_empty() {
            return None;
        }
        Some(self.reasons.join("; "))
    }

    /// Whether the client could have avoided this by reporting better capabilities.
    ///
    /// Worth knowing: a codec the client *does* support appearing here means the
    /// capability report is wrong, which is a bug in the client rather than a genuine
    /// server-side limitation. Plan task 2.2 exists because of exactly this.
    pub fn looks_like_a_client_gap(&self) -> bool {
        const CLIENT_SIDE_HINTS: [&str; 6] = [
            "codec",
            "container",
            "resolution",
            "bit depth",
            "bit-depth",
            "profile",
        ];
        self.reasons.iter().any(|reason| {
            let lowered = reason.to_ascii_lowercase();
            CLIENT_SIDE_HINTS.iter().any(|hint| lowered.contains(hint))
        })
    }
}

/// The server's answer to a play request, reduced to what the player needs.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlayResponse {
    /// Token for the stream endpoint.
    pub token: String,
    pub session_id: Option<String>,
    pub media_source_id: Option<String>,
    pub method: PlaybackMethod,
    /// The server's own flag, kept alongside the derived method because the two can
    /// disagree on an unknown method and the flag is the more conservative signal.
    pub direct_stream: bool,
    pub duration: Option<f64>,
    pub width: Option<u32>,
    pub height: Option<u32>,
    pub reasons: TranscodeReasons,
}

impl PlayResponse {
    /// Parses the play response.
    ///
    /// Defensive about types because a missing field must not abort playback: a token
    /// and a method are enough to start, everything else is metadata the UI can live
    /// without.
    pub fn parse(body: &serde_json::Value) -> Result<Self, PlaybackError> {
        let token = body
            .get("token")
            .and_then(serde_json::Value::as_str)
            .filter(|t| !t.trim().is_empty())
            .ok_or(PlaybackError::MissingToken)?
            .to_string();

        let method = body
            .get("playback_method")
            .and_then(serde_json::Value::as_str)
            .map(PlaybackMethod::from_wire)
            .unwrap_or(PlaybackMethod::Unknown(String::new()));

        // The reasons live inside `stream_info`, which is where the server puts them.
        let reasons = body
            .get("stream_info")
            .and_then(|info| info.get("transcoding_reasons"))
            .and_then(serde_json::Value::as_array)
            .map(|items| {
                items
                    .iter()
                    .filter_map(serde_json::Value::as_str)
                    .map(str::to_string)
                    .collect()
            })
            .unwrap_or_default();

        Ok(Self {
            token,
            session_id: string_or_none(body, "session_id"),
            media_source_id: string_or_none(body, "media_source_id"),
            method,
            direct_stream: body
                .get("direct_stream")
                .and_then(serde_json::Value::as_bool)
                .unwrap_or(false),
            duration: body.get("duration").and_then(serde_json::Value::as_f64),
            width: body
                .get("width")
                .and_then(serde_json::Value::as_u64)
                .map(|v| v as u32),
            height: body
                .get("height")
                .and_then(serde_json::Value::as_u64)
                .map(|v| v as u32),
            reasons: TranscodeReasons::new(reasons),
        })
    }

    /// Whether this playback avoids server-side re-encoding.
    ///
    /// Both signals must agree to call it a direct play: a server that reports
    /// `transcode` while setting `direct_stream` is describing a remux, and treating
    /// that as a full direct play would hide the work it is doing.
    pub fn is_direct_play(&self) -> bool {
        matches!(self.method, PlaybackMethod::DirectPlay)
            || (self.direct_stream && !self.method.costs_server_cpu())
    }

    /// The URL that serves the file.
    ///
    /// Spike 0.3 established the shape: the token alone authorises the request, and the
    /// endpoint supports byte ranges — which is what lets mpv seek without downloading
    /// the whole file first.
    pub fn stream_url(&self, base_url: &str) -> String {
        format!(
            "{}/api/stream/file?token={}",
            base_url.trim_end_matches('/'),
            self.token
        )
    }

    /// The HLS playlist used when a transcode is unavoidable.
    ///
    /// Kept separate and explicitly named: `playlist.m3u8` *is* the transcode path, and
    /// the plan wants it used only when direct play is impossible.
    pub fn hls_url(&self, base_url: &str) -> Option<String> {
        self.session_id.as_ref().map(|session| {
            format!(
                "{}/api/stream/{}/playlist.m3u8?token={}",
                base_url.trim_end_matches('/'),
                session,
                self.token
            )
        })
    }

    /// The URL mpv should be given.
    ///
    /// Direct play by default; the HLS manifest only when the server has to transcode
    /// and provided a session. Returns an error rather than falling back to something
    /// arbitrary, so a failure is visible instead of producing a black window.
    pub fn url_for_player(&self, base_url: &str) -> Result<String, PlaybackError> {
        if self.is_direct_play() {
            return Ok(self.stream_url(base_url));
        }
        self.hls_url(base_url)
            .ok_or_else(|| PlaybackError::NoPlayableUrl(self.method.as_str().to_string()))
    }

    /// Whether playing this is worth confirming with the user first.
    pub fn needs_transcode_confirmation(&self, policy: &ResumePolicy) -> bool {
        policy.confirm_transcode && self.method.costs_server_cpu()
    }
}

fn string_or_none(body: &serde_json::Value, key: &str) -> Option<String> {
    body.get(key)
        .and_then(serde_json::Value::as_str)
        .map(str::to_string)
        .filter(|s| !s.is_empty())
}

/// Rules for where playback should start.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ResumePolicy {
    /// Positions below this are treated as "not started" and playback begins at zero.
    pub minimum_resume_seconds: f64,
    /// How close to the end counts as finished.
    pub finished_margin_seconds: f64,
    /// A relative version of the same rule, for long films where two minutes is
    /// nothing.
    pub finished_margin_fraction: f64,
    /// Ask before starting a transcode.
    pub confirm_transcode: bool,
}

impl Default for ResumePolicy {
    fn default() -> Self {
        Self {
            // Roughly the length of opening titles and studio logos.
            minimum_resume_seconds: 30.0,
            // Inside the credits for a typical film.
            finished_margin_seconds: 120.0,
            // …but on a three-hour film, 2 % is still over three minutes, so both
            // rules apply and the larger margin wins.
            finished_margin_fraction: 0.02,
            confirm_transcode: true,
        }
    }
}

/// What to do about a stored position.
#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub enum ResumeDecision {
    /// Start from the beginning.
    StartOver,
    /// Resume at this position.
    Resume(f64),
    /// Resume at this position, but say so — the user gets a visible hint and can
    /// choose to start over, rather than wondering why the film did not begin.
    ResumeWithPrompt(f64),
}

impl ResumeDecision {
    /// The position to hand to mpv.
    pub fn position(self) -> f64 {
        match self {
            Self::StartOver => 0.0,
            Self::Resume(p) | Self::ResumeWithPrompt(p) => p,
        }
    }

    pub fn is_resuming(self) -> bool {
        !matches!(self, Self::StartOver)
    }
}

impl ResumePolicy {
    /// Decides where to start.
    ///
    /// `stored_position` and `duration` are both in seconds. Called with what the
    /// server reported for this user and item.
    pub fn decide(
        &self,
        stored_position: f64,
        duration: Option<f64>,
        already_played: bool,
    ) -> ResumeDecision {
        // A position that is not a number, or negative, carries no information.
        if !stored_position.is_finite() || stored_position <= 0.0 {
            return ResumeDecision::StartOver;
        }
        // The user marked it unwatched or watched; their explicit action beats a
        // leftover position.
        if already_played {
            return ResumeDecision::StartOver;
        }
        if stored_position < self.minimum_resume_seconds {
            return ResumeDecision::StartOver;
        }

        if let Some(duration) = duration.filter(|d| d.is_finite() && *d > 0.0) {
            // A stored position beyond the duration means the file changed or the
            // metadata is stale; starting in the middle of nothing is worse than
            // starting over.
            if stored_position >= duration {
                return ResumeDecision::StartOver;
            }
            let margin = self
                .finished_margin_seconds
                .max(duration * self.finished_margin_fraction);
            if duration - stored_position <= margin {
                return ResumeDecision::StartOver;
            }
        }

        // A prompt is worthwhile when the position is far enough in that the user
        // would be confused to land in the middle without explanation.
        if stored_position >= self.prompt_threshold_seconds() {
            ResumeDecision::ResumeWithPrompt(stored_position)
        } else {
            ResumeDecision::Resume(stored_position)
        }
    }

    /// From here on, resuming is announced.
    pub fn prompt_threshold_seconds(&self) -> f64 {
        // Two minutes in: past any remaining doubt that the viewing was intentional.
        self.minimum_resume_seconds.max(120.0)
    }
}

/// What to report to the server as playback advances.
///
/// The payload shape mirrors `ItemPlaystateReport` in
/// `backend/src/streamarr/api/v1/viewing_history.py`, which is where the server reads
/// `position_seconds`, `duration_seconds`, `is_paused` and the track selections.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlaybackReport {
    pub position_seconds: u32,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_seconds: Option<u32>,
    pub is_paused: bool,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub audio_stream_index: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub subtitle_stream_index: Option<u32>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub media_source_id: Option<String>,
}

impl PlaybackReport {
    /// Builds a report from the player's state.
    pub fn from_state(position: f64, duration: f64, paused: bool) -> Self {
        Self {
            // Rounded down and floored at zero: the server validates `ge=0`, and a
            // negative or fractional position would be rejected.
            position_seconds: position.max(0.0).floor() as u32,
            duration_seconds: (duration > 0.0).then(|| duration.floor() as u32),
            is_paused: paused,
            audio_stream_index: None,
            subtitle_stream_index: None,
            media_source_id: None,
        }
    }

    pub fn with_tracks(mut self, audio: Option<u32>, subtitle: Option<u32>) -> Self {
        self.audio_stream_index = audio;
        self.subtitle_stream_index = subtitle;
        self
    }

    /// How far through, as a percentage, for the server's progress bar.
    pub fn percentage(&self) -> Option<f64> {
        let duration = self.duration_seconds?;
        if duration == 0 {
            return None;
        }
        Some((self.position_seconds as f64 / duration as f64 * 100.0).clamp(0.0, 100.0))
    }

    /// Whether a new report is worth sending.
    ///
    /// Reporting every second would be a request per second per viewer. Two things are
    /// worth a request: a meaningful position change, and a pause/resume (which is a
    /// state the server stores separately and which the user would notice being
    /// wrong).
    pub fn should_send(&self, previous: Option<&PlaybackReport>, interval_seconds: u32) -> bool {
        let Some(previous) = previous else {
            return true;
        };
        if previous.is_paused != self.is_paused {
            return true;
        }
        // A backwards jump larger than the interval is a seek; reporting it keeps the
        // server's position in step with the user's.
        if self.position_seconds + interval_seconds < previous.position_seconds {
            return true;
        }
        self.position_seconds
            .saturating_sub(previous.position_seconds)
            >= interval_seconds
    }
}

/// A track choice as the server stores it.
///
/// The server keeps both an index and a language (`MediaUserData`): the index is exact
/// but breaks when a file is replaced, the language survives that. Storing both and
/// preferring the index mirrors the server's own fields.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrackPreference {
    pub audio_index: Option<u32>,
    pub subtitle_index: Option<u32>,
    pub audio_language: Option<String>,
    pub subtitle_language: Option<String>,
}

impl TrackPreference {
    /// The audio to select, preferring the explicit index over the language.
    pub fn audio_choice(&self) -> TrackChoice {
        match (self.audio_index, self.audio_language.as_deref()) {
            (Some(index), _) => TrackChoice::ByIndex(index),
            (None, Some(language)) => TrackChoice::ByLanguage(language.to_string()),
            (None, None) => TrackChoice::MpvDefault,
        }
    }

    /// The subtitle to select.
    ///
    /// An explicit index of `0` or a language of `"none"` is how the UI records "the
    /// user turned subtitles off" — which must not fall through to a language match,
    /// or subtitles would come back on. An explicit index of `-1` (mpv's "off") is
    /// handled by [`TrackChoice::Disabled`].
    pub fn subtitle_choice(&self) -> TrackChoice {
        if let Some(index) = self.subtitle_index {
            return if index == u32::MAX {
                TrackChoice::Disabled
            } else {
                TrackChoice::ByIndex(index)
            };
        }
        match self.subtitle_language.as_deref() {
            Some("none") | Some("off") | Some("") => TrackChoice::Disabled,
            Some(language) => TrackChoice::ByLanguage(language.to_string()),
            None => TrackChoice::MpvDefault,
        }
    }
}

/// Which track to select.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub enum TrackChoice {
    /// Leave mpv's own choice, which follows the file's default flags.
    MpvDefault,
    /// Select by mpv's numeric track id.
    ByIndex(u32),
    /// Select the best match for this language.
    ByLanguage(String),
    /// Turn this track type off.
    Disabled,
}

impl TrackChoice {
    /// The `aid`/`sid` value for mpv, or `None` when mpv should decide.
    ///
    /// mpv expresses "off" as `no` for these properties; a numeric id is a number.
    pub fn mpv_value(&self) -> Option<serde_json::Value> {
        match self {
            Self::MpvDefault => None,
            Self::ByIndex(index) => Some(serde_json::json!(index)),
            Self::ByLanguage(_) => None,
            Self::Disabled => Some(serde_json::json!("no")),
        }
    }

    /// Whether the shell has to look up a track before it can apply this.
    pub fn needs_lookup(&self) -> bool {
        matches!(self, Self::ByLanguage(_))
    }
}

/// What can go wrong deciding playback.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum PlaybackError {
    /// The server returned no token, so nothing can be played.
    MissingToken,
    /// Direct play was impossible and no session was given for a transcode.
    NoPlayableUrl(String),
}

impl fmt::Display for PlaybackError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::MissingToken => write!(
                f,
                "Der Server hat kein Wiedergabe-Token geliefert — dieser Titel kann \
                 nicht abgespielt werden."
            ),
            Self::NoPlayableUrl(method) => write!(
                f,
                "Für `{method}` gibt es keine abspielbare URL. Der Server hat keine \
                 Streaming-Sitzung angelegt."
            ),
        }
    }
}

impl std::error::Error for PlaybackError {}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // ── Playback method ──

    #[test]
    fn known_methods_are_recognised() {
        assert_eq!(
            PlaybackMethod::from_wire("direct_play"),
            PlaybackMethod::DirectPlay
        );
        assert_eq!(
            PlaybackMethod::from_wire("direct_stream"),
            PlaybackMethod::DirectStream
        );
        assert_eq!(
            PlaybackMethod::from_wire("transcode"),
            PlaybackMethod::Transcode
        );
    }

    /// The wire value is free text; variants of the same method must not become
    /// different methods.
    #[test]
    fn spelling_variants_collapse() {
        for value in ["direct_play", "DirectPlay", "direct-play", " DIRECT_PLAY "] {
            assert_eq!(
                PlaybackMethod::from_wire(value),
                PlaybackMethod::DirectPlay,
                "`{value}` wurde nicht als Direct Play erkannt"
            );
        }
    }

    /// A new server-side method must not stop the client from playing.
    #[test]
    fn an_unknown_method_is_preserved_not_rejected() {
        let method = PlaybackMethod::from_wire("some_new_method");
        assert_eq!(
            method,
            PlaybackMethod::Unknown("some_new_method".to_string())
        );
        assert_eq!(method.as_str(), "some_new_method");
        // And it is not assumed to be free.
        assert!(!method.costs_server_cpu());
    }

    #[test]
    fn only_transcode_costs_server_cpu() {
        assert!(PlaybackMethod::Transcode.costs_server_cpu());
        assert!(!PlaybackMethod::DirectPlay.costs_server_cpu());
        // A remux is cheap compared with a re-encode.
        assert!(!PlaybackMethod::DirectStream.costs_server_cpu());
    }

    // ── Response parsing ──

    fn response_fixture() -> serde_json::Value {
        json!({
            "status": "success",
            "token": "abc123",
            "session_id": "sess-1",
            "media_source_id": "src-1",
            "playback_method": "direct_play",
            "direct_stream": false,
            "duration": 102.5,
            "width": 1480,
            "height": 1080,
            "stream_info": {
                "source_file": "/media/Casablanca.mkv",
                "transcoding": false,
                "transcoding_reasons": [],
                "client_capabilities": {}
            }
        })
    }

    #[test]
    fn a_full_response_is_parsed() {
        let parsed = PlayResponse::parse(&response_fixture()).unwrap();
        assert_eq!(parsed.token, "abc123");
        assert_eq!(parsed.session_id.as_deref(), Some("sess-1"));
        assert_eq!(parsed.method, PlaybackMethod::DirectPlay);
        assert_eq!(parsed.duration, Some(102.5));
        assert_eq!(parsed.width, Some(1480));
        assert_eq!(parsed.height, Some(1080));
        assert!(parsed.reasons.is_empty());
    }

    /// Without a token nothing can be played, and a silent failure would show a black
    /// window instead of an explanation.
    #[test]
    fn a_missing_token_is_an_error() {
        let mut body = response_fixture();
        body.as_object_mut().unwrap().remove("token");
        assert_eq!(PlayResponse::parse(&body), Err(PlaybackError::MissingToken));

        // An empty token is no better than a missing one.
        let body = json!({"token": "   "});
        assert_eq!(PlayResponse::parse(&body), Err(PlaybackError::MissingToken));
    }

    /// A minimal response must still play: the server may omit metadata.
    #[test]
    fn a_minimal_response_still_works() {
        let parsed = PlayResponse::parse(&json!({"token": "t"})).unwrap();
        assert_eq!(parsed.token, "t");
        assert_eq!(parsed.duration, None);
        assert_eq!(parsed.method, PlaybackMethod::Unknown(String::new()));
    }

    #[test]
    fn transcode_reasons_are_read_from_stream_info() {
        let body = json!({
            "token": "t",
            "playback_method": "transcode",
            "stream_info": {
                "transcoding": true,
                "transcoding_reasons": [
                    "Video codec hevc not supported by client",
                    "10-bit → 8-bit conversion"
                ]
            }
        });
        let parsed = PlayResponse::parse(&body).unwrap();
        assert_eq!(parsed.reasons.reasons.len(), 2);
        let described = parsed.reasons.describe().unwrap();
        assert!(described.contains("hevc"));
        assert!(described.contains("8-bit"));
    }

    #[test]
    fn no_reasons_means_nothing_to_describe() {
        assert_eq!(TranscodeReasons::default().describe(), None);
        assert!(TranscodeReasons::default().is_empty());
    }

    /// A reason naming a codec or container is the client's own fault, which is what
    /// plan task 2.2 exists to fix. Distinguishing it from a genuine limitation is how
    /// a broken capability report becomes visible instead of looking like a server
    /// restriction.
    #[test]
    fn client_side_reasons_are_recognised() {
        assert!(TranscodeReasons::new(vec![
            "Audio codec truehd not supported by client".to_string()
        ])
        .looks_like_a_client_gap());
        assert!(
            TranscodeReasons::new(vec!["Container mkv not supported".to_string()])
                .looks_like_a_client_gap()
        );
        // A server-side decision is not a client gap.
        assert!(
            !TranscodeReasons::new(vec!["Server bandwidth limit exceeded".to_string()])
                .looks_like_a_client_gap()
        );
    }

    // ── Direct play decisions ──

    #[test]
    fn a_direct_play_is_reported_as_one() {
        let parsed = PlayResponse::parse(&response_fixture()).unwrap();
        assert!(parsed.is_direct_play());
        assert!(!parsed.needs_transcode_confirmation(&ResumePolicy::default()));
    }

    /// A server that sets `direct_stream` while calling it a transcode is describing a
    /// remux. Calling that a full direct play would hide the work it is doing.
    #[test]
    fn the_method_flag_wins_over_the_direct_stream_flag() {
        let body = json!({
            "token": "t",
            "playback_method": "transcode",
            "direct_stream": true
        });
        let parsed = PlayResponse::parse(&body).unwrap();
        assert!(!parsed.is_direct_play());
        assert!(parsed.needs_transcode_confirmation(&ResumePolicy::default()));
    }

    #[test]
    fn a_direct_stream_without_a_transcode_counts_as_direct() {
        let body = json!({
            "token": "t",
            "playback_method": "direct_stream",
            "direct_stream": true
        });
        let parsed = PlayResponse::parse(&body).unwrap();
        assert!(parsed.is_direct_play());
    }

    #[test]
    fn transcode_confirmation_can_be_turned_off() {
        let body = json!({"token": "t", "playback_method": "transcode"});
        let parsed = PlayResponse::parse(&body).unwrap();
        let policy = ResumePolicy {
            confirm_transcode: false,
            ..Default::default()
        };
        assert!(!parsed.needs_transcode_confirmation(&policy));
    }

    // ── URLs ──

    /// Spike 0.3: the token alone authorises the file request, and the endpoint serves
    /// byte ranges, which is what lets mpv seek without a full download.
    #[test]
    fn the_direct_url_uses_the_file_endpoint_with_the_token() {
        let parsed = PlayResponse::parse(&response_fixture()).unwrap();
        assert_eq!(
            parsed.stream_url("https://host/"),
            "https://host/api/stream/file?token=abc123"
        );
    }

    #[test]
    fn a_trailing_slash_on_the_base_url_does_not_double_up() {
        let parsed = PlayResponse::parse(&response_fixture()).unwrap();
        let url = parsed.stream_url("https://host");
        assert!(!url.contains("//api"), "{url}");
    }

    /// HLS *is* the transcode path; it must only be used when direct play is
    /// impossible.
    #[test]
    fn the_player_gets_the_direct_url_for_a_direct_play() {
        let parsed = PlayResponse::parse(&response_fixture()).unwrap();
        let url = parsed.url_for_player("https://host").unwrap();
        assert!(url.contains("/api/stream/file"), "{url}");
        assert!(!url.contains("playlist.m3u8"), "{url}");
    }

    #[test]
    fn the_player_gets_the_manifest_only_when_transcoding() {
        let body = json!({
            "token": "t", "session_id": "s1", "playback_method": "transcode"
        });
        let parsed = PlayResponse::parse(&body).unwrap();
        let url = parsed.url_for_player("https://host").unwrap();
        assert_eq!(url, "https://host/api/stream/s1/playlist.m3u8?token=t");
    }

    /// A transcode without a session cannot be played; failing loudly beats handing mpv
    /// a URL that produces a black window.
    #[test]
    fn a_transcode_without_a_session_is_an_error() {
        let body = json!({"token": "t", "playback_method": "transcode"});
        let parsed = PlayResponse::parse(&body).unwrap();
        assert!(matches!(
            parsed.url_for_player("https://host"),
            Err(PlaybackError::NoPlayableUrl(_))
        ));
    }

    #[test]
    fn playback_errors_explain_themselves() {
        let err = PlaybackError::MissingToken;
        assert!(err.to_string().contains("Token"));
        assert!(!err.to_string().contains("PlaybackError"));
    }

    // ── Resume ──

    #[test]
    fn a_stored_position_far_into_the_file_is_resumed() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(600.0, Some(7200.0), false),
            ResumeDecision::ResumeWithPrompt(600.0)
        );
    }

    /// The studio-logos case: a few seconds in is not a viewing to resume.
    #[test]
    fn a_position_just_after_the_start_starts_over() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(7.0, Some(7200.0), false),
            ResumeDecision::StartOver
        );
        assert_eq!(
            policy.decide(29.9, Some(7200.0), false),
            ResumeDecision::StartOver
        );
    }

    #[test]
    fn a_position_at_the_threshold_resumes() {
        let policy = ResumePolicy::default();
        let decision = policy.decide(30.0, Some(7200.0), false);
        assert!(decision.is_resuming(), "{decision:?}");
    }

    /// The end-credits case: resuming near the end makes the film appear to finish
    /// instantly.
    #[test]
    fn a_position_near_the_end_starts_over() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(3600.0, Some(3660.0), false),
            ResumeDecision::StartOver,
            "eine Minute vor Schluss"
        );
        assert_eq!(
            policy.decide(3599.0, Some(3600.0), false),
            ResumeDecision::StartOver
        );
    }

    /// The relative rule exists for long material: on a three-hour film, two minutes
    /// is nothing, so the larger margin applies.
    #[test]
    fn the_larger_end_margin_wins_on_long_files() {
        let policy = ResumePolicy::default();
        let duration = 3.0 * 3600.0;
        let margin = duration * policy.finished_margin_fraction;
        assert!(
            margin > policy.finished_margin_seconds,
            "Testannahme verletzt"
        );

        // Just outside the relative margin: resume.
        let position = duration - margin - 1.0;
        assert!(policy.decide(position, Some(duration), false).is_resuming());
        // Just inside it: start over.
        let position = duration - margin + 1.0;
        assert_eq!(
            policy.decide(position, Some(duration), false),
            ResumeDecision::StartOver
        );
    }

    /// A user who marked an item unwatched expects it to start at the beginning; their
    /// explicit action beats a leftover position.
    #[test]
    fn a_played_flag_beats_a_stored_position() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(600.0, Some(7200.0), true),
            ResumeDecision::StartOver
        );
    }

    #[test]
    fn a_zero_or_missing_position_starts_over() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(0.0, Some(7200.0), false),
            ResumeDecision::StartOver
        );
        assert_eq!(
            policy.decide(-5.0, Some(7200.0), false),
            ResumeDecision::StartOver
        );
        // Not a number at all.
        assert_eq!(
            policy.decide(f64::NAN, Some(7200.0), false),
            ResumeDecision::StartOver
        );
        assert_eq!(
            policy.decide(f64::INFINITY, Some(7200.0), false),
            ResumeDecision::StartOver
        );
    }

    /// A position past the duration means the file changed or the metadata is stale.
    #[test]
    fn a_position_beyond_the_duration_starts_over() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(9000.0, Some(7200.0), false),
            ResumeDecision::StartOver
        );
    }

    /// Without a duration the end rules cannot apply, but the start rule still can —
    /// resuming is better than refusing to.
    #[test]
    fn without_a_duration_the_start_rule_still_applies() {
        let policy = ResumePolicy::default();
        assert!(policy.decide(600.0, None, false).is_resuming());
        assert_eq!(policy.decide(5.0, None, false), ResumeDecision::StartOver);
    }

    #[test]
    fn a_zero_duration_is_treated_as_unknown() {
        let policy = ResumePolicy::default();
        assert!(policy.decide(600.0, Some(0.0), false).is_resuming());
        assert!(policy.decide(600.0, Some(-10.0), false).is_resuming());
    }

    /// A prompt is only worth showing once the position is far enough in that landing
    /// there unexplained would be confusing.
    #[test]
    fn a_short_resume_does_not_prompt() {
        let policy = ResumePolicy::default();
        assert_eq!(
            policy.decide(45.0, Some(7200.0), false),
            ResumeDecision::Resume(45.0)
        );
        assert_eq!(
            policy.decide(600.0, Some(7200.0), false),
            ResumeDecision::ResumeWithPrompt(600.0)
        );
    }

    #[test]
    fn the_decision_hands_the_right_position_to_the_player() {
        assert_eq!(ResumeDecision::StartOver.position(), 0.0);
        assert_eq!(ResumeDecision::Resume(42.0).position(), 42.0);
        assert_eq!(ResumeDecision::ResumeWithPrompt(42.0).position(), 42.0);
        assert!(!ResumeDecision::StartOver.is_resuming());
    }

    #[test]
    fn the_policy_is_adjustable() {
        let policy = ResumePolicy {
            minimum_resume_seconds: 0.0,
            finished_margin_seconds: 0.0,
            finished_margin_fraction: 0.0,
            confirm_transcode: false,
        };
        // With every guard off, any positive position resumes.
        assert!(policy.decide(1.0, Some(7200.0), false).is_resuming());
    }

    // ── Progress reporting ──

    #[test]
    fn a_report_is_built_from_the_player_state() {
        let report = PlaybackReport::from_state(125.7, 7200.4, false);
        assert_eq!(report.position_seconds, 125);
        assert_eq!(report.duration_seconds, Some(7200));
        assert!(!report.is_paused);
    }

    /// The server validates `ge=0`; a negative position would be rejected outright.
    #[test]
    fn a_negative_position_is_clamped() {
        let report = PlaybackReport::from_state(-10.0, 100.0, false);
        assert_eq!(report.position_seconds, 0);
    }

    #[test]
    fn an_unknown_duration_is_omitted_rather_than_sent_as_zero() {
        let report = PlaybackReport::from_state(10.0, 0.0, false);
        assert_eq!(report.duration_seconds, None);
        assert_eq!(report.percentage(), None);

        // And a zero duration must not produce a division by zero.
        let json = serde_json::to_value(&report).unwrap();
        assert!(json.get("duration_seconds").is_none(), "{json}");
    }

    #[test]
    fn the_percentage_matches_the_position() {
        let report = PlaybackReport::from_state(25.0, 100.0, false);
        assert_eq!(report.percentage(), Some(25.0));
    }

    #[test]
    fn the_percentage_is_clamped_to_a_hundred() {
        let report = PlaybackReport::from_state(150.0, 100.0, false);
        assert_eq!(report.percentage(), Some(100.0));
    }

    /// A request per second per viewer is not acceptable; only meaningful changes are
    /// reported.
    #[test]
    fn reports_are_throttled_by_position() {
        let first = PlaybackReport::from_state(10.0, 100.0, false);
        assert!(
            first.should_send(None, 10),
            "der erste Bericht geht immer raus"
        );

        let soon = PlaybackReport::from_state(15.0, 100.0, false);
        assert!(!soon.should_send(Some(&first), 10), "5 s sind zu wenig");

        let later = PlaybackReport::from_state(20.0, 100.0, false);
        assert!(later.should_send(Some(&first), 10));
    }

    /// A pause is a state the server stores separately and the user would notice being
    /// wrong, so it is reported immediately however recent the last report was.
    #[test]
    fn a_state_change_is_reported_immediately() {
        let playing = PlaybackReport::from_state(10.0, 100.0, false);
        let paused = PlaybackReport::from_state(10.0, 100.0, true);
        assert!(paused.should_send(Some(&playing), 10));
    }

    /// Seeking backwards is a real change even though the position did not advance.
    #[test]
    fn a_backwards_seek_is_reported() {
        let later = PlaybackReport::from_state(500.0, 100.0, false);
        let seeked = PlaybackReport::from_state(60.0, 100.0, false);
        assert!(seeked.should_send(Some(&later), 10));
    }

    #[test]
    fn an_unchanged_position_is_not_reported() {
        let report = PlaybackReport::from_state(10.0, 100.0, false);
        assert!(!report.should_send(Some(&report), 10));
    }

    #[test]
    fn track_indices_are_attached_when_known() {
        let report = PlaybackReport::from_state(1.0, 100.0, false).with_tracks(Some(1), Some(2));
        assert_eq!(report.audio_stream_index, Some(1));
        assert_eq!(report.subtitle_stream_index, Some(2));
        // Absent fields are omitted so the server keeps what it has.
        let bare = serde_json::to_value(PlaybackReport::from_state(1.0, 100.0, false)).unwrap();
        assert!(bare.get("audio_stream_index").is_none(), "{bare}");
    }

    // ── Track preferences ──

    #[test]
    fn an_explicit_index_is_preferred_over_a_language() {
        let preference = TrackPreference {
            audio_index: Some(2),
            audio_language: Some("de".to_string()),
            ..Default::default()
        };
        assert_eq!(preference.audio_choice(), TrackChoice::ByIndex(2));
    }

    #[test]
    fn a_language_is_used_when_there_is_no_index() {
        let preference = TrackPreference {
            audio_language: Some("de".to_string()),
            ..Default::default()
        };
        assert_eq!(
            preference.audio_choice(),
            TrackChoice::ByLanguage("de".to_string())
        );
    }

    #[test]
    fn no_preference_leaves_mpvs_choice_alone() {
        assert_eq!(
            TrackPreference::default().audio_choice(),
            TrackChoice::MpvDefault
        );
        assert_eq!(
            TrackPreference::default().subtitle_choice(),
            TrackChoice::MpvDefault
        );
    }

    /// Turning subtitles off must stay off. Falling through to a language match would
    /// silently turn them back on — the kind of bug a user would report as "the app
    /// ignores my setting".
    #[test]
    fn subtitles_turned_off_stay_off() {
        let preference = TrackPreference {
            subtitle_language: Some("none".to_string()),
            ..Default::default()
        };
        assert_eq!(preference.subtitle_choice(), TrackChoice::Disabled);

        for off in ["none", "off", ""] {
            let preference = TrackPreference {
                subtitle_language: Some(off.to_string()),
                ..Default::default()
            };
            assert_eq!(
                preference.subtitle_choice(),
                TrackChoice::Disabled,
                "`{off}` muss Untertitel abschalten"
            );
        }
    }

    /// An audio preference of "none" makes no sense — there has to be sound — but an
    /// explicit subtitle index of mpv's "off" does.
    #[test]
    fn an_explicit_off_index_disables_subtitles() {
        let preference = TrackPreference {
            subtitle_index: Some(u32::MAX),
            ..Default::default()
        };
        assert_eq!(preference.subtitle_choice(), TrackChoice::Disabled);
    }

    #[test]
    fn a_set_subtitle_index_selects_that_track() {
        let preference = TrackPreference {
            subtitle_index: Some(3),
            ..Default::default()
        };
        assert_eq!(preference.subtitle_choice(), TrackChoice::ByIndex(3));
    }

    #[test]
    fn mpv_values_are_expressed_the_way_mpv_expects() {
        assert_eq!(TrackChoice::MpvDefault.mpv_value(), None);
        assert_eq!(
            TrackChoice::ByIndex(4).mpv_value(),
            Some(serde_json::json!(4)),
            "die Spur-ID muss eine Zahl sein"
        );
        // mpv expresses "off" as the string `no` for these properties.
        assert_eq!(
            TrackChoice::Disabled.mpv_value(),
            Some(serde_json::json!("no"))
        );
    }

    #[test]
    fn only_a_language_choice_needs_a_lookup() {
        assert!(TrackChoice::ByLanguage("de".to_string()).needs_lookup());
        assert!(!TrackChoice::ByIndex(1).needs_lookup());
        assert!(!TrackChoice::MpvDefault.needs_lookup());
        assert!(!TrackChoice::Disabled.needs_lookup());
    }
}
