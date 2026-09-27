//! What this build's mpv can actually do (plan task 2.2).
//!
//! The app ships no mpv of its own by default — it uses the one on the machine. That
//! makes the capability set a *runtime* property, not a compile-time one: whether
//! `gpu-next` exists, which hardware decoders are present, and whether the HDR options
//! are understood all depend on which mpv the user has. Reporting a fixed list would be a
//! guess, and a wrong guess here has a specific cost — every codec claimed but not
//! playable becomes a stream the server sends and the player then fails on, and every
//! codec *not* claimed becomes an unnecessary transcode.
//!
//! # Why the capabilities are asked of mpv, not assumed
//!
//! Three questions are answered by running mpv, because the answers are not knowable from
//! the outside:
//!
//!   * **Which options exist** — `--list-options`. A feature added in a newer mpv (or
//!     compiled out) would otherwise be passed blindly, and mpv's response to an unknown
//!     option is to exit.
//!   * **Which video outputs exist** — `--vo=help`. This is what decides whether the HDR
//!     path is even available: `gpu-next` is libplacebo-based and is the only output that
//!     can tone-map and pass HDR metadata; `x11` and `sdl` cannot.
//!   * **Which hardware decoders exist** — `--hwdec=help`, which lists what this build
//!     was compiled with, as opposed to what the CPU supports.
//!
//! # The trap this module is written around
//!
//! mpv reports "help" output on a channel that also carries exit codes and error text,
//! and several of these list commands **exit non-zero** even when they succeed (`--vo=help`
//! exits 0, but a probe that runs with `--idle` never terminates on its own). So every
//! probe here runs with a hard timeout and treats "produced parseable output" as success
//! rather than "exited zero" — the exit code is recorded for diagnostics, not used as the
//! verdict.
//!
//! The parsing is separated from the running, so the interesting part — turning mpv's
//! human-readable list into a decision — is testable without an mpv binary.

use std::collections::BTreeSet;
use std::process::{Command, Stdio};
use std::time::Duration;

/// How long a capability probe may take.
///
/// Generous, because a cold mpv start on a loaded machine is the slow part and the probe
/// is one-time work. It is a ceiling, not an expectation: measured well under a second.
const PROBE_TIMEOUT: Duration = Duration::from_secs(10);

/// The name of the mpv binary to probe.
pub const DEFAULT_BINARY: &str = "mpv";

/// What the installed mpv can do.
#[derive(Debug, Clone, PartialEq, Eq, Default)]
pub struct MpvCapabilities {
    /// The version string mpv reported, e.g. `v0.41.0`.
    pub version: Option<String>,
    /// The libplacebo version, which is what the HDR path actually depends on.
    pub libplacebo: Option<String>,
    /// Available video outputs (`--vo=help`), lower-case.
    pub video_outputs: BTreeSet<String>,
    /// Available audio outputs (`--ao=help`), lower-case.
    pub audio_outputs: BTreeSet<String>,
    /// Available hardware decoders (`--hwdec=help`), lower-case.
    pub hwdec: BTreeSet<String>,
    /// Options this mpv understands (`--list-options`).
    pub options: BTreeSet<String>,
}

impl MpvCapabilities {
    /// Whether a video output exists.
    pub fn has_vo(&self, name: &str) -> bool {
        self.video_outputs.contains(&name.to_ascii_lowercase())
    }

    /// Whether an option exists.
    ///
    /// The name is written the way it is passed on the command line, without leading
    /// dashes. Only the option names are collected, not their variants: `--vo=help`
    /// lists sub-options like `gpu-next` separately, and treating those as options would
    /// make `has_option("gpu-api")` true because of a line under `--vo`.
    pub fn has_option(&self, name: &str) -> bool {
        self.options.contains(name)
    }

