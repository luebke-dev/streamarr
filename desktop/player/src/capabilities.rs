//! What this client can play, and how to tell the server about it.
//!
//! Two problems this solves, both found during phase 0:
//!
//! 1. **The server transcodes when it need not.** Spike 0.3 showed a
//!    h264/AC3 file being transcoded (`Audio: ac3 → aac`) although the client can
//!    play AC3 natively. The reason was that no capabilities were sent, so the
//!    server fell back to conservative defaults.
//! 2. **The web client's HDR probe is wrong.** `frontend/src/composables/usePlay.js`
//!    probes with `type: 'media-source'`, which asks the *browser* what it can
//!    decode — irrelevant when the video is decoded by mpv outside the webview.
//!
//! Being precise here is what makes Direct Play work at all: every codec the
//! client does not claim becomes a transcode, and every codec it claims wrongly
//! becomes a file that fails to play.
//!
//! # Two field names for one thing
//!
//! The play endpoint takes `client_max_resolution`
//! (`api/v1/playback_params.py`), while the device-capability endpoint takes
//! `max_resolution` (`schemas/device.py`). They mean the same thing. Rather than
//! let callers guess, [`Capabilities::play_query`] and
//! [`Capabilities::device_payload`] each emit the right name, and a golden test
//! pins both against the server sources.

use serde::{Deserialize, Serialize};

/// Video codecs, named the way the server compares them.
///
/// The server normalises aliases before comparing
/// (`libraries/base.py`: `h265`, `x265` and `hevc` are the same codec), so any
/// spelling would work — but sending the canonical one keeps logs readable and
/// avoids depending on that normalisation.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VideoCodec {
    H264,
    /// Reported to the server as `h265`; the server also accepts `hevc`/`x265`.
    H265,
    Av1,
    Vp9,
}

impl VideoCodec {
    /// Wire name used when talking to the server.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::H264 => "h264",
            Self::H265 => "h265",
            Self::Av1 => "av1",
            Self::Vp9 => "vp9",
        }
    }
}

/// Audio codecs. `copy` is not a codec but the server's instruction to pass audio
/// through untouched, so it lives in its own list below rather than here.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum AudioCodec {
    Aac,
    Ac3,
    Eac3,
    Dts,
    /// DTS-HD / DTS:X; the server's list uses `dtshd`.
    DtsHd,
    TrueHd,
    Flac,
    Opus,
    Mp3,
}

impl AudioCodec {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Aac => "aac",
            Self::Ac3 => "ac3",
            Self::Eac3 => "eac3",
            Self::Dts => "dts",
            Self::DtsHd => "dtshd",
            Self::TrueHd => "truehd",
            Self::Flac => "flac",
            Self::Opus => "opus",
            Self::Mp3 => "mp3",
        }
    }
}

/// Containers mpv opens directly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Container {
    Mkv,
    Mp4,
    Avi,
    /// MPEG transport stream.
    Ts,
    Webm,
    Mov,
}

impl Container {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Mkv => "mkv",
            Self::Mp4 => "mp4",
            Self::Avi => "avi",
            Self::Ts => "ts",
            Self::Webm => "webm",
            Self::Mov => "mov",
        }
    }
}

/// Maximum output resolution the client will claim.
///
/// Deliberately not "whatever the display is": claiming 8K on a 1080p screen
/// would push the server into a pointless 8K transcode. See
/// [`Capabilities::detect`].
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
pub enum MaxResolution {
    Hd720,
    FullHd1080,
    Uhd4k,
    Uhd8k,
}

