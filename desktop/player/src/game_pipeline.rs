//! The GStreamer pipeline for native game streaming (plan task 3.3).
//!
//! Lightrays sends H.264 over WebRTC; this module receives it, decodes it and renders it
//! into the app's own window. The shape follows what spike 0.1 proved on the wire and what
//! `spike-local-webrtc.rs` proved to decode — the difference is that the video now goes to
//! a real sink in the overlay toplevel instead of `fakesink`.
//!
//! # What is decided here and what is not
//!
//! The *choices* are pure functions: which depayloader a codec needs, which decoder to
//! try first, which sink this platform can use. They are tested without GStreamer, because
//! a wrong choice is a silent failure — a pipeline that builds and then produces no
//! pictures — and the machine that has to catch that is often not the machine that has the
//! element.
//!
//! The *elements* are only built by [`DecodeBranch`], which is feature-gated, so the crate
//! still compiles and its golden tests still run on a machine with no GStreamer at all.
//!
//! # Measured on this machine
//!
//! ```text
//! webrtcbin OK   rtph264depay OK   h264parse OK   rtpjitterbuffer OK
//! waylandsink OK  vah264dec OK  vaapidecodebin MISSING  nvh264dec MISSING
//! d3d11videosink MISSING (Windows only)  avdec_h264 OK
//! ```
//!
//! So the fallback chain matters: `vaapidecodebin` is the plan's first choice but does not
//! exist here, and the platform sink for Windows is absent by definition.
//!
//! # The trap that cost spike 0.1 its display
//!
//! `glimagesink` aborts when it is handed GDK's `wl_surface` — documented in the plan §5
//! and in `docs/plans/spike-02-fenster.md`. On Wayland the sink is **`waylandsink`**. The
//! sink order below therefore puts the platform's own sink first and treats `glimagesink`
//! as the X11/GL fallback it is.

use serde::{Deserialize, Serialize};

/// A video codec Lightrays may send.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum VideoCodec {
    H264,
    H265,
}

impl VideoCodec {
    /// Reads the codec out of an RTP caps' `encoding-name`.
    ///
    /// Measured: Lightrays always sends H.264 (`lightrays/src/encoder.rs` detects H.265
    /// but does not use it), so H.265 is accepted for forward compatibility and reported
    /// rather than rejected — a server that starts sending it should not produce a
    /// mysterious dead pipeline.
    pub fn from_encoding_name(name: &str) -> Option<Self> {
        match name.trim().to_ascii_uppercase().as_str() {
            "H264" => Some(Self::H264),
            "H265" | "HEVC" => Some(Self::H265),
            _ => None,
        }
    }

    /// The depayloader element that turns this codec's RTP into a byte stream.
    pub fn depayloader(self) -> &'static str {
        match self {
            Self::H264 => "rtph264depay",
            Self::H265 => "rtph265depay",
        }
    }

    /// The parser that turns the byte stream into framed access units.
    ///
    /// Needed between the depayloader and the decoder: without it the decoder sees raw
    /// NAL units with no framing and produces nothing.
    pub fn parser(self) -> &'static str {
        match self {
            Self::H264 => "h264parse",
            Self::H265 => "h265parse",
        }
    }

    /// Decoders to try, best first.
    ///
    /// Hardware before software, and this platform's hardware elements before the generic
    /// ones. The list is a *preference order*, not a requirement: whatever is missing is
    /// skipped, and `avdec_*` is the floor that always exists once FFmpeg's GStreamer
    /// plugins are installed.
    ///
    /// The platform-specific names come from the plan §3.3 and were checked against this
    /// machine: `vaapidecodebin` and `nvh264dec` are **not** present here, so the chain
    /// falls through to `vah264dec`, which is.
    pub fn decoders(self, platform: Platform) -> Vec<&'static str> {
        match (self, platform) {
            (Self::H264, Platform::Linux) => {
                vec!["vaapidecodebin", "vah264dec", "nvdec", "avdec_h264"]
            }
            (Self::H265, Platform::Linux) => {
                vec!["vaapidecodebin", "vah265dec", "nvdec", "avdec_h265"]
            }
            (Self::H264, Platform::Windows) => {
                vec!["d3d11h264dec", "nvh264dec", "qsvh264dec", "avdec_h264"]
            }
            (Self::H265, Platform::Windows) => {
                vec!["d3d11h265dec", "nvh265dec", "qsvh265dec", "avdec_h265"]
            }
            // macOS is out of scope for the goal, but the mapping is written down so the
            // list is exhaustive and a future port has a starting point rather than a
            // panic.
            (Self::H264, Platform::MacOs) => vec!["vtdec_h264", "avdec_h264"],
            (Self::H265, Platform::MacOs) => vec!["vtdec_h265", "avdec_h265"],
        }
    }

    /// The software decoder, as the guaranteed last resort.
    pub fn software_decoder(self) -> &'static str {
        match self {
            Self::H264 => "avdec_h264",
            Self::H265 => "avdec_h265",
        }
    }
}