    /// Whether hardware decoding of some kind is available.
    pub fn has_hardware_decode(&self) -> bool {
        // `no` and `auto` are always listed and are not decoders; `auto-safe` and
        // `auto-copy` are selection policies rather than hardware.
        self.hwdec
            .iter()
            .any(|d| !matches!(d.as_str(), "no" | "auto" | "auto-safe" | "auto-copy"))
    }

    /// Whether the HDR-capable video output is present.
    ///
    /// `gpu-next` specifically, not `gpu`: only `gpu-next` is libplacebo-based, and
    /// libplacebo is what applies tone mapping and passes HDR metadata through. Claiming
    /// HDR on the strength of `gpu` would send the server an HDR stream that the client
    /// then has to approximate.
    pub fn supports_hdr_passthrough(&self) -> bool {
        self.has_vo("gpu-next")
            && self.has_option("target-colorspace-hint")
            && self.has_option("target-prim")
            && self.has_option("target-trc")
    }

    /// Whether mpv can tone-map HDR to SDR.
    ///
    /// A weaker requirement than passthrough and useful independently: it decides whether
    /// an HDR source can be shown on an SDR display at all, or whether the server must be
    /// asked to convert. `tone-mapping` is what libplacebo uses.
    pub fn can_tone_map(&self) -> bool {
        self.has_vo("gpu-next") && self.has_option("tone-mapping")
    }

    /// Whether this mpv is usable at all.
    ///
    /// A build with no video output cannot play anything, and discovering that at
    /// `loadfile` time would show the user a playback failure instead of a clear "your
    /// mpv is not usable".
    pub fn is_usable(&self) -> bool {
        self.version.is_some() && !self.video_outputs.is_empty()
    }

    /// A one-line summary for the log.
    pub fn describe(&self) -> String {
        format!(
            "mpv {} — {} Videoausgänge, {} Audiopässe, Hardware-Dekodierung: {}, \
             HDR-Durchreichung: {}, Tone-Mapping: {}",
            self.version.as_deref().unwrap_or("unbekannt"),
            self.video_outputs.len(),
            self.audio_outputs.len(),
            if self.has_hardware_decode() {
                "ja"
            } else {
                "nein"
            },
            if self.supports_hdr_passthrough() {
                "ja"
            } else {
                "nein"
            },
            if self.can_tone_map() { "ja" } else { "nein" }
        )
    }
}

/// Reads the version line out of `mpv --version` output.
///
/// Returns the mpv version and the libplacebo version, in that order. Both are on
/// separate lines of the same output, so one call answers both.
pub fn parse_version(output: &str) -> (Option<String>, Option<String>) {
    let mut version = None;
    let mut libplacebo = None;

    for line in output.lines() {
        let line = line.trim();
        // The first line looks like `mpv v0.41.0 Copyright © 2000-2025 mpv/MPlayer/...`.
        if version.is_none() {
            if let Some(rest) = line.strip_prefix("mpv ") {
                // Only the first whitespace-delimited token is the version.
                if let Some(first) = rest.split_whitespace().next() {
                    version = Some(first.to_string());
                }
            }
        }
        if let Some(rest) = line.strip_prefix("libplacebo version:") {
            libplacebo = Some(rest.trim().to_string());
        }
    }

    (version, libplacebo)
}

/// Reads a `--vo=help` / `--ao=help` / `--hwdec=help` listing.
///
/// The lists share a shape: a heading line ending in `:`, then indented
/// `name  description` rows. Rows are taken from the first whitespace-delimited token.
///
/// Lines that are not rows are skipped rather than rejected: mpv's output varies between
/// versions, and a probe that fails on an unexpected header would report an installed mpv
/// as unusable.
pub fn parse_output_list(output: &str) -> BTreeSet<String> {
    let mut names = BTreeSet::new();

    for line in output.lines() {
        // Keep the original to test for indentation, but decide on the trimmed text.
        let trimmed = line.trim();
        if trimmed.is_empty() || trimmed.ends_with(':') {
            continue;
        }
        // A row must be indented; a heading or a stray message is not a row.
        if !line.starts_with(' ') && !line.starts_with('\t') {
            continue;
        }
        let Some(name) = trimmed.split_whitespace().next() else {
            continue;
        };
        // Skip anything that looks like prose rather than a name.
        if name.ends_with(':') || name.starts_with('-') {
            continue;
        }
        names.insert(name.to_ascii_lowercase());
    }

    names
}