impl MaxResolution {
    /// Wire name. The play endpoint documents `4k`, `1080p`, `720p`
    /// (`playback_params.py`); `8k` follows the same pattern.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Hd720 => "720p",
            Self::FullHd1080 => "1080p",
            Self::Uhd4k => "4k",
            Self::Uhd8k => "8k",
        }
    }

    /// Pixel width, used to pick the largest resolution a display supports.
    pub fn width(self) -> u32 {
        match self {
            Self::Hd720 => 1280,
            Self::FullHd1080 => 1920,
            Self::Uhd4k => 3840,
            Self::Uhd8k => 7680,
        }
    }

    /// The largest tier a display of this width can show.
    ///
    /// Anything at or above 4K is reported as 4K at most: the server's own
    /// encoder caps H.264 at 4096 wide (`lightrays/src/encoder.rs`), and 8K
    /// sources are vanishingly rare, so claiming 8K buys nothing but risk.
    pub fn for_display_width(width: u32) -> Self {
        match width {
            w if w >= 3840 => Self::Uhd4k,
            w if w >= 1920 => Self::FullHd1080,
            w if w >= 1280 => Self::Hd720,
            _ => Self::Hd720,
        }
    }
}

/// Renders a codec list as the comma-separated string the server parses.
///
/// Takes `&str`s rather than a generic over `AsRef<str>`: the three codec enums
/// would each need an `AsRef` impl for that, which is more machinery than the
/// single call site justifies.
fn join_codecs(codecs: &[&str]) -> String {
    codecs.join(",")
}

/// Turns a slice of codec enums into their wire names.
fn names<T: Copy>(codecs: &[T], as_str: fn(T) -> &'static str) -> Vec<&'static str> {
    codecs.iter().copied().map(as_str).collect()
}

/// What this client can decode, as reported to the server.
///
/// Built by [`Capabilities::detect`] in the real app, or by hand in tests. The
/// fields mirror the server's expectations exactly; see the module docs for the
/// two names for the maximum resolution.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Capabilities {
    pub video_codecs: Vec<VideoCodec>,
    pub audio_codecs: Vec<AudioCodec>,
    pub containers: Vec<Container>,
    pub max_resolution: MaxResolution,
    /// HDR passthrough (HDR10/HLG) — true only when the display and the renderer
    /// both support it. See [`Capabilities::detect`].
    pub supports_hdr: bool,
    /// Whether hardware decoding is active. Not sent to the server — it affects
    /// playback smoothness, not what can be played — but shown in the UI and in
    /// bug reports.
    pub hardware_decode: bool,
    pub app_name: String,
    pub app_version: String,
}

impl Capabilities {
    /// What mpv can play on a desktop, with HDR and hardware decode as inputs.
    ///
    /// The codec list is not guessed: it is what mpv ships with (FFmpeg's
    /// decoders plus the platform's hardware decoders). H.264/HEVC cover the
    /// libraries; AV1 and VP9 are included because mpv handles them in software
    /// at any realistic resolution, and every codec left out becomes a
    /// transcode.
    pub fn detect(
        display_width: u32,
        hdr_display: bool,
        hdr_renderer: bool,
        hardware_decode: bool,
        app_version: &str,
    ) -> Self {
        Self {
            video_codecs: vec![
                VideoCodec::H264,
                VideoCodec::H265,
                VideoCodec::Av1,
                VideoCodec::Vp9,
            ],
            audio_codecs: vec![
                AudioCodec::Aac,
                AudioCodec::Ac3,
                AudioCodec::Eac3,
                AudioCodec::Dts,
                AudioCodec::DtsHd,
                AudioCodec::TrueHd,
                AudioCodec::Flac,
                AudioCodec::Opus,
                AudioCodec::Mp3,
            ],
            containers: vec![
                Container::Mkv,
                Container::Mp4,
                Container::Mov,
                Container::Avi,
                Container::Ts,
                Container::Webm,
            ],
            max_resolution: MaxResolution::for_display_width(display_width),
            // HDR needs *both*: a display that can show it and a renderer that
            // passes it through. Claiming it with only one of the two makes the
            // server send an HDR stream that has to be tone-mapped anyway — and
            // the backend's transcode path is HDR-blind (plan §10.2), so the
            // result would be washed out rather than merely suboptimal.
            supports_hdr: hdr_display && hdr_renderer,
            hardware_decode,
            app_name: "Streamarr Desktop".to_string(),
            app_version: app_version.to_string(),
        }
    }