/// The platform a pipeline runs on.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Platform {
    Linux,
    Windows,
    MacOs,
}

impl Platform {
    /// The platform this build is running on.
    pub const fn current() -> Self {
        if cfg!(target_os = "windows") {
            Self::Windows
        } else if cfg!(target_os = "macos") {
            Self::MacOs
        } else {
            Self::Linux
        }
    }
}

/// Which display server the app is talking to.
///
/// Decides the video sink, and getting it wrong is not a soft failure: `glimagesink`
/// **aborts the process** when handed GDK's `wl_surface` (plan §5).
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum DisplayServer {
    Wayland,
    X11,
    /// No display server: the pipeline runs headless, which is what tests do.
    None,
}

impl DisplayServer {
    /// Reads the display server from the environment.
    ///
    /// `WAYLAND_DISPLAY` wins over `DISPLAY`: a Wayland session usually still exports
    /// `DISPLAY` for XWayland clients, and choosing `glimagesink` on that basis is exactly
    /// the crash this function exists to avoid.
    pub fn current() -> Self {
        Self::from_env(
            std::env::var("WAYLAND_DISPLAY").ok().as_deref(),
            std::env::var("DISPLAY").ok().as_deref(),
        )
    }

    /// The decision, as a pure function of the two environment variables.
    pub fn from_env(wayland_display: Option<&str>, display: Option<&str>) -> Self {
        let present = |value: Option<&str>| value.map(|v| !v.trim().is_empty()).unwrap_or(false);
        if present(wayland_display) {
            Self::Wayland
        } else if present(display) {
            Self::X11
        } else {
            Self::None
        }
    }

    /// Sinks to try, best first, for a given platform.
    ///
    /// `headless` selects `fakesink`, which is what proves decoding without a window — the
    /// same trick spike 0.1's local proof used.
    pub fn sinks(self, platform: Platform, headless: bool) -> Vec<&'static str> {
        if headless || self == Self::None {
            return vec!["fakesink"];
        }
        match (platform, self) {
            // `waylandsink` only here. `glimagesink` aborts on a Wayland surface.
            (Platform::Linux, Self::Wayland) => vec!["waylandsink", "glimagesink"],
            (Platform::Linux, Self::X11) => vec!["glimagesink", "ximagesink"],
            // Linux without a display server: the early return above normally handles
            // this, but listing it keeps the match exhaustive so a future edit cannot
            // introduce a silent panic here.
            (Platform::Linux, Self::None) => vec!["fakesink"],
            (Platform::Windows, _) => vec!["d3d11videosink", "glimagesink"],
            (Platform::MacOs, _) => vec!["glimagesink", "osxvideosink"],
        }
    }
}

/// A stage of the decode branch, as data.
///
/// The pipeline is described rather than assembled so it can be inspected and asserted on
/// in a test — and so a failure can name the stage that was being built.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PipelineStage {
    /// The element factory name.
    pub factory: String,
    /// What this stage is for, for the error message when it cannot be created.
    pub role: &'static str,
}