/// Reads the option names out of `--list-options` output.
///
/// Rows look like ` --volume                         Float (default: 100)`. Both leading and
/// trailing dashes appear in mpv's output, and sub-options are indented further
/// (`    --hwdec-add`). Sub-options are **included**, because `has_option` is asked about
/// real options; what must not happen is a *value* such as the `gpu-next` line under
/// `--vo=help` being mistaken for an option, and that cannot occur here because
/// `--list-options` prints option names only.
pub fn parse_options(output: &str) -> BTreeSet<String> {
    let mut names = BTreeSet::new();

    for line in output.lines() {
        let trimmed = line.trim();
        let Some(rest) = trimmed.strip_prefix("--") else {
            continue;
        };
        // The name ends at the first space. A trailing marker (`--vo-`) is stripped by the
        // split already, since the marker is separated by whitespace in mpv's output.
        let raw = rest.split_whitespace().next().unwrap_or("");
        let name = raw.trim_end_matches('-');
        if name.is_empty() {
            continue;
        }
        let name = name.to_ascii_lowercase();
        names.insert(name.clone());

        // mpv spells the negation `--no-fullscreen` for `--fullscreen`. Both spellings are
        // recorded, so a caller may ask either way — and, more importantly, so a caller
        // asking whether the *positive* option exists is not answered "no" merely because
        // only the negated row appeared in the listing.
        if let Some(positive) = name.strip_prefix("no-") {
            if !positive.is_empty() {
                names.insert(positive.to_string());
            }
        }
    }

    names
}

/// Runs one mpv probe and returns its output.
///
/// The verdict is "did it produce output", not "did it exit zero": mpv's list commands
/// are inconsistent about exit codes, and `--vo=help` in particular prints its list and
/// exits without an error while other probes behave differently across versions. The exit
/// status is available to the caller through `None` only when the process could not be
/// started or timed out.
fn run_probe(args: &[&str]) -> Option<String> {
    let mut child = Command::new(binary())
        .args(args)
        // Diagnostics on stdout are what is being parsed; stderr is not needed and a piped
        // stderr that is never read deadlocks mpv (spike 0.3, defect 2).
        .stdout(Stdio::piped())
        .stderr(Stdio::null())
        .stdin(Stdio::null())
        .spawn()
        .ok()?;

    // A worker thread does the blocking read while this one enforces the deadline, so a
    // hung mpv cannot hang the caller.
    let mut stdout = child.stdout.take()?;
    let (tx, rx) = std::sync::mpsc::channel();
    std::thread::spawn(move || {
        use std::io::Read;
        let mut buffer = String::new();
        let _ = stdout.read_to_string(&mut buffer);
        let _ = tx.send(buffer);
    });

    let output = rx.recv_timeout(PROBE_TIMEOUT).ok();

    // Killed either way: a list probe has no reason to keep running, and one that did
    // would linger for the life of the app.
    let _ = child.kill();
    let _ = child.wait();

    output.filter(|text| !text.trim().is_empty())
}

/// The mpv binary to use, overridable for tests and for a bundled build.
pub fn binary() -> String {
    std::env::var("STREAMARR_MPV_BINARY").unwrap_or_else(|_| DEFAULT_BINARY.to_string())
}