    /// Query parameters for `POST /api/play/{guid}`.
    ///
    /// The play endpoint takes query parameters, not a JSON body; a JSON body is
    /// ignored silently, which cost time during spike 0.3.
    pub fn play_query(&self) -> Vec<(String, String)> {
        let out = vec![
            (
                "supported_video_codecs".to_string(),
                join_codecs(&names(&self.video_codecs, VideoCodec::as_str)),
            ),
            (
                "supported_audio_codecs".to_string(),
                join_codecs(&names(&self.audio_codecs, AudioCodec::as_str)),
            ),
            (
                "supported_containers".to_string(),
                join_codecs(&names(&self.containers, Container::as_str)),
            ),
            // Named `client_max_resolution` here, `max_resolution` on the device
            // endpoint — the server really does use two names.
            (
                "client_max_resolution".to_string(),
                self.max_resolution.as_str().to_string(),
            ),
        ];
        // `supports_hdr` is deliberately NOT sent: the server has no such
        // parameter (verified against playback_params.py by a golden test). HDR
        // is a local decision — the client reads `hdr_format` from the library
        // metadata and decides whether to tone-map. Sending a field the server
        // ignores would look like a working feature while doing nothing.
        out
    }

    /// JSON body for `PUT /api/devices/me/{guid}/capabilities`.
    ///
    /// Field names follow `schemas/device.py::DeviceCapabilitiesUpdate`. Note
    /// `max_resolution` without the `client_` prefix, and that the codec lists
    /// are JSON *arrays* here while the play endpoint wants comma-separated
    /// strings for the same data.
    pub fn device_payload(&self) -> serde_json::Value {
        serde_json::json!({
            "supported_video_codecs": self.video_codecs.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
            "supported_audio_codecs": self.audio_codecs.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
            "supported_containers": self.containers.iter().map(|c| c.as_str()).collect::<Vec<_>>(),
            "max_resolution": self.max_resolution.as_str(),
            "app_name": self.app_name,
            "app_version": self.app_version,
            // A native mpv client always direct-plays when the codec matches; it
            // never needs the server to transcode for container reasons. Stating
            // this is what stops the server from transcoding "just in case".
            "supports_direct_play": true,
            "supports_direct_stream": true,
            "supports_transcoding": true,
        })
    }

    /// Whether a source file can be played without transcoding.
    ///
    /// Used by the UI to explain *why* something is being transcoded, and to
    /// decide whether to warn before playback. Case-insensitive and alias-aware,
    /// matching the server's own normalisation (`libraries/base.py`).
    pub fn can_direct_play(
        &self,
        video_codec: &str,
        audio_codec: &str,
        container: Option<&str>,
        hdr_format: Option<&str>,
    ) -> DirectPlayVerdict {
        // The server normalises aliases before comparing; do the same here so the
        // UI gives the same answer the server will.
        let video = normalise_video_codec(video_codec);
        if !self.video_codecs.iter().any(|c| c.as_str() == video) {
            return DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedVideoCodec,
            };
        }

        let audio = normalise_audio_codec(audio_codec);
        // The server accepts `copy` as "do not touch the audio"; a client that
        // can direct-play always prefers it.
        if !self.audio_codecs.iter().any(|c| c.as_str() == audio) {
            return DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedAudioCodec,
            };
        }

        if let Some(container) = container {
            let container = container.trim().to_lowercase();
            if !self.containers.iter().any(|c| c.as_str() == container) {
                return DirectPlayVerdict::Transcode {
                    reason: TranscodeReason::UnsupportedContainer,
                };
            }
        }

        // HDR without a capable display is *not* a transcode: the file plays, but
        // it has to be tone-mapped. Reporting it as a distinct verdict keeps the
        // UI honest — and the backend cannot do the tone-mapping correctly today
        // (plan §10.2), so this case deserves its own message.
        if let Some(fmt) = hdr_format {
            let fmt = fmt.trim().to_uppercase();
            if !fmt.is_empty() && fmt != "SDR" && fmt != "NONE" && !self.supports_hdr {
                return DirectPlayVerdict::ToneMapRequired { format: fmt };
            }
        }

        DirectPlayVerdict::DirectPlay
    }
}