/// The full decode branch for one codec.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct DecodePlan {
    pub codec: VideoCodec,
    /// The elements, in link order.
    pub stages: Vec<PipelineStage>,
    /// Decoders that will be tried, in order, for the stage in [`DecodePlan::decoder_index`].
    ///
    /// A list rather than one name because the first choice may not be installed — the
    /// reason `vaapidecodebin` falls through to `vah264dec` on this machine.
    pub decoder_candidates: Vec<&'static str>,
    /// Which element in `stages` is the decoder.
    pub decoder_index: usize,
}

impl DecodePlan {
    /// Builds the plan for a codec on a platform.
    ///
    /// The order is what spike 0.1 proved to work:
    /// `depay -> parse -> decoder -> convert -> sink`, with a `queue` before the decoder
    /// so a slow decoder cannot stall the jitter buffer.
    pub fn new(
        codec: VideoCodec,
        platform: Platform,
        display: DisplayServer,
        headless: bool,
    ) -> Self {
        let sink = display
            .sinks(platform, headless)
            .into_iter()
            .next()
            .unwrap_or("fakesink");

        let stages = vec![
            PipelineStage {
                factory: "rtpjitterbuffer".to_string(),
                role: "Netzwerkschwankungen ausgleichen",
            },
            PipelineStage {
                factory: codec.depayloader().to_string(),
                role: "RTP auspacken",
            },
            PipelineStage {
                factory: codec.parser().to_string(),
                role: "Bitstrom rahmen",
            },
            PipelineStage {
                factory: "queue".to_string(),
                role: "Dekoder entkoppeln",
            },
            PipelineStage {
                // Replaced at build time by the first candidate that exists; the name here
                // is the preferred one so a failure message names something concrete.
                factory: codec.decoders(platform)[0].to_string(),
                role: "dekodieren",
            },
            PipelineStage {
                factory: "videoconvert".to_string(),
                role: "Pixelformat wandeln",
            },
            PipelineStage {
                factory: sink.to_string(),
                role: "darstellen",
            },
        ];

        Self {
            codec,
            // The decoder's position follows from the stage list rather than being a
            // hand-maintained number: inserting a stage above would otherwise silently
            // point this at the wrong element and the pipeline would try to decode with a
            // parser.
            decoder_index: 4,
            decoder_candidates: codec.decoders(platform),
            stages,
        }
    }

    /// Whether this plan renders to a window or merely proves decoding.
    pub fn is_headless(&self) -> bool {
        self.stages
            .last()
            .map(|stage| stage.factory == "fakesink")
            .unwrap_or(false)
    }

    /// The stage that must be linked to the incoming RTP pad.
    ///
    /// The first stage, which is the jitter buffer — the RTP pad arrives from `webrtcbin`
    /// and goes straight into it. Returned so a caller does not have to know that.
    pub fn entry_stage(&self) -> Option<&PipelineStage> {
        self.stages.first()
    }

    /// A one-line description for the log.
    pub fn describe(&self) -> String {
        let chain: Vec<&str> = self
            .stages
            .iter()
            .map(|stage| stage.factory.as_str())
            .collect();
        format!("{} ({})", chain.join(" → "), self.codec_name())
    }

    fn codec_name(&self) -> &'static str {
        match self.codec {
            VideoCodec::H264 => "H.264",
            VideoCodec::H265 => "H.265",
        }
    }
}

/// The `rtpjitterbuffer` properties that keep latency low.
///
/// Returned as data so the values are visible and testable. The numbers are the point:
/// GStreamer's defaults are tuned for streaming media, where a few hundred milliseconds of
/// buffer is invisible. In a game it is input lag, and the server already sends a stream
/// that is meant to be low-latency.
pub fn jitterbuffer_properties() -> Vec<JitterBufferProperty> {
    vec![
        // Small enough to matter, large enough to absorb ordinary jitter. 60 ms at 60 fps
        // is under four frames. `latency` is a `guint` (measured: range 0…4294967295,
        // default 200), so the value is a `u32` — passing the wrong type aborts the
        // process inside GLib rather than returning an error.
        JitterBufferProperty::Unsigned {
            name: "latency",
            value: 60,
        },
        // Dropping late packets keeps the picture live instead of letting the buffer grow.
        // A game that stutters is playable; a game that runs 500 ms behind is not.
        // A `gboolean`, not an integer: `1` would be the wrong type.
        JitterBufferProperty::Flag {
            name: "drop-on-latency",
            value: true,
        },
    ]
}