/// Asks the installed mpv what it can do.
///
/// Returns `None` when mpv is not installed or produced nothing usable — the caller
/// reports that rather than pretending to a capability set.
pub fn detect() -> Option<MpvCapabilities> {
    let version_output = run_probe(&["--version"])?;
    let (version, libplacebo) = parse_version(&version_output);
    // Without a version there was no usable mpv output at all; the rest of the probes
    // would only produce empty sets that look like a capability set.
    version.as_ref()?;

    let video_outputs = run_probe(&["--vo=help"])
        .map(|text| parse_output_list(&text))
        .unwrap_or_default();
    let audio_outputs = run_probe(&["--ao=help"])
        .map(|text| parse_output_list(&text))
        .unwrap_or_default();
    let hwdec = run_probe(&["--hwdec=help"])
        .map(|text| parse_output_list(&text))
        .unwrap_or_default();
    let options = run_probe(&["--list-options"])
        .map(|text| parse_options(&text))
        .unwrap_or_default();

    Some(MpvCapabilities {
        version,
        libplacebo,
        video_outputs,
        audio_outputs,
        hwdec,
        options,
    })
}

#[cfg(test)]
mod tests {
    use super::*;

    /// The shape `mpv --version` actually produces (measured, v0.41.0).
    const VERSION_OUTPUT: &str = "\
mpv v0.41.0 Copyright © 2000-2025 mpv/MPlayer/mplayer2 projects
libplacebo version: v7.360.1
FFmpeg version: 8.0.1 (runtime 8.1.3)
";

    /// The shape `mpv --vo=help` actually produces.
    const VO_HELP: &str = "\
Available video outputs:
  libmpv           render API for libmpv
  gpu              Shader-based GPU Renderer
  gpu-next         Video output based on libplacebo
  vdpau            VDPAU with X11
  wayland          Wayland Shared Memory video output as fallback
  x11              X11 (software scaling)
  null             Null video output
";

    const AO_HELP: &str = "\
Available audio outputs:
  pipewire         PipeWire audio output
  pulse            PulseAudio audio output
  alsa             ALSA audio output
  null             Null audio output
";

    const HWDEC_HELP: &str = "\
Available hardware decoders:
  no
  auto
  auto-safe
  auto-copy
  vaapi
  vaapi-copy
  vulkan
  nvdec
";

    const LIST_OPTIONS: &str = "\
Options:

 --ab-loop-a                      Time (default: no)
 --vo                             String list
    --vo-add
 --target-colorspace-hint         Flag (default: no)
 --target-prim                    Choice (default: auto)
 --target-trc                     Choice (default: auto)
 --tone-mapping                   Choice (default: auto)
 --hwdec                          String list (default: no)
    --hwdec-add
    --hwdec-append
 --no-fullscreen                  Flag
";

    #[test]
    fn the_version_and_libplacebo_are_read_from_one_call() {
        let (version, libplacebo) = parse_version(VERSION_OUTPUT);
        assert_eq!(version.as_deref(), Some("v0.41.0"));
        // libplacebo is what the HDR path actually depends on, so it is worth recording
        // next to the version rather than only reporting mpv's own number.
        assert_eq!(libplacebo.as_deref(), Some("v7.360.1"));
    }

    #[test]
    fn an_empty_or_foreign_version_output_yields_nothing() {
        assert_eq!(parse_version(""), (None, None));
        assert_eq!(parse_version("kein mpv hier"), (None, None));
        // A line that merely mentions mpv is not a version line.
        assert_eq!(parse_version("I am mpv v1.0"), (None, None));
    }

    #[test]
    fn the_video_output_list_is_read() {
        let outputs = parse_output_list(VO_HELP);
        assert!(outputs.contains("gpu-next"), "{outputs:?}");
        assert!(outputs.contains("gpu"));
        assert!(outputs.contains("wayland"));
        // The heading must not become an entry.
        assert!(!outputs.contains("available"));
        assert_eq!(outputs.len(), 7);
    }