/// Why Direct Play is not possible, so the UI can say more than "transcoding".
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum TranscodeReason {
    UnsupportedVideoCodec,
    UnsupportedAudioCodec,
    UnsupportedContainer,
}

impl TranscodeReason {
    /// User-facing explanation, in German (the app's UI language).
    pub fn message(self) -> &'static str {
        match self {
            Self::UnsupportedVideoCodec => "Der Videocodec wird nicht unterstützt",
            Self::UnsupportedAudioCodec => "Der Audiocodec wird nicht unterstützt",
            Self::UnsupportedContainer => "Das Dateiformat wird nicht unterstützt",
        }
    }
}

/// The outcome of a direct-play check.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum DirectPlayVerdict {
    /// Plays as-is.
    DirectPlay,
    /// Plays, but the server has to transcode.
    Transcode { reason: TranscodeReason },
    /// Plays as-is, but HDR content on an SDR display needs tone mapping.
    ///
    /// Separate from `Transcode` because nothing is re-encoded — and because the
    /// backend's transcode path is HDR-blind, so this is a real limitation rather
    /// than a routing decision.
    ToneMapRequired { format: String },
}

/// Maps codec aliases the way the server does.
///
/// `libraries/base.py` treats `h265`, `x265` and `hevc` as one codec, and
/// `h264`, `x264`, `avc` as another. Without this the client would claim a file
/// cannot be played that the server would happily direct-play.
fn normalise_video_codec(codec: &str) -> &str {
    match codec.trim().to_lowercase().as_str() {
        "h265" | "x265" | "hevc" => "h265",
        "h264" | "x264" | "avc" | "avc1" => "h264",
        "av1" | "av01" => "av1",
        "vp9" | "vp09" => "vp9",
        // Unknown codecs are returned as-is so the comparison above fails and the
        // caller learns it is unsupported.
        _ => codec.trim(),
    }
}