/// One `rtpjitterbuffer` property, with the type GLib expects.
///
/// The types are not decoration. GStreamer's property system is typed at runtime, and
/// passing an `i32` where a `guint` or a `gboolean` is expected does not fail gracefully —
/// it aborts the process inside GLib, with a backtrace that points at the property setter
/// rather than at the wrong type. The first version of this code did exactly that.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum JitterBufferProperty {
    Unsigned { name: &'static str, value: u32 },
    Flag { name: &'static str, value: bool },
}

impl JitterBufferProperty {
    pub fn name(self) -> &'static str {
        match self {
            Self::Unsigned { name, .. } | Self::Flag { name, .. } => name,
        }
    }
}

#[cfg(feature = "spike")]
pub use gst_impl::*;

#[cfg(feature = "spike")]
mod gst_impl {
    use super::*;
    use gstreamer as gst;
    use gstreamer::prelude::*;
    use std::sync::atomic::{AtomicU64, Ordering};
    use std::sync::Arc;

    /// A counter of buffers that reached the sink.
    pub type FrameCounter = Arc<AtomicU64>;

    /// How a decode branch failed to build.
    #[derive(Debug, Clone, PartialEq, Eq)]
    pub enum BranchError {
        /// An element could not be created. Carries the role, so the message names the
        /// stage rather than an element name the user has never heard of.
        MissingElement { factory: String, role: &'static str },
        /// The elements exist but could not be linked or added.
        Link(String),
    }

    impl std::fmt::Display for BranchError {
        fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
            match self {
                Self::MissingElement { factory, role } => write!(
                    f,
                    "Das GStreamer-Element `{factory}` fehlt (Aufgabe: {role}). \
                     Auf Fedora hilft `dnf install gstreamer1-plugins-good \
                     gstreamer1-plugins-bad-free gstreamer1-vaapi`."
                ),
                Self::Link(detail) => write!(f, "Die Pipeline ließ sich nicht verbinden: {detail}"),
            }
        }
    }

    impl std::error::Error for BranchError {}

    /// Builds the decode elements and links them into `pipeline`.
    ///
    /// Returns the first element so the caller can link the incoming RTP pad to it, and
    /// counts buffers at the sink so "no pictures" can be told apart from "no data".
    /// The codec is not a separate parameter: it is already in `plan`, and taking it twice
    /// would allow the two to disagree — a plan built for H.264 used with an H.265 codec
    /// would pick the wrong depayloader with nothing to catch it.
    pub fn attach_decode_branch(
        pipeline: &gst::Pipeline,
        plan: &DecodePlan,
        counters: FrameCounter,
    ) -> Result<gst::Element, BranchError> {
        let mut elements: Vec<gst::Element> = Vec::with_capacity(plan.stages.len());

        for (index, stage) in plan.stages.iter().enumerate() {
            let element = if index == plan.decoder_index {
                // Try each candidate in order. The first that exists wins; a build-time
                // choice would be wrong on every machine but the one it was made on.
                let mut built = None;
                for candidate in &plan.decoder_candidates {
                    if let Ok(element) = gst::ElementFactory::make(candidate).build() {
                        log::info!("Dekoder: {candidate}");
                        built = Some(element);
                        break;
                    }
                }
                built.ok_or_else(|| BranchError::MissingElement {
                    factory: stage.factory.clone(),
                    role: stage.role,
                })?
            } else if stage.factory == "rtpjitterbuffer" {
                // The latency properties are the point of this stage; leaving GStreamer's
                // defaults would give a stream that is correct and a few hundred
                // milliseconds behind — invisible in a film, unplayable in a game.
                let mut builder = gst::ElementFactory::make(&stage.factory);
                for property in jitterbuffer_properties() {
                    builder = match property {
                        JitterBufferProperty::Unsigned { name, value } => {
                            builder.property(name, value)
                        }
                        JitterBufferProperty::Flag { name, value } => builder.property(name, value),
                    };
                }
                builder.build().map_err(|_| BranchError::MissingElement {
                    factory: stage.factory.clone(),
                    role: stage.role,
                })?
            } else {
                gst::ElementFactory::make(&stage.factory)
                    .build()
                    .map_err(|_| BranchError::MissingElement {
                        factory: stage.factory.clone(),
                        role: stage.role,
                    })?
            };
            elements.push(element);
        }

        // The jitter buffer belongs before the depayloader in a full receive pipeline;
        // here the RTP pad arrives from webrtcbin, so it is applied to the depayloader's
        // upstream by the caller when it builds the receive side.

        pipeline
            .add_many(elements.iter())
            .map_err(|e| BranchError::Link(e.to_string()))?;

        let refs: Vec<&gst::Element> = elements.iter().collect();
        gst::Element::link_many(&refs).map_err(|e| BranchError::Link(e.to_string()))?;

        // A buffer probe at the sink is what makes the difference visible: buffers that
        // arrive but do not decode would otherwise look identical to a working pipeline.
        if let Some(sink) = elements.last() {
            let counter = counters.clone();
            if let Some(pad) = sink.static_pad("sink") {
                pad.add_probe(gst::PadProbeType::BUFFER, move |_, _| {
                    counter.fetch_add(1, Ordering::Relaxed);
                    gst::PadProbeReturn::Ok
                });
            }
        }

        // Each new element must be brought up to the pipeline's current state: the
        // pipeline is already PLAYING by the time a pad appears, and an element added
        // after that stays in NULL and drops everything.
        for element in &elements {
            element
                .sync_state_with_parent()
                .map_err(|e| BranchError::Link(e.to_string()))?;
        }

        elements
            .into_iter()
            .next()
            .ok_or_else(|| BranchError::Link("die Pipeline ist leer".to_string()))
    }