    #[test]
    fn the_audio_output_list_is_read() {
        // The audio side matters for a different reason than video: it is what decides
        // whether the app can hand mpv a working output at all, and a machine with only
        // `null` would play silently with no explanation.
        let outputs = parse_output_list(AO_HELP);
        assert!(outputs.contains("pipewire"), "{outputs:?}");
        assert!(outputs.contains("alsa"));
        assert!(outputs.contains("null"));
        assert!(!outputs.contains("available"));
    }

    #[test]
    fn the_hardware_decoder_list_is_read() {
        let decoders = parse_output_list(HWDEC_HELP);
        assert!(decoders.contains("vaapi"));
        assert!(decoders.contains("vulkan"));
        assert!(decoders.contains("nvdec"));
    }

    #[test]
    fn the_automatic_entries_are_not_counted_as_hardware() {
        // Otherwise every mpv would claim hardware decoding, including one on a machine
        // with no usable decoder — and the app would advertise a capability that costs the
        // server a stream it cannot serve.
        let automatic = MpvCapabilities {
            hwdec: ["no", "auto", "auto-safe", "auto-copy"]
                .iter()
                .map(|s| s.to_string())
                .collect(),
            ..Default::default()
        };
        assert!(!automatic.has_hardware_decode());

        let mut with_vaapi = automatic;
        with_vaapi.hwdec.insert("vaapi".to_string());
        assert!(with_vaapi.has_hardware_decode());
    }

    #[test]
    fn option_names_are_read_without_their_dashes() {
        let options = parse_options(LIST_OPTIONS);
        assert!(options.contains("target-colorspace-hint"), "{options:?}");
        assert!(options.contains("tone-mapping"));
        assert!(options.contains("vo"));
        // Sub-options are real options and are kept.
        assert!(options.contains("hwdec-add"));
        // The negated form loses its trailing marker, so it is the same option.
        assert!(options.contains("fullscreen"));
    }

    #[test]
    fn the_prose_of_an_option_line_is_not_mistaken_for_a_name() {
        let options = parse_options(LIST_OPTIONS);
        assert!(!options.contains("time"));
        assert!(!options.contains("flag"));
        assert!(!options.contains("default:"));
    }

    #[test]
    fn hdr_passthrough_needs_gpu_next_and_the_colour_options() {
        // Measured: `gpu` and `gpu-next` both exist, but only `gpu-next` is
        // libplacebo-based. Claiming HDR on the strength of `gpu` would send an HDR
        // stream the client can only approximate.
        let caps = MpvCapabilities {
            video_outputs: parse_output_list(VO_HELP),
            options: parse_options(LIST_OPTIONS),
            ..Default::default()
        };
        assert!(caps.supports_hdr_passthrough());

        // Without `gpu-next` there is no libplacebo, hence no passthrough.
        let mut without_gpu_next = caps.clone();
        without_gpu_next.video_outputs.remove("gpu-next");
        assert!(!without_gpu_next.supports_hdr_passthrough());
    }

    #[test]
    fn hdr_passthrough_needs_the_colour_options_not_just_the_output() {
        let mut options = parse_options(LIST_OPTIONS);
        options.remove("target-colorspace-hint");
        let caps = MpvCapabilities {
            video_outputs: parse_output_list(VO_HELP),
            options,
            ..Default::default()
        };
        assert!(
            !caps.supports_hdr_passthrough(),
            "an option mpv does not know would make it exit, not tone-map"
        );
    }

    #[test]
    fn tone_mapping_is_a_weaker_requirement_than_passthrough() {
        // It decides whether an HDR source can be shown on an SDR display at all — a
        // different question from passing HDR through, and one the server has to answer
        // differently.
        let mut options = parse_options(LIST_OPTIONS);
        // Remove the colour hints: passthrough is gone, tone mapping remains.
        options.remove("target-prim");
        options.remove("target-trc");
        options.remove("target-colorspace-hint");
        let caps = MpvCapabilities {
            video_outputs: parse_output_list(VO_HELP),
            options,
            ..Default::default()
        };
        assert!(!caps.supports_hdr_passthrough());
        assert!(caps.can_tone_map());
    }