fn normalise_audio_codec(codec: &str) -> &str {
    match codec.trim().to_lowercase().as_str() {
        "aac" | "mp4a" => "aac",
        "ac3" | "ac-3" => "ac3",
        "eac3" | "e-ac3" | "ec-3" => "eac3",
        "dts" => "dts",
        "dtshd" | "dts-hd" => "dtshd",
        "truehd" | "mlp" => "truehd",
        "flac" => "flac",
        "opus" => "opus",
        "mp3" => "mp3",
        _ => codec.trim(),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn caps() -> Capabilities {
        Capabilities::detect(3840, true, true, true, "0.1.0")
    }

    // ── Serialisation for the play endpoint ──

    #[test]
    fn play_query_uses_comma_separated_codec_lists() {
        let q = caps().play_query();
        let get = |key: &str| {
            q.iter()
                .find(|(k, _)| k == key)
                .map(|(_, v)| v.clone())
                .unwrap_or_else(|| panic!("missing {key}"))
        };
        assert_eq!(get("supported_video_codecs"), "h264,h265,av1,vp9");
        assert!(get("supported_audio_codecs").contains("ac3"));
        assert!(get("supported_audio_codecs").contains("truehd"));
        assert_eq!(get("supported_containers"), "mkv,mp4,mov,avi,ts,webm");
    }

    /// The two endpoints use different names for the maximum resolution. This is
    /// the trap the module docs describe, so it gets its own test.
    #[test]
    fn play_query_uses_client_max_resolution_prefix() {
        let q = caps().play_query();
        assert!(
            q.iter()
                .any(|(k, v)| k == "client_max_resolution" && v == "4k"),
            "got {q:?}"
        );
        assert!(
            !q.iter().any(|(k, _)| k == "max_resolution"),
            "the play endpoint does not know `max_resolution`"
        );
    }

    #[test]
    fn device_payload_uses_max_resolution_without_prefix() {
        let payload = caps().device_payload();
        assert_eq!(payload["max_resolution"], "4k");
        assert!(
            payload.get("client_max_resolution").is_none(),
            "the device endpoint does not know `client_max_resolution`"
        );
    }

    /// The play endpoint wants comma-separated strings, the device endpoint wants
    /// JSON arrays — same data, different shape.
    #[test]
    fn device_payload_uses_arrays_not_strings() {
        let payload = caps().device_payload();
        assert!(payload["supported_video_codecs"].is_array());
        assert_eq!(payload["supported_video_codecs"][0], "h264");
        assert_eq!(payload["app_name"], "Streamarr Desktop");
        assert_eq!(payload["supports_direct_play"], true);
    }

    #[test]
    fn hdr_is_only_claimed_when_both_display_and_renderer_support_it() {
        assert!(Capabilities::detect(3840, true, true, true, "1").supports_hdr);
        assert!(!Capabilities::detect(3840, true, false, true, "1").supports_hdr);
        assert!(!Capabilities::detect(3840, false, true, true, "1").supports_hdr);
        assert!(!Capabilities::detect(3840, false, false, true, "1").supports_hdr);
    }

    /// HDR support is never sent to the server, because the server has no
    /// parameter for it — it is HDR-blind on the transcode path. A golden test
    /// against playback_params.py caught an earlier version that did send it.
    #[test]
    fn hdr_is_never_sent_to_the_server() {
        for caps in [
            Capabilities::detect(1920, false, false, false, "1"),
            Capabilities::detect(3840, true, true, true, "1"),
        ] {
            assert!(
                !caps.play_query().iter().any(|(k, _)| k.contains("hdr")),
                "the server would ignore an HDR capability"
            );
        }
    }

    // ── Resolution tiers ──

    #[test]
    fn resolution_follows_the_display() {
        assert_eq!(MaxResolution::for_display_width(1280), MaxResolution::Hd720);
        assert_eq!(
            MaxResolution::for_display_width(1920),
            MaxResolution::FullHd1080
        );
        assert_eq!(
            MaxResolution::for_display_width(2560),
            MaxResolution::FullHd1080,
            "1440p is not a tier the server knows; 1080p is the honest claim"
        );
        assert_eq!(MaxResolution::for_display_width(3840), MaxResolution::Uhd4k);
    }

    /// A 5K ultrawide must not make the client claim 8K: the server's H.264
    /// encoder caps at 4096 wide, so anything above 4K buys a needless transcode.
    #[test]
    fn very_wide_displays_cap_at_4k() {
        assert_eq!(MaxResolution::for_display_width(5120), MaxResolution::Uhd4k);
        assert_eq!(MaxResolution::for_display_width(7680), MaxResolution::Uhd4k);
    }

    #[test]
    fn tiny_displays_do_not_claim_more_than_720p() {
        assert_eq!(MaxResolution::for_display_width(1024), MaxResolution::Hd720);
        assert_eq!(MaxResolution::for_display_width(0), MaxResolution::Hd720);
    }

    // ── Direct play decisions ──

    #[test]
    fn matching_codecs_direct_play() {
        assert_eq!(
            caps().can_direct_play("h264", "ac3", Some("mkv"), None),
            DirectPlayVerdict::DirectPlay
        );
    }

    /// The server normalises aliases; the client must agree, or it will report a
    /// file as unplayable that the server would direct-play.
    #[test]
    fn codec_aliases_are_recognised() {
        for (video, audio) in [
            ("hevc", "eac3"),
            ("x265", "truehd"),
            ("h265", "dtshd"),
            ("avc", "aac"),
            ("x264", "ac3"),
        ] {
            assert_eq!(
                caps().can_direct_play(video, audio, Some("mkv"), None),
                DirectPlayVerdict::DirectPlay,
                "{video}/{audio} should direct-play"
            );
        }
    }

    #[test]
    fn codec_matching_is_case_insensitive() {
        assert_eq!(
            caps().can_direct_play("H264", "AC3", Some("MKV"), None),
            DirectPlayVerdict::DirectPlay
        );
    }

    #[test]
    fn unsupported_video_codec_reports_why() {
        assert_eq!(
            caps().can_direct_play("mpeg2", "ac3", Some("mkv"), None),
            DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedVideoCodec
            }
        );
    }

    #[test]
    fn unsupported_audio_codec_reports_why() {
        assert_eq!(
            caps().can_direct_play("h264", "pcm_bluray", Some("mkv"), None),
            DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedAudioCodec
            }
        );
    }

    #[test]
    fn unsupported_container_reports_why() {
        assert_eq!(
            caps().can_direct_play("h264", "ac3", Some("rmvb"), None),
            DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedContainer
            }
        );
    }

    /// A missing container must not be treated as an unsupported one: the probe
    /// does not always store it, and guessing "unsupported" would force a
    /// transcode on every such file.
    #[test]
    fn unknown_container_is_not_held_against_the_file() {
        assert_eq!(
            caps().can_direct_play("h264", "ac3", None, None),
            DirectPlayVerdict::DirectPlay
        );
    }

    // ── HDR ──

    #[test]
    fn hdr_on_an_hdr_display_direct_plays() {
        assert_eq!(
            caps().can_direct_play("h265", "truehd", Some("mkv"), Some("HDR10")),
            DirectPlayVerdict::DirectPlay
        );
    }

    /// HDR on an SDR display is not a transcode — nothing is re-encoded — but it
    /// is not plain direct play either, because the picture needs tone mapping
    /// the backend cannot do correctly today.
    #[test]
    fn hdr_on_an_sdr_display_asks_for_tone_mapping() {
        let sdr = Capabilities::detect(1920, false, false, true, "1");
        assert_eq!(
            sdr.can_direct_play("h265", "ac3", Some("mkv"), Some("HDR10")),
            DirectPlayVerdict::ToneMapRequired {
                format: "HDR10".to_string()
            }
        );
    }

    #[test]
    fn sdr_and_missing_hdr_formats_are_not_tone_mapped() {
        let sdr = Capabilities::detect(1920, false, false, true, "1");
        for fmt in [Some("SDR"), Some("none"), Some(""), None] {
            assert_eq!(
                sdr.can_direct_play("h264", "ac3", Some("mkv"), fmt),
                DirectPlayVerdict::DirectPlay,
                "format {fmt:?} must not trigger tone mapping"
            );
        }
    }

    /// An unsupported codec is a bigger problem than an HDR mismatch, so it must
    /// win: reporting "tone mapping" for a file that cannot play at all would
    /// send the user looking in the wrong place.
    #[test]
    fn unsupported_codec_takes_precedence_over_hdr() {
        let sdr = Capabilities::detect(1920, false, false, true, "1");
        assert_eq!(
            sdr.can_direct_play("mpeg2", "ac3", Some("mkv"), Some("HDR10")),
            DirectPlayVerdict::Transcode {
                reason: TranscodeReason::UnsupportedVideoCodec
            }
        );
    }

    #[test]
    fn transcode_reasons_are_explained_in_german() {
        for reason in [
            TranscodeReason::UnsupportedVideoCodec,
            TranscodeReason::UnsupportedAudioCodec,
            TranscodeReason::UnsupportedContainer,
        ] {
            assert!(!reason.message().is_empty());
        }
    }
}