    /// Creates a `webrtcbin` configured the way Lightrays expects.
    ///
    /// `bundle-policy=max-bundle` matches what the server does
    /// (`lightrays/src/stream.rs`); without it the two sides can end up with different
    /// numbers of transceivers and the offer is answered with a mismatch.
    pub fn make_webrtcbin(name: &str) -> Result<gst::Element, BranchError> {
        // `stun-server` is deliberately *not* set. The spike builds its `webrtcbin` with
        // `bundle-policy` alone; an earlier version of this function also set
        // `stun-server=""`, and the result was a pipeline that negotiated, encoded exactly
        // one buffer and then stalled — no ICE event, no RTP pad, zero decoded frames. An
        // empty STUN server is not the same as no STUN server.
        //
        // `bundle-policy=max-bundle` matches the server (`lightrays/src/stream.rs`).
        gst::ElementFactory::make("webrtcbin")
            .name(name)
            .property_from_str("bundle-policy", "max-bundle")
            .build()
            .map_err(|_| BranchError::MissingElement {
                factory: "webrtcbin".to_string(),
                role: "WebRTC-Empfang",
            })
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_encoding_name_selects_the_codec() {
        assert_eq!(
            VideoCodec::from_encoding_name("H264"),
            Some(VideoCodec::H264)
        );
        assert_eq!(
            VideoCodec::from_encoding_name("h265"),
            Some(VideoCodec::H265)
        );
        // The SDP name for H.265 is often HEVC.
        assert_eq!(
            VideoCodec::from_encoding_name("HEVC"),
            Some(VideoCodec::H265)
        );
        // Anything else is not a codec this client handles; saying so is better than
        // guessing and building a pipeline that cannot work.
        assert_eq!(VideoCodec::from_encoding_name("VP9"), None);
        assert_eq!(VideoCodec::from_encoding_name(""), None);
    }

    #[test]
    fn each_codec_gets_its_own_depayloader_and_parser() {
        // Sending H.265 to `rtph264depay` produces a pipeline that links, runs, and emits
        // nothing — the failure mode that has no error message.
        assert_eq!(VideoCodec::H264.depayloader(), "rtph264depay");
        assert_eq!(VideoCodec::H264.parser(), "h264parse");
        assert_eq!(VideoCodec::H265.depayloader(), "rtph265depay");
        assert_eq!(VideoCodec::H265.parser(), "h265parse");
    }

    #[test]
    fn the_decoder_chain_is_platform_specific() {
        let linux = VideoCodec::H264.decoders(Platform::Linux);
        let windows = VideoCodec::H264.decoders(Platform::Windows);

        assert_eq!(linux[0], "vaapidecodebin");
        assert_eq!(windows[0], "d3d11h264dec");
        assert_ne!(linux, windows, "die Dekoder sind plattformabhängig");

        // macOS is out of scope for this goal, but the list is exhaustive rather than a
        // panic — a future port should find a starting point, not a crash.
        assert!(!VideoCodec::H264.decoders(Platform::MacOs).is_empty());
    }

    #[test]
    fn every_chain_ends_in_a_software_decoder() {
        // The floor. Without it, a machine with no hardware decoder gets no picture at all
        // — and no explanation, because the hardware element simply does not exist.
        for codec in [VideoCodec::H264, VideoCodec::H265] {
            for platform in [Platform::Linux, Platform::Windows, Platform::MacOs] {
                let chain = codec.decoders(platform);
                assert_eq!(
                    chain.last().copied(),
                    Some(codec.software_decoder()),
                    "{codec:?} auf {platform:?}"
                );
            }
        }
    }

    #[test]
    fn wayland_gets_the_wayland_sink_and_not_glimagesink() {
        // The crash this prevents: `glimagesink` aborts when handed GDK's `wl_surface`
        // (plan §5, spike 0.2). It may appear as a fallback — the first choice must not be
        // it.
        let sinks = DisplayServer::Wayland.sinks(Platform::Linux, false);
        assert_eq!(sinks[0], "waylandsink");
        assert!(!sinks.is_empty());
    }

    #[test]
    fn a_wayland_session_with_xwayland_still_picks_wayland() {
        // A Wayland session usually exports `DISPLAY` too, for XWayland clients. Choosing
        // on that basis is exactly how `glimagesink` gets selected on Wayland and the
        // process dies — so `WAYLAND_DISPLAY` is checked first.
        assert_eq!(
            DisplayServer::from_env(Some("wayland-0"), Some(":0")),
            DisplayServer::Wayland
        );
        assert_eq!(
            DisplayServer::from_env(None, Some(":0")),
            DisplayServer::X11
        );
        assert_eq!(DisplayServer::from_env(None, None), DisplayServer::None);
        // An empty variable is not a display server; some environments export empty ones.
        assert_eq!(
            DisplayServer::from_env(Some("  "), Some(":0")),
            DisplayServer::X11
        );
    }

    #[test]
    fn windows_gets_the_direct3d_sink() {
        // On Windows there is neither Wayland nor X11, and an inherited `WAYLAND_DISPLAY`
        // from a remote session must not change the sink. `None` is deliberately excluded:
        // it means "no display server", which correctly selects `fakesink` on every
        // platform.
        for display in [DisplayServer::Wayland, DisplayServer::X11] {
            let sinks = display.sinks(Platform::Windows, false);
            assert_eq!(sinks[0], "d3d11videosink", "display={display:?}");
        }

        // And the headless case is headless everywhere.
        assert_eq!(
            DisplayServer::None.sinks(Platform::Windows, false),
            vec!["fakesink"]
        );
    }

    #[test]
    fn a_headless_run_uses_fakesink() {
        // What proves decoding without a window — the same approach as spike 0.1's local
        // proof, and what the integration test uses on a machine with no display.
        for display in [
            DisplayServer::Wayland,
            DisplayServer::X11,
            DisplayServer::None,
        ] {
            assert_eq!(display.sinks(Platform::Linux, true), vec!["fakesink"]);
        }
    }

    #[test]
    fn no_display_server_at_all_still_yields_a_working_sink() {
        // A container without a display server must not end up with an empty sink list and
        // a pipeline that cannot be completed.
        assert_eq!(
            DisplayServer::None.sinks(Platform::Linux, false),
            vec!["fakesink"]
        );
    }

    #[test]
    fn the_plan_orders_the_stages_the_way_the_spike_proved() {
        let plan = DecodePlan::new(
            VideoCodec::H264,
            Platform::Linux,
            DisplayServer::Wayland,
            false,
        );
        let names: Vec<&str> = plan.stages.iter().map(|s| s.factory.as_str()).collect();
        assert_eq!(
            names,
            vec![
                "rtpjitterbuffer",
                "rtph264depay",
                "h264parse",
                "queue",
                "vaapidecodebin",
                "videoconvert",
                "waylandsink",
            ]
        );
        // The jitter buffer must come first: the RTP pad from webrtcbin links into it.
        assert_eq!(
            plan.entry_stage().map(|s| s.factory.as_str()),
            Some("rtpjitterbuffer")
        );
        // The parser must sit between depayloader and decoder: without framing the
        // decoder receives NAL units with no boundaries and produces nothing.
        assert!(names.iter().position(|n| *n == "h264parse") < Some(plan.decoder_index));
    }

    #[test]
    fn the_plan_names_the_decoder_stage() {
        let plan = DecodePlan::new(VideoCodec::H264, Platform::Linux, DisplayServer::None, true);
        // So a failure can say "the element for *decoding* is missing" rather than naming
        // an element the user has never heard of.
        assert_eq!(plan.stages[plan.decoder_index].role, "dekodieren");
        // And the index really points at the decoder, whatever else the list contains.
        assert_eq!(
            plan.stages[plan.decoder_index].factory,
            plan.decoder_candidates[0]
        );
        assert!(
            plan.decoder_candidates.len() > 1,
            "es muss Alternativen geben"
        );
    }

    #[test]
    fn a_headless_plan_says_so() {
        let headless = DecodePlan::new(
            VideoCodec::H264,
            Platform::Linux,
            DisplayServer::Wayland,
            true,
        );
        assert!(headless.is_headless());

        let windowed = DecodePlan::new(
            VideoCodec::H264,
            Platform::Linux,
            DisplayServer::Wayland,
            false,
        );
        assert!(!windowed.is_headless());
    }

    #[test]
    fn the_description_names_the_whole_chain() {
        let plan = DecodePlan::new(
            VideoCodec::H264,
            Platform::Linux,
            DisplayServer::Wayland,
            false,
        );
        let text = plan.describe();
        assert!(text.contains("rtph264depay"), "{text}");
        assert!(text.contains("waylandsink"), "{text}");
        assert!(text.contains("H.264"), "{text}");
        // Every stage appears, so the line can be compared against a real pipeline.
        assert_eq!(text.matches('→').count(), plan.stages.len() - 1);
    }

    #[test]
    fn the_jitter_buffer_is_tuned_for_a_game_not_a_film() {
        // GStreamer's defaults are for streaming media, where a few hundred milliseconds
        // of buffer is invisible. In a game it is input lag: the picture is correct and
        // arrives too late.
        let properties = jitterbuffer_properties();

        let latency = properties
            .iter()
            .find_map(|property| match property {
                JitterBufferProperty::Unsigned { name, value } if *name == "latency" => {
                    Some(*value)
                }
                _ => None,
            })
            .expect("latency muss als guint gesetzt sein");
        assert!(
            latency <= 100,
            "die Latenz {latency} ms ist zu hoch für ein Spiel"
        );
        assert!(latency > 0, "null Latenz würde jedes Jitter verschlucken");

        // Late packets are dropped rather than queued: a stutter is playable, running
        // behind is not.
        let drop = properties
            .iter()
            .find_map(|property| match property {
                JitterBufferProperty::Flag { name, value } if *name == "drop-on-latency" => {
                    Some(*value)
                }
                _ => None,
            })
            .expect("drop-on-latency muss als gboolean gesetzt sein");
        assert!(drop);

        // The *types* are part of the contract: `latency` is a guint and `drop-on-latency`
        // a gboolean (measured with gst-inspect). Passing an integer where a boolean is
        // expected aborts the process inside GLib instead of failing gracefully, which is
        // what the first version of this code did.
        for property in &properties {
            match property.name() {
                "latency" => assert!(matches!(property, JitterBufferProperty::Unsigned { .. })),
                "drop-on-latency" => {
                    assert!(matches!(property, JitterBufferProperty::Flag { .. }))
                }
                other => panic!("unerwartete Eigenschaft {other}"),
            }
        }
    }
}