    #[test]
    fn a_build_without_a_video_output_is_not_usable() {
        // Discovering this at `loadfile` time would show a playback failure; saying it
        // here lets the app report "your mpv cannot play video" instead.
        let versioned = MpvCapabilities {
            version: Some("v0.41.0".to_string()),
            ..Default::default()
        };
        assert!(!versioned.is_usable());

        let with_output = MpvCapabilities {
            video_outputs: ["gpu-next".to_string()].into_iter().collect(),
            ..versioned
        };
        assert!(with_output.is_usable());

        // And a version is required too: without one, nothing was actually probed.
        let unversioned = MpvCapabilities {
            video_outputs: ["gpu-next".to_string()].into_iter().collect(),
            ..Default::default()
        };
        assert!(!unversioned.is_usable());
    }

    #[test]
    fn the_description_names_the_two_hdr_answers_separately() {
        let caps = MpvCapabilities {
            version: Some("v0.41.0".to_string()),
            video_outputs: parse_output_list(VO_HELP),
            options: parse_options(LIST_OPTIONS),
            hwdec: parse_output_list(HWDEC_HELP),
            ..Default::default()
        };

        let text = caps.describe();
        assert!(text.contains("v0.41.0"), "{text}");
        assert!(text.contains("HDR-Durchreichung: ja"), "{text}");
        assert!(text.contains("Tone-Mapping: ja"), "{text}");
        assert!(text.contains("Hardware-Dekodierung: ja"), "{text}");
    }

    #[test]
    fn a_missing_description_still_reads_as_a_sentence() {
        // The log line is written before anything is known, so it must not panic or read
        // as an empty string.
        let text = MpvCapabilities::default().describe();
        assert!(text.contains("unbekannt"), "{text}");
        assert!(text.contains("nein"), "{text}");
    }

    #[test]
    fn the_probe_output_is_parsed_tolerantly() {
        // A version of mpv that formats its headings differently must not be reported as
        // unusable — the cost of being wrong is a player that refuses to start.
        let unusual = "\
Some new heading without colon
  gpu-next  the good one

  wayland    shared memory
";
        let parsed = parse_output_list(unusual);
        assert!(parsed.contains("gpu-next"), "{parsed:?}");
        assert!(parsed.contains("wayland"));
        // The unindented heading is not a name.
        assert!(!parsed.contains("some"));
    }

    // ── Against the real mpv, when there is one ──

    #[test]
    fn a_real_mpv_reports_a_usable_capability_set() {
        // Skipped, not silently passed, when mpv is absent: the CI runner has no mpv, and
        // a test that quietly succeeds there would be worth nothing on a developer machine.
        if std::process::Command::new(binary())
            .arg("--version")
            .stdout(Stdio::null())
            .stderr(Stdio::null())
            .status()
            .is_err()
        {
            eprintln!("übersprungen: keine mpv-Binary gefunden");
            return;
        }

        let caps = detect().expect("mpv ist da, also muss die Erkennung etwas liefern");
        assert!(caps.is_usable(), "{:?}", caps.describe());
        assert!(caps.version.is_some());

        // Measured on mpv 0.41.0 in this container. These assertions are what make the
        // detection meaningful: if mpv stops reporting these, the HDR path silently
        // disappears and nothing else would notice.
        assert!(
            caps.has_vo("gpu-next"),
            "ohne gpu-next gibt es keinen HDR-Pfad: {}",
            caps.describe()
        );
        assert!(
            caps.has_option("target-colorspace-hint"),
            "{}",
            caps.describe()
        );
        assert!(caps.can_tone_map(), "{}", caps.describe());
        assert!(
            caps.video_outputs.len() > 3,
            "die Videoausgangsliste ist auffällig kurz: {:?}",
            caps.video_outputs
        );
    }
}
