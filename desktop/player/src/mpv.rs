//! Media playback via a separate mpv process over its JSON IPC.
//!
//! Decision §9.2 of the plan, validated in spike 0.3: mpv runs as a **child process**
//! driven over its JSON IPC socket, not linked in as libmpv. The reasons are in the
//! plan; the practically important ones are crash isolation, no C link step in
//! packaging or CI, the full `gpu-next`/HDR path, and the user being able to reuse
//! their own `mpv.conf`. The cost is about 100 ms of process start.
//!
//! # Why this module looks paranoid
//!
//! Spike 0.3 found six defects in the first IPC client, all of them silent. They are
//! the reason for the shape of this code, and each one has a comment where it matters:
//!
//! 1. mpv's IPC is **strongly typed**. `["observe_property", "1", "time-pos"]` — the id
//!    as a *string* — is answered with `invalid parameter` and then produces no events
//!    at all, ever. So commands are built as [`serde_json::Value`], never as
//!    `&[&str]` with everything stringified.
//! 2. `stderr(Stdio::piped())` without reading it deadlocks mpv as soon as its
//!    diagnostics fill the pipe. Diagnostics go to a file.
//! 3. A fresh `BufReader` per call silently discards read-ahead, so one persistent
//!    reader is held.
//! 4. Large replies (`track-list`) arrive fragmented; bytes received before a read
//!    timeout must be kept, or the reply is truncated and looks like an empty answer.
//! 5. Observers registered **before** `loadfile` produce no events for that file. The
//!    order in [`Mpv::start`] is deliberate.
//! 6. A blocking socket makes deadline checks dead code, so a read timeout is set.
//!
//! # What is tested and what needs a real mpv
//!
//! Everything that is a *decision* is a pure function and unit-tested: the argument
//! list, track-list parsing, property-event parsing, the resume position rule, the
//! URL/token handling. The IPC and process layer needs a real `mpv` binary and is
//! covered by the `spike-mpv` measurement program and by an integration test that
//! skips when mpv is absent.

use std::io::{BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

/// Property observation ids. Numbers, not strings — see the module docs.
///
/// Fixed constants rather than a counter so a property can be recognised in an event
/// without keeping a map, and so the ids are stable across a restart.
pub mod observe {
    pub const TIME_POS: u64 = 1;
    pub const DURATION: u64 = 2;
    pub const PAUSE: u64 = 3;
    pub const TRACK_LIST: u64 = 4;
    pub const SPEED: u64 = 6;
    pub const CORE_IDLE: u64 = 7;
    pub const EOF_REACHED: u64 = 8;
}

/// How long to wait for mpv's IPC socket after starting it.
///
/// mpv creates the socket asynchronously, and on a loaded machine that can take a
/// moment. Measured well under a second in spike 0.3.
const SOCKET_TIMEOUT: Duration = Duration::from_secs(10);

/// How long a command reply may take.
const REPLY_TIMEOUT: Duration = Duration::from_secs(5);

/// Read timeout on the socket.
///
/// Not a failure condition: mpv sends events only when something happens, so an idle
/// socket is the normal state while polling. The timeout is what makes the deadlines
/// in this module real instead of decorative.
const READ_TIMEOUT: Duration = Duration::from_millis(250);

/// HDR handling for media playback (plan task 2.9).
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default, Serialize, Deserialize)]
pub enum HdrMode {
    /// Let mpv decide. The safe default.
    #[default]
    Auto,
    /// Pass HDR through untouched: `--target-colorspace-hint=yes`.
    ///
    /// Only correct when the display *and* the renderer both support HDR. Claiming it
    /// otherwise does not produce a fallback — the server's transcode path is
    /// HDR-blind (plan §10.2), so the picture comes out washed out rather than merely
    /// suboptimal. Hence a mode the shell must choose deliberately.
    Passthrough,
    /// Tone-map HDR down to SDR for a display that cannot show it.
    ///
    /// The provable alternative to passthrough, which is what the plan asks for:
    /// "HDR10-Durchleitung oder nachweisbares SDR-Mapping".
    ToneMapSdr,
}

impl HdrMode {
    /// mpv arguments for this mode.
    pub fn to_args(self) -> Vec<String> {
        match self {
            // Nothing forced: mpv's own defaults are better informed than a guess.
            Self::Auto => vec![],
            Self::Passthrough => vec![
                "--target-colorspace-hint=yes".to_string(),
                // Peak detection in the display's own terms; without it mpv still
                // tone-maps, which defeats passthrough.
                "--hdr-compute-peak=no".to_string(),
            ],
            Self::ToneMapSdr => vec![
                "--target-colorspace-hint=no".to_string(),
                // bt.2390 is the ITU reference curve and is what mpv recommends for
                // HDR10 -> SDR. Named explicitly rather than left on `auto` so a
                // future mpv release cannot change the picture without a test here.
                "--tone-mapping=bt.2390".to_string(),
                "--hdr-compute-peak=yes".to_string(),
            ],
        }
    }

    /// Whether this mode claims HDR output, i.e. whether reporting it as a client
    /// capability would be truthful.
    pub fn claims_hdr(self) -> bool {
        matches!(self, Self::Passthrough)
    }
}

/// Everything that shapes how mpv is invoked.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PlayerOptions {
    /// The profile directory containing `mpv.conf`.
    ///
    /// Passed as `--config-dir`, which *replaces* mpv's default location rather than
    /// adding to it. That is deliberate: the profile's `mpv.conf` is the app's mpv
    /// configuration (plan task 1.3), and silently also honouring `~/.config/mpv`
    /// would make the same profile behave differently on two machines.
    pub config_dir: PathBuf,
    /// Start fullscreen.
    ///
    /// On by default because spike 0.2 established that the video toplevel is the
    /// primary mode on Wayland: a client cannot position its own toplevel there, so
    /// the design is fullscreen video with the UI window hidden.
    pub fullscreen: bool,
    pub hdr: HdrMode,
    /// Hardware decoding mode. `auto-safe` never fails; it falls back to software.
    pub hwdec: String,
    /// Video output driver. `gpu-next` is the libplacebo path and the only one that
    /// does HDR properly.
    pub vo: String,
    /// Audio output driver.
    ///
    /// Defaults to `auto`, i.e. the user's real sound device, which is what a media
    /// player should do. It is a field rather than a constant because **automated
    /// tests must silence it**: the test media carries real audio tracks, and the
    /// first version of the integration tests played 440 Hz and 880 Hz test tones
    /// through the developer's speakers during every run. `--vo=null` silences the
    /// picture and nothing else, which is the trap.
    pub ao: String,
    /// Extra user arguments, appended last so they win.
    pub extra_args: Vec<String>,
}

impl Default for PlayerOptions {
    fn default() -> Self {
        Self {
            config_dir: PathBuf::new(),
            fullscreen: true,
            hdr: HdrMode::Auto,
            hwdec: "auto-safe".to_string(),
            vo: "gpu-next".to_string(),
            ao: "auto".to_string(),
            extra_args: Vec::new(),
        }
    }
}

impl PlayerOptions {
    /// The full argument list, without the URL.
    ///
    /// Pure so it can be tested without mpv. `--idle=yes` is what lets one process
    /// serve successive files instead of restarting per playback.
    pub fn to_args(&self) -> Vec<String> {
        let mut args = vec![
            "--idle=yes".to_string(),
            // Keep mpv's chatter off the protocol stream — but do *not* silence it
            // entirely: `--really-quiet` would also hide the errors that explain a
            // failure to play.
            "--no-terminal".to_string(),
            format!("--vo={}", self.vo),
            format!("--hwdec={}", self.hwdec),
            format!("--ao={}", self.ao),
        ];

        if !self.config_dir.as_os_str().is_empty() {
            args.push(format!("--config-dir={}", self.config_dir.display()));
        }
        if self.fullscreen {
            args.push("--fullscreen=yes".to_string());
        }
        args.extend(self.hdr.to_args());
        // Last, so a user argument can override anything above.
        args.extend(self.extra_args.iter().cloned());
        args
    }
}

/// What kind of track this is.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum TrackKind {
    Video,
    Audio,
    Subtitle,
}

impl TrackKind {
    pub fn from_mpv(value: &str) -> Option<Self> {
        match value {
            "video" => Some(Self::Video),
            "audio" => Some(Self::Audio),
            "sub" => Some(Self::Subtitle),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Self::Video => "video",
            Self::Audio => "audio",
            Self::Subtitle => "sub",
        }
    }
}

/// One track from mpv's `track-list`.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Track {
    /// mpv's numeric track id, used to select it.
    pub id: i64,
    pub kind: TrackKind,
    /// Language code as stored in the file, if any.
    pub language: Option<String>,
    /// Human-readable title, if any.
    pub title: Option<String>,
    pub codec: Option<String>,
    /// Whether mpv currently has this track selected.
    pub selected: bool,
    /// Whether the track is external (a separate subtitle file).
    pub external: bool,
    /// `true` for mpv's synthetic "no subtitles" entry.
    pub is_default: bool,
}

impl Track {
    /// A label for the UI, preferring real information over placeholders.
    ///
    /// Order matters: a title is what the release group intended, a language is
    /// usually present but terse, and the codec is the last resort. Showing
    /// "Track 2" when the file says "German (AC3 5.1)" would be a needless loss.
    pub fn label(&self) -> String {
        if let Some(title) = self.title.as_deref().filter(|t| !t.trim().is_empty()) {
            return title.to_string();
        }
        if let Some(language) = self.language.as_deref().filter(|l| !l.trim().is_empty()) {
            return match &self.codec {
                Some(codec) => format!("{language} ({codec})"),
                None => language.to_string(),
            };
        }
        match &self.codec {
            Some(codec) => codec.clone(),
            None => format!("Spur {}", self.id),
        }
    }

    /// Whether the language matches a preference, e.g. `de` against `ger` or `deu`.
    pub fn matches_language(&self, wanted: &str) -> bool {
        match self.language.as_deref() {
            Some(actual) => languages_match(actual, wanted),
            None => false,
        }
    }
}

/// The tracks mpv currently knows about.
#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
pub struct TrackList {
    pub tracks: Vec<Track>,
}

impl TrackList {
    /// Parses mpv's `track-list` property.
    ///
    /// Unknown track types are skipped rather than treated as an error: mpv has more
    /// types than this player cares about, and failing on one would make a perfectly
    /// playable file report as broken.
    pub fn parse(value: &serde_json::Value) -> Self {
        let tracks = value
            .as_array()
            .map(|items| {
                items
                    .iter()
                    .filter_map(|item| {
                        let kind = TrackKind::from_mpv(item.get("type")?.as_str()?)?;
                        Some(Track {
                            id: item.get("id").and_then(serde_json::Value::as_i64)?,
                            kind,
                            language: string_field(item, "lang"),
                            title: string_field(item, "title"),
                            codec: string_field(item, "codec"),
                            selected: item
                                .get("selected")
                                .and_then(serde_json::Value::as_bool)
                                .unwrap_or(false),
                            external: item
                                .get("external")
                                .and_then(serde_json::Value::as_bool)
                                .unwrap_or(false),
                            is_default: item
                                .get("default")
                                .and_then(serde_json::Value::as_bool)
                                .unwrap_or(false),
                        })
                    })
                    .collect()
            })
            .unwrap_or_default();
        Self { tracks }
    }

    pub fn of_kind(&self, kind: TrackKind) -> Vec<&Track> {
        self.tracks.iter().filter(|t| t.kind == kind).collect()
    }

    pub fn audio(&self) -> Vec<&Track> {
        self.of_kind(TrackKind::Audio)
    }

    pub fn subtitles(&self) -> Vec<&Track> {
        self.of_kind(TrackKind::Subtitle)
    }

    pub fn selected(&self, kind: TrackKind) -> Option<&Track> {
        self.of_kind(kind).into_iter().find(|t| t.selected)
    }

    /// The track to select for a preferred language, if one matches.
    ///
    /// `None` means "no preference expressed or nothing matched", and the caller
    /// leaves mpv's own choice alone. Returning a default here would override mpv's
    /// decision — which is usually right, since it follows the file's default flags —
    /// with a guess.
    pub fn best_match(&self, kind: TrackKind, wanted: Option<&str>) -> Option<&Track> {
        let wanted = wanted?.trim();
        if wanted.is_empty() {
            return None;
        }
        self.of_kind(kind)
            .into_iter()
            // A track with the right language and a title beats a bare one.
            .filter(|t| t.matches_language(wanted))
            .max_by_key(|t| (t.title.is_some() as u8, !t.external as u8))
    }
}

/// ISO 639-1 code to its ISO 639-2 forms (bibliographic and terminological).
///
/// A table, not a prefix comparison. The prefix idea is appealing — `eng`/`en`,
/// `ita`/`it` and `por`/`pt` do share their first two letters — but it was **wrong**,
/// which a test caught: German is `ger`/`deu` for `de`, French `fre`/`fra` for `fr`,
/// Spanish `spa` for `es`. Worse, it silently merged languages that must stay apart:
/// `sl` (Slovenian) and `slk` (Slovak) share a prefix and are not the same language.
///
/// Files carry whichever form their authoring tool produced, so both directions are
/// resolved: a two-letter preference matches a three-letter track and vice versa.
/// Codes absent from the table are compared exactly, which fails closed — showing the
/// wrong audio track is worse than showing none.
const LANGUAGE_ALIASES: &[(&str, &[&str])] = &[
    ("af", &["afr"]),
    ("am", &["amh"]),
    ("ar", &["ara"]),
    ("az", &["aze"]),
    ("be", &["bel"]),
    ("bg", &["bul"]),
    ("bn", &["ben"]),
    ("bo", &["tib", "bod"]),
    ("bs", &["bos"]),
    ("ca", &["cat"]),
    ("cs", &["cze", "ces"]),
    ("cy", &["wel", "cym"]),
    ("da", &["dan"]),
    ("de", &["ger", "deu"]),
    ("el", &["gre", "ell"]),
    ("en", &["eng"]),
    ("es", &["spa"]),
    ("et", &["est"]),
    ("eu", &["baq", "eus"]),
    ("fa", &["per", "fas"]),
    ("fi", &["fin"]),
    ("fo", &["fao"]),
    ("fr", &["fre", "fra"]),
    ("ga", &["gle"]),
    ("gd", &["gla"]),
    ("gl", &["glg"]),
    ("he", &["heb"]),
    ("hi", &["hin"]),
    ("hr", &["hrv"]),
    ("hu", &["hun"]),
    ("hy", &["arm", "hye"]),
    ("id", &["ind"]),
    ("is", &["ice", "isl"]),
    ("it", &["ita"]),
    ("ja", &["jpn"]),
    ("ka", &["geo", "kat"]),
    ("kk", &["kaz"]),
    ("km", &["khm"]),
    ("ko", &["kor"]),
    ("ky", &["kir"]),
    ("lb", &["ltz"]),
    ("lo", &["lao"]),
    ("lt", &["lit"]),
    ("lv", &["lav"]),
    ("mi", &["mao", "mri"]),
    ("mk", &["mac", "mkd"]),
    ("ml", &["mal"]),
    ("mn", &["mon"]),
    ("ms", &["may", "msa"]),
    ("mt", &["mlt"]),
    ("my", &["bur", "mya"]),
    ("ne", &["nep"]),
    ("nl", &["dut", "nld"]),
    ("no", &["nor"]),
    ("pl", &["pol"]),
    ("pt", &["por"]),
    ("ro", &["rum", "ron"]),
    ("ru", &["rus"]),
    ("si", &["sin"]),
    ("sk", &["slo", "slk"]),
    ("sl", &["slv"]),
    ("so", &["som"]),
    ("sq", &["alb", "sqi"]),
    ("sr", &["srp"]),
    ("sv", &["swe"]),
    ("sw", &["swa"]),
    ("ta", &["tam"]),
    ("te", &["tel"]),
    ("th", &["tha"]),
    ("tl", &["tgl"]),
    ("tr", &["tur"]),
    ("uk", &["ukr"]),
    ("ur", &["urd"]),
    ("uz", &["uzb"]),
    ("vi", &["vie"]),
    ("zh", &["chi", "zho"]),
    ("zu", &["zul"]),
];

/// Reduces a language tag to its base code.
///
/// Strips a regional or script suffix, so `de-DE`, `de_DE` and `de` are one language.
/// A file tagged `pt-BR` should satisfy a `pt` preference.
fn normalise_language(code: &str) -> String {
    code.trim()
        .to_ascii_lowercase()
        .split(['-', '_'])
        .next()
        .unwrap_or_default()
        .to_string()
}

/// Whether two language tags denote the same language.
pub fn languages_match(a: &str, b: &str) -> bool {
    let a = normalise_language(a);
    let b = normalise_language(b);
    if a.is_empty() || b.is_empty() {
        return false;
    }
    if a == b {
        return true;
    }
    // Resolve both to the set of tags they denote and look for an overlap. Handles
    // both directions, so a `de` preference finds a `ger` track and a `ger` preference
    // finds a `de` track.
    for (short, longs) in LANGUAGE_ALIASES {
        let group = std::iter::once(*short).chain(longs.iter().copied());
        let contains_a = group.clone().any(|c| c == a);
        if !contains_a {
            continue;
        }
        if group.into_iter().any(|c| c == b) {
            return true;
        }
    }
    false
}

fn string_field(value: &serde_json::Value, key: &str) -> Option<String> {
    value
        .get(key)
        .and_then(serde_json::Value::as_str)
        .map(str::to_string)
        .filter(|s| !s.trim().is_empty())
}

/// A snapshot of the player, as the UI needs it.
#[derive(Debug, Clone, PartialEq, Serialize, Deserialize)]
pub struct PlayerState {
    pub position: f64,
    pub duration: f64,
    pub paused: bool,
    pub speed: f64,
    /// `true` once the file has been loaded and playback is possible.
    pub loaded: bool,
    /// Set when mpv reports end of file.
    pub ended: bool,
    /// Set when mpv went idle without an EOF, i.e. playback was stopped.
    pub idle: bool,
}

impl Default for PlayerState {
    fn default() -> Self {
        Self {
            position: 0.0,
            duration: 0.0,
            paused: false,
            speed: 1.0,
            loaded: false,
            ended: false,
            idle: true,
        }
    }
}

impl PlayerState {
    /// How far through the file we are, 0.0 to 1.0.
    pub fn progress(&self) -> f64 {
        if self.duration <= 0.0 {
            return 0.0;
        }
        (self.position / self.duration).clamp(0.0, 1.0)
    }

    /// Applies one mpv property event.
    ///
    /// Pure, so the whole state machine is tested without mpv. Returns whether
    /// anything changed, which the shell uses to decide if the UI needs an update —
    /// mpv emits events on every frame for `time-pos`, and repainting the UI on each
    /// would be wasteful.
    pub fn apply_event(&mut self, name: &str, data: &serde_json::Value) -> bool {
        match name {
            "time-pos" => {
                let Some(value) = data.as_f64() else {
                    return false;
                };
                if (self.position - value).abs() < f64::EPSILON {
                    return false;
                }
                self.position = value;
                true
            }
            "duration" => {
                let Some(value) = data.as_f64() else {
                    return false;
                };
                self.duration = value;
                // A duration can only be known once a file is loaded, so this is the
                // reliable signal that playback became possible.
                self.loaded = true;
                true
            }
            "pause" => {
                let Some(value) = data.as_bool() else {
                    return false;
                };
                if self.paused == value {
                    return false;
                }
                self.paused = value;
                true
            }
            "speed" => {
                let Some(value) = data.as_f64() else {
                    return false;
                };
                self.speed = value;
                true
            }
            "eof-reached" => {
                let Some(value) = data.as_bool() else {
                    return false;
                };
                self.ended = value;
                true
            }
            "core-idle" => {
                let Some(value) = data.as_bool() else {
                    return false;
                };
                self.idle = value;
                true
            }
            _ => false,
        }
    }

    /// Resets the parts that belong to a file, keeping the user's speed.
    ///
    /// Speed is a preference ("I watch everything at 1.25×"), not a property of the
    /// file, so carrying it across files is right. Position, duration and the end flag
    /// are not.
    pub fn reset_for_new_file(&mut self) {
        self.position = 0.0;
        self.duration = 0.0;
        self.paused = false;
        self.loaded = false;
        self.ended = false;
    }
}

/// What can go wrong.
#[derive(Debug)]
pub enum MpvError {
    /// mpv could not be started or its socket never appeared.
    Start(String),
    /// The IPC exchange failed.
    Ipc(String),
    /// mpv is not on `PATH`.
    NotInstalled,
    Io(std::io::Error),
}

impl std::fmt::Display for MpvError {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Start(detail) => write!(f, "mpv konnte nicht gestartet werden: {detail}"),
            Self::Ipc(detail) => write!(f, "Fehler in der mpv-Steuerung: {detail}"),
            Self::NotInstalled => write!(
                f,
                "mpv wurde nicht gefunden. Bitte mpv installieren und erneut versuchen."
            ),
            Self::Io(err) => write!(f, "Dateifehler: {err}"),
        }
    }
}

impl std::error::Error for MpvError {}

impl From<std::io::Error> for MpvError {
    fn from(err: std::io::Error) -> Self {
        Self::Io(err)
    }
}

// ─────────────────────────────────────────────────────────────────────────────
// Process and IPC layer. Needs a real `mpv` binary; covered by the spike-mpv
// measurement program and by the integration test that skips without mpv.
// ─────────────────────────────────────────────────────────────────────────────

/// Path of the IPC socket for a given tag.
///
/// On Unix a socket in `XDG_RUNTIME_DIR`, which is per-user and not world-readable.
/// On Windows mpv uses a named pipe, which lives in a namespace rather than on disk —
/// **this path is not verified in this project**, because no Windows system was
/// available; it follows mpv's documented `\\.\pipe\` form.
pub fn ipc_endpoint(tag: &str) -> String {
    if cfg!(windows) {
        format!(r"\\.\pipe\streamarr-mpv-{tag}")
    } else {
        let dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string());
        PathBuf::from(dir)
            .join(format!("streamarr-mpv-{tag}.sock"))
            .display()
            .to_string()
    }
}

/// A tag unique to one player instance.
///
/// Per *instance*, not per process. The first version used the process id alone, and
/// running the integration tests in parallel made the defect obvious: every instance
/// in a process computed the same socket path, so the second player connected to the
/// first one's mpv. In the app that would mean a second playback hijacking the first —
/// and because the tests are the only place two players coexist today, the bug would
/// have shipped. The counter is what makes the tag unique; the process id keeps it
/// unique across processes.
fn instance_tag() -> String {
    use std::sync::atomic::{AtomicU64, Ordering};
    static COUNTER: AtomicU64 = AtomicU64::new(0);
    format!(
        "{}-{}",
        std::process::id(),
        COUNTER.fetch_add(1, Ordering::SeqCst)
    )
}

/// A running mpv process with its IPC connection.
pub struct Mpv {
    child: Child,
    /// This instance's own IPC endpoint. Stored rather than recomputed: recomputing it
    /// would produce a *different* tag, so the socket would never be cleaned up.
    endpoint: String,
    stream: std::os::unix::net::UnixStream,
    /// One persistent reader. A fresh `BufReader` per call discards read-ahead, and
    /// whatever it buffered is then lost to the next reader — which was a silent hang
    /// in spike 0.3 (defect 3).
    reader: BufReader<std::os::unix::net::UnixStream>,
    /// Carries a partially received line across read timeouts; a large reply such as
    /// `track-list` arrives in fragments (defect 4).
    partial: String,
    next_id: u64,
}

impl Mpv {
    /// Starts mpv and loads `url`.
    ///
    /// The observers are registered *after* `loadfile` on purpose: registered before,
    /// they produced no events for the file loaded afterwards (defect 5).
    pub fn start(url: &str, options: &PlayerOptions) -> Result<Self, MpvError> {
        let endpoint = ipc_endpoint(&instance_tag());
        if !cfg!(windows) {
            let _ = std::fs::remove_file(&endpoint);
        }

        let log_path = log_file_path(&endpoint);

        let mut command = Command::new("mpv");
        command.arg(format!("--input-ipc-server={endpoint}"));
        // mpv's own log file, which is the *supported* way to keep its diagnostics.
        // Redirecting stderr was not enough and the mistake was silent: `--no-terminal`
        // suppresses exactly the messages one wants to keep, so the redirect produced
        // 0-byte files that looked like working diagnostics. Verified by reading the
        // log back — and it is what finally made the audio device mpv chose visible.
        command.arg(format!("--log-file={}", log_path.display()));
        command.arg("--msg-level=all=info");
        for arg in options.to_args() {
            command.arg(arg);
        }
        command
            .stdout(Stdio::null())
            // NOT `piped`: unread diagnostics fill the pipe and mpv blocks before it
            // emits any event (defect 2). With `--log-file` in place this stream only
            // needs somewhere harmless to go.
            .stderr(Stdio::from(std::fs::File::create(&log_path).map_err(
                |e| MpvError::Start(format!("mpv-Protokoll {}: {e}", log_path.display())),
            )?));

        let child = command.spawn().map_err(|e| match e.kind() {
            std::io::ErrorKind::NotFound => MpvError::NotInstalled,
            _ => MpvError::Start(e.to_string()),
        })?;

        let stream = connect_with_timeout(&endpoint)?;
        stream
            .set_read_timeout(Some(READ_TIMEOUT))
            .map_err(|e| MpvError::Start(e.to_string()))?;
        let reader = BufReader::new(
            stream
                .try_clone()
                .map_err(|e| MpvError::Start(e.to_string()))?,
        );

        let mut mpv = Self {
            child,
            endpoint,
            stream,
            reader,
            partial: String::new(),
            next_id: 1,
        };
        mpv.send(&serde_json::json!(["loadfile", url, "replace"]))?;
        for (id, property) in [
            (observe::TIME_POS, "time-pos"),
            (observe::DURATION, "duration"),
            (observe::PAUSE, "pause"),
            (observe::TRACK_LIST, "track-list"),
            (observe::SPEED, "speed"),
            (observe::CORE_IDLE, "core-idle"),
            (observe::EOF_REACHED, "eof-reached"),
        ] {
            // The id is a *number*. As a string mpv answers `invalid parameter` and
            // then emits no events at all (defect 1).
            mpv.send(&serde_json::json!(["observe_property", id, property]))?;
        }
        Ok(mpv)
    }

    /// This instance's IPC endpoint, for diagnostics and tests.
    pub fn ipc_endpoint(&self) -> &str {
        &self.endpoint
    }

    /// Readiness of the process, for a timeout while starting.
    pub fn has_exited(&mut self) -> bool {
        matches!(self.child.try_wait(), Ok(Some(_)))
    }

    /// Writes one command. Arguments keep their JSON types (defect 1).
    pub fn send(&mut self, command: &serde_json::Value) -> Result<(), MpvError> {
        let payload = serde_json::json!({ "command": command });
        self.stream
            .write_all(payload.to_string().as_bytes())
            .map_err(|e| MpvError::Ipc(e.to_string()))?;
        self.stream
            .write_all(b"\n")
            .map_err(|e| MpvError::Ipc(e.to_string()))?;
        self.stream
            .flush()
            .map_err(|e| MpvError::Ipc(e.to_string()))
    }

    /// Sends a command and waits for its own reply, matched by request id.
    ///
    /// Matching matters: IPC is asynchronous, so reading whatever arrives next would
    /// attribute one command's answer to another.
    pub fn request(&mut self, command: serde_json::Value) -> Result<serde_json::Value, MpvError> {
        let id = self.next_id;
        self.next_id += 1;
        let payload = serde_json::json!({ "command": command, "request_id": id });
        self.stream
            .write_all(payload.to_string().as_bytes())
            .map_err(|e| MpvError::Ipc(e.to_string()))?;
        self.stream
            .write_all(b"\n")
            .map_err(|e| MpvError::Ipc(e.to_string()))?;
        self.stream
            .flush()
            .map_err(|e| MpvError::Ipc(e.to_string()))?;

        let deadline = Instant::now() + REPLY_TIMEOUT;
        loop {
            if Instant::now() > deadline {
                return Err(MpvError::Ipc(format!("keine Antwort auf {command}")));
            }
            match self.read_value() {
                Ok(Some(value)) => {
                    if value.get("request_id").and_then(serde_json::Value::as_u64) == Some(id) {
                        return Ok(value);
                    }
                }
                Ok(None) => {}
                Err(e) => return Err(e),
            }
        }
    }

    /// Reads a property, returning `Null` when it is unavailable.
    pub fn property(&mut self, name: &str) -> serde_json::Value {
        self.request(serde_json::json!(["get_property", name]))
            .ok()
            .and_then(|reply| reply.get("data").cloned())
            .unwrap_or(serde_json::Value::Null)
    }

    /// Reads the track list.
    pub fn track_list(&mut self) -> TrackList {
        TrackList::parse(&self.property("track-list"))
    }

    /// Waits for the next event, or `None` on timeout.
    ///
    /// Replies to earlier requests are skipped, so the caller only ever sees events.
    pub fn next_event(&mut self, timeout: Duration) -> Option<serde_json::Value> {
        let deadline = Instant::now() + timeout;
        loop {
            if Instant::now() > deadline {
                return None;
            }
            match self.read_value() {
                Ok(Some(value)) => {
                    if value.get("event").is_some() {
                        return Some(value);
                    }
                }
                Ok(None) => {}
                Err(_) => return None,
            }
        }
    }

    /// Reads one JSON line; `Ok(None)` means the read timed out.
    ///
    /// A timeout is a normal outcome, not an error — mpv is silent while nothing
    /// happens. Bytes received before the timeout are kept, because they are part of a
    /// reply that has not finished arriving.
    fn read_value(&mut self) -> Result<Option<serde_json::Value>, MpvError> {
        loop {
            // Only a line ending in a newline is complete.
            if let Some(position) = self.partial.find('\n') {
                let line = self.partial[..position].to_string();
                self.partial.drain(..=position);
                if line.trim().is_empty() {
                    continue;
                }
                return Ok(serde_json::from_str(line.trim()).ok());
            }

            let mut chunk = String::new();
            match self.reader.read_line(&mut chunk) {
                Ok(0) => {
                    return Err(MpvError::Ipc(
                        "mpv hat die IPC-Verbindung geschlossen".to_string(),
                    ))
                }
                Ok(_) => self.partial.push_str(&chunk),
                Err(e)
                    if e.kind() == std::io::ErrorKind::WouldBlock
                        || e.kind() == std::io::ErrorKind::TimedOut =>
                {
                    // Keep what arrived; dropping it truncated large replies.
                    self.partial.push_str(&chunk);
                    return Ok(None);
                }
                Err(e) => return Err(MpvError::Ipc(e.to_string())),
            }
        }
    }

    /// Stops mpv and removes the socket.
    ///
    /// Falls back to `kill` after a grace period: without this a crashed or wedged mpv
    /// would leak a process per playback.
    pub fn stop(&mut self) {
        let _ = self.send(&serde_json::json!(["quit"]));
        for _ in 0..20 {
            if let Ok(Some(_)) = self.child.try_wait() {
                self.cleanup_socket();
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        self.cleanup_socket();
    }

    fn cleanup_socket(&self) {
        if !cfg!(windows) {
            let _ = std::fs::remove_file(&self.endpoint);
        }
    }
}

impl Drop for Mpv {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Path of the diagnostics file, next to the socket.
pub fn log_file_path(endpoint: &str) -> PathBuf {
    if cfg!(windows) {
        std::env::temp_dir().join("streamarr-mpv.log")
    } else {
        Path::new(endpoint).with_extension("log")
    }
}

/// Connects to the IPC endpoint, waiting for mpv to create it.
fn connect_with_timeout(endpoint: &str) -> Result<std::os::unix::net::UnixStream, MpvError> {
    let deadline = Instant::now() + SOCKET_TIMEOUT;
    loop {
        match std::os::unix::net::UnixStream::connect(endpoint) {
            Ok(stream) => return Ok(stream),
            Err(e) => {
                if Instant::now() > deadline {
                    return Err(MpvError::Start(format!(
                        "mpv hat den IPC-Endpunkt {endpoint} nicht bereitgestellt: {e}"
                    )));
                }
                std::thread::sleep(Duration::from_millis(50));
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // ── Option building ──

    #[test]
    fn idle_is_always_set() {
        // Without `--idle=yes` a single mpv process could not serve a second file.
        let args = PlayerOptions::default().to_args();
        assert!(args.contains(&"--idle=yes".to_string()), "{args:?}");
    }

    #[test]
    fn the_config_dir_replaces_mpvs_own() {
        let options = PlayerOptions {
            config_dir: PathBuf::from("/config/profiles/home"),
            ..Default::default()
        };
        let args = options.to_args();
        assert!(
            args.contains(&"--config-dir=/config/profiles/home".to_string()),
            "{args:?}"
        );
        // `--no-config` would defeat the point of a per-profile mpv.conf.
        assert!(!args.contains(&"--no-config".to_string()));
    }

    #[test]
    fn no_config_dir_argument_when_unset() {
        let args = PlayerOptions::default().to_args();
        assert!(!args.iter().any(|a| a.starts_with("--config-dir")));
    }

    /// The GPU path is the reason for a native player at all; a regression to a
    /// software-only output would be invisible until someone looked at the picture.
    #[test]
    fn the_gpu_renderer_and_hardware_decoding_are_the_default() {
        let args = PlayerOptions::default().to_args();
        assert!(args.contains(&"--vo=gpu-next".to_string()), "{args:?}");
        assert!(args.contains(&"--hwdec=auto-safe".to_string()), "{args:?}");
    }

    /// Audio output must default to the real device: this is a media player, and
    /// silently muting the user would be a far worse bug than a noisy test.
    #[test]
    fn audio_output_defaults_to_the_real_device() {
        assert_eq!(PlayerOptions::default().ao, "auto");
        assert!(PlayerOptions::default()
            .to_args()
            .contains(&"--ao=auto".to_string()));
    }

    /// The other half of the same rule: tests must be able to silence playback, and
    /// video alone does not do it. The first version of the integration tests used
    /// `--vo=null` and played test tones through the developer's speakers.
    /// mpv's own log file is the *supported* way to keep its diagnostics.
    /// Redirecting stderr was not enough and the failure was silent: `--no-terminal`
    /// suppresses precisely the messages one wants to keep, so the redirect produced
    /// 0-byte files that looked like working diagnostics. Reading them back is what
    /// made the audio device mpv chose visible at all.
    #[test]
    fn diagnostics_are_written_to_mpvs_own_log_file() {
        let endpoint = ipc_endpoint("diagnostics-check");
        let log = log_file_path(&endpoint);
        assert_eq!(
            log.extension().and_then(|e| e.to_str()),
            Some("log"),
            "{log:?}"
        );
        // Next to the socket, so both live in the per-user runtime directory.
        assert_eq!(log.parent(), Path::new(&endpoint).parent());
    }

    #[test]
    fn audio_output_can_be_silenced_for_tests() {
        let options = PlayerOptions {
            ao: "null".to_string(),
            ..Default::default()
        };
        let args = options.to_args();
        assert!(args.contains(&"--ao=null".to_string()), "{args:?}");
        // The picture is silenced separately; neither implies the other.
        assert!(args.contains(&"--vo=gpu-next".to_string()));
    }

    #[test]
    fn fullscreen_is_on_by_default() {
        // Spike 0.2: on Wayland the video toplevel is the primary mode.
        assert!(PlayerOptions::default().fullscreen);
        assert!(PlayerOptions::default()
            .to_args()
            .contains(&"--fullscreen=yes".to_string()));
    }

    #[test]
    fn fullscreen_can_be_turned_off() {
        let options = PlayerOptions {
            fullscreen: false,
            ..Default::default()
        };
        assert!(!options
            .to_args()
            .iter()
            .any(|a| a.starts_with("--fullscreen")));
    }

    // ── HDR ──

    #[test]
    fn auto_hdr_forces_nothing() {
        assert!(HdrMode::Auto.to_args().is_empty());
        assert!(!HdrMode::Auto.claims_hdr());
    }

    #[test]
    fn passthrough_sets_the_colorspace_hint_and_stops_peak_tone_mapping() {
        let args = HdrMode::Passthrough.to_args();
        assert!(args.contains(&"--target-colorspace-hint=yes".to_string()));
        // Leaving peak computation on would tone-map despite the hint.
        assert!(args.contains(&"--hdr-compute-peak=no".to_string()));
        assert!(HdrMode::Passthrough.claims_hdr());
    }

    /// The provable SDR mapping the plan asks for, with the tone-mapping curve named
    /// so a future mpv cannot change the picture silently.
    #[test]
    fn sdr_tone_mapping_uses_the_reference_curve() {
        let args = HdrMode::ToneMapSdr.to_args();
        assert!(args.contains(&"--target-colorspace-hint=no".to_string()));
        assert!(args.contains(&"--tone-mapping=bt.2390".to_string()));
        assert!(args.contains(&"--hdr-compute-peak=yes".to_string()));
        assert!(!HdrMode::ToneMapSdr.claims_hdr());
    }

    /// Claiming HDR is only honest in passthrough mode; the plan is explicit that a
    /// false claim yields a washed-out picture, not a fallback.
    #[test]
    fn only_passthrough_claims_hdr() {
        assert!(HdrMode::Passthrough.claims_hdr());
        for mode in [HdrMode::Auto, HdrMode::ToneMapSdr] {
            assert!(!mode.claims_hdr(), "{mode:?} darf HDR nicht behaupten");
        }
    }

    #[test]
    fn hdr_is_auto_by_default() {
        assert_eq!(PlayerOptions::default().hdr, HdrMode::Auto);
    }

    // ── Extra arguments ──

    #[test]
    fn user_arguments_come_last_so_they_win() {
        let options = PlayerOptions {
            extra_args: vec!["--vo=x11".to_string()],
            ..Default::default()
        };
        let args = options.to_args();
        let user = args.iter().position(|a| a == "--vo=x11").unwrap();
        let ours = args.iter().position(|a| a == "--vo=gpu-next").unwrap();
        assert!(user > ours, "Nutzer-Argumente müssen zuletzt kommen");
    }

    // ── Track parsing ──

    fn track_list_fixture() -> serde_json::Value {
        json!([
            {"id": 1, "type": "video", "codec": "h264", "selected": true,
             "demux-w": 1480, "demux-h": 1080},
            {"id": 2, "type": "audio", "codec": "ac3", "lang": "en",
             "title": "English 1.0", "selected": true, "default": true},
            {"id": 3, "type": "audio", "codec": "ac3", "lang": "de",
             "title": "Deutsch 1.0", "selected": false},
            {"id": 4, "type": "sub", "codec": "subrip", "lang": "de",
             "selected": false, "external": true},
            {"id": 5, "type": "sub", "codec": "subrip", "selected": true,
             "default": true}
        ])
    }

    #[test]
    fn a_track_list_is_parsed() {
        let list = TrackList::parse(&track_list_fixture());
        assert_eq!(list.tracks.len(), 5);
        assert_eq!(list.audio().len(), 2);
        assert_eq!(list.subtitles().len(), 2);
        assert_eq!(list.of_kind(TrackKind::Video).len(), 1);
    }

    #[test]
    fn the_selected_track_is_found() {
        let list = TrackList::parse(&track_list_fixture());
        assert_eq!(list.selected(TrackKind::Audio).unwrap().id, 2);
        // The selected subtitle is mpv's synthetic "no subtitles" entry, which is why
        // it has no language.
        assert_eq!(list.selected(TrackKind::Subtitle).unwrap().id, 5);
    }

    #[test]
    fn a_track_without_a_language_or_title_still_yields_a_label() {
        let list = TrackList::parse(&track_list_fixture());
        let track = list.tracks.iter().find(|t| t.id == 1).unwrap();
        // Falls back to the codec rather than showing an empty string.
        assert_eq!(track.label(), "h264");
    }

    #[test]
    fn a_title_wins_over_a_language_for_the_label() {
        let list = TrackList::parse(&track_list_fixture());
        let english = list.tracks.iter().find(|t| t.id == 2).unwrap();
        assert_eq!(english.label(), "English 1.0");
    }

    #[test]
    fn a_language_without_a_title_is_combined_with_the_codec() {
        let list = TrackList::parse(&track_list_fixture());
        let german = list.tracks.iter().find(|t| t.id == 4).unwrap();
        assert_eq!(german.label(), "de (subrip)");
    }

    #[test]
    fn a_track_with_nothing_identifying_falls_back_to_its_id() {
        let track = Track {
            id: 9,
            kind: TrackKind::Audio,
            language: None,
            title: None,
            codec: None,
            selected: false,
            external: false,
            is_default: false,
        };
        assert_eq!(track.label(), "Spur 9");
    }

    #[test]
    fn blank_fields_are_treated_as_absent() {
        let list = TrackList::parse(&json!([
            {"id": 1, "type": "audio", "title": "   ", "lang": "", "codec": "aac"}
        ]));
        assert_eq!(list.tracks[0].label(), "aac");
        assert_eq!(list.tracks[0].language, None);
    }

    /// mpv knows more track types than this player uses; an unknown one must not
    /// break the file.
    #[test]
    fn an_unknown_track_type_is_skipped_not_fatal() {
        let list = TrackList::parse(&json!([
            {"id": 1, "type": "audio", "codec": "aac"},
            {"id": 2, "type": "mystery"},
            {"id": 3, "type": "video", "codec": "h264"}
        ]));
        assert_eq!(list.tracks.len(), 2);
    }

    #[test]
    fn a_track_without_an_id_is_skipped() {
        let list = TrackList::parse(&json!([{"type": "audio", "codec": "aac"}]));
        assert!(list.tracks.is_empty());
    }

    #[test]
    fn malformed_input_yields_an_empty_list_rather_than_panicking() {
        for input in [json!(null), json!("nonsense"), json!(42), json!({})] {
            assert!(TrackList::parse(&input).tracks.is_empty(), "{input}");
        }
    }

    // ── Language matching ──

    #[test]
    fn an_exact_language_matches() {
        let list = TrackList::parse(&track_list_fixture());
        let track = list.tracks.iter().find(|t| t.id == 3).unwrap();
        assert!(track.matches_language("de"));
    }

    /// `ger` and `deu` are both German; files use either.
    #[test]
    fn three_letter_codes_match_their_two_letter_form() {
        let track = Track {
            id: 1,
            kind: TrackKind::Audio,
            language: Some("ger".to_string()),
            title: None,
            codec: None,
            selected: false,
            external: false,
            is_default: false,
        };
        assert!(track.matches_language("de"));
        assert!(track.matches_language("deu"));
        assert!(!track.matches_language("en"));
    }

    /// The prefix idea this table replaced would have merged Slovenian and Slovak.
    /// Both are real language tags and they are not the same language, so the mistake
    /// would have picked the wrong audio track on real files.
    #[test]
    fn languages_sharing_a_prefix_are_not_confused() {
        assert!(
            !languages_match("sl", "sk"),
            "Slowenisch ist nicht Slowakisch"
        );
        assert!(!languages_match("slv", "slo"), "slv vs. slo");
        assert!(!languages_match("sl", "slk"));
        // A few more pairs a prefix rule would have merged.
        assert!(!languages_match("de", "da"), "Deutsch ist nicht Dänisch");
        assert!(!languages_match("es", "et"), "Spanisch ist nicht Estnisch");
        assert!(
            !languages_match("fi", "fr"),
            "Finnisch ist nicht Französisch"
        );
        assert!(
            !languages_match("no", "nl"),
            "Norwegisch ist nicht Niederländisch"
        );
        assert!(!languages_match("ro", "ru"), "Rumänisch ist nicht Russisch");
    }

    /// The pairs that motivated a table at all: these must match in both directions,
    /// and their first two letters do *not* agree.
    #[test]
    fn bibliographic_and_terminological_forms_match() {
        for (short, long) in [
            ("de", "ger"),
            ("de", "deu"),
            ("fr", "fre"),
            ("fr", "fra"),
            ("es", "spa"),
            ("nl", "dut"),
            ("nl", "nld"),
            ("cs", "cze"),
            ("zh", "chi"),
            ("el", "gre"),
        ] {
            assert!(languages_match(short, long), "{short} vs {long}");
            assert!(languages_match(long, short), "{long} vs {short}");
        }
    }

    /// A regional suffix names a variant of the same language.
    #[test]
    fn regional_suffixes_are_ignored() {
        assert!(languages_match("pt-BR", "pt"));
        assert!(languages_match("pt", "pt-BR"));
        assert!(languages_match("de-DE", "ger"));
        assert!(languages_match("de_DE", "de"));
        assert!(languages_match("zh-Hans", "zh"));
        // …but a different base language is still different.
        assert!(!languages_match("pt-BR", "es"));
    }

    /// An unknown code falls back to an exact comparison. Failing closed is the right
    /// trade: picking the wrong audio track is worse than picking none.
    #[test]
    fn unknown_codes_are_compared_exactly() {
        assert!(languages_match("xx", "xx"));
        assert!(!languages_match("xx", "xy"));
        assert!(!languages_match("klingon", "tlh"));
    }

    #[test]
    fn empty_codes_never_match() {
        assert!(!languages_match("", "de"));
        assert!(!languages_match("de", ""));
        assert!(!languages_match("   ", "de"));
        assert!(!languages_match("", ""));
    }

    /// Every alias entry must be well formed, or the table quietly stops working for
    /// that language.
    #[test]
    fn the_alias_table_is_sane() {
        let mut seen = std::collections::HashSet::new();
        for (short, longs) in LANGUAGE_ALIASES {
            assert_eq!(short.len(), 2, "`{short}` ist kein ISO-639-1-Code");
            assert!(short.chars().all(|c| c.is_ascii_lowercase()), "{short}");
            assert!(!longs.is_empty(), "{short} hat keine Langform");
            for long in *longs {
                assert_eq!(long.len(), 3, "`{long}` ist kein ISO-639-2-Code");
                assert!(long.chars().all(|c| c.is_ascii_lowercase()), "{long}");
                // A code must not appear in two groups, or a preference could match
                // two languages at once.
                assert!(
                    seen.insert(*long),
                    "`{long}` kommt mehrfach in der Tabelle vor"
                );
            }
            assert!(seen.insert(*short), "`{short}` kommt mehrfach vor");
        }
    }

    /// German is the case a German-speaking user will hit first.
    #[test]
    fn a_german_preference_finds_a_ger_track() {
        let list = TrackList::parse(&json!([
            {"id": 1, "type": "audio", "lang": "eng", "title": "English"},
            {"id": 2, "type": "audio", "lang": "ger", "title": "Deutsch"}
        ]));
        assert_eq!(list.best_match(TrackKind::Audio, Some("de")).unwrap().id, 2);
    }

    #[test]
    fn language_matching_is_case_insensitive() {
        let list = TrackList::parse(&track_list_fixture());
        let track = list.tracks.iter().find(|t| t.id == 3).unwrap();
        assert!(track.matches_language("DE"));
        assert!(track.matches_language(" de "));
    }

    #[test]
    fn a_track_without_a_language_never_matches() {
        let track = Track {
            id: 1,
            kind: TrackKind::Audio,
            language: None,
            title: None,
            codec: None,
            selected: false,
            external: false,
            is_default: false,
        };
        assert!(!track.matches_language("de"));
    }

    // ── Preference selection ──

    #[test]
    fn a_preferred_language_selects_the_matching_track() {
        let list = TrackList::parse(&track_list_fixture());
        let chosen = list.best_match(TrackKind::Audio, Some("de")).unwrap();
        assert_eq!(chosen.id, 3);
    }

    /// No preference means mpv's own choice stands — it follows the file's default
    /// flags, which is better information than a guess.
    #[test]
    fn no_preference_selects_nothing() {
        let list = TrackList::parse(&track_list_fixture());
        assert!(list.best_match(TrackKind::Audio, None).is_none());
        assert!(list.best_match(TrackKind::Audio, Some("   ")).is_none());
    }

    #[test]
    fn an_unmatched_preference_selects_nothing() {
        let list = TrackList::parse(&track_list_fixture());
        assert!(list.best_match(TrackKind::Audio, Some("fr")).is_none());
    }

    /// A titled track is the better choice when two share a language.
    #[test]
    fn a_titled_track_wins_over_an_untitled_one() {
        let list = TrackList::parse(&json!([
            {"id": 1, "type": "audio", "lang": "de"},
            {"id": 2, "type": "audio", "lang": "de", "title": "Kommentar"}
        ]));
        assert_eq!(list.best_match(TrackKind::Audio, Some("de")).unwrap().id, 2);
    }

    // ── State machine ──

    #[test]
    fn a_fresh_state_is_idle_and_unloaded() {
        let state = PlayerState::default();
        assert!(state.idle);
        assert!(!state.loaded);
        assert_eq!(state.speed, 1.0);
    }

    #[test]
    fn time_position_updates_are_applied() {
        let mut state = PlayerState::default();
        assert!(state.apply_event("time-pos", &json!(12.5)));
        assert_eq!(state.position, 12.5);
    }

    /// `time-pos` arrives every frame; reporting "nothing changed" lets the shell skip
    /// a repaint.
    #[test]
    fn an_unchanged_position_reports_no_change() {
        let mut state = PlayerState::default();
        state.apply_event("time-pos", &json!(5.0));
        assert!(!state.apply_event("time-pos", &json!(5.0)));
    }

    /// A known duration is the reliable sign that a file loaded and can be played.
    #[test]
    fn a_duration_marks_the_player_as_loaded() {
        let mut state = PlayerState::default();
        assert!(!state.loaded);
        assert!(state.apply_event("duration", &json!(102.0)));
        assert!(state.loaded);
        assert_eq!(state.duration, 102.0);
    }

    #[test]
    fn pause_is_tracked_and_reported_once() {
        let mut state = PlayerState::default();
        assert!(state.apply_event("pause", &json!(true)));
        assert!(state.paused);
        assert!(!state.apply_event("pause", &json!(true)), "keine Änderung");
        assert!(state.apply_event("pause", &json!(false)));
        assert!(!state.paused);
    }

    #[test]
    fn end_of_file_is_tracked() {
        let mut state = PlayerState::default();
        assert!(state.apply_event("eof-reached", &json!(true)));
        assert!(state.ended);
    }

    #[test]
    fn idle_is_tracked() {
        let mut state = PlayerState::default();
        state.apply_event("core-idle", &json!(false));
        assert!(!state.idle);
    }

    /// mpv sends `null` for properties that do not exist yet, and a malformed event
    /// must not be mistaken for a value.
    #[test]
    fn a_null_or_wrong_typed_value_is_ignored() {
        let mut state = PlayerState::default();
        assert!(!state.apply_event("time-pos", &json!(null)));
        assert!(!state.apply_event("duration", &json!("nonsense")));
        assert!(!state.apply_event("pause", &json!(1)));
        assert!(!state.apply_event("eof-reached", &json!("yes")));
        assert_eq!(state, PlayerState::default());
    }

    #[test]
    fn an_unknown_property_is_ignored() {
        let mut state = PlayerState::default();
        assert!(!state.apply_event("volume", &json!(100)));
        assert_eq!(state, PlayerState::default());
    }

    #[test]
    fn progress_is_computed_and_clamped() {
        let mut state = PlayerState::default();
        assert_eq!(state.progress(), 0.0, "ohne Dauer kein Fortschritt");

        state.apply_event("duration", &json!(100.0));
        state.apply_event("time-pos", &json!(25.0));
        assert_eq!(state.progress(), 0.25);

        // mpv can briefly report a position past the duration at the very end.
        state.apply_event("time-pos", &json!(120.0));
        assert_eq!(state.progress(), 1.0);
    }

    /// Speed is a viewing preference, not a property of the file.
    #[test]
    fn resetting_for_a_new_file_keeps_the_speed() {
        let mut state = PlayerState::default();
        state.apply_event("time-pos", &json!(50.0));
        state.apply_event("duration", &json!(100.0));
        state.apply_event("pause", &json!(true));
        state.apply_event("eof-reached", &json!(true));
        state.apply_event("speed", &json!(1.25));

        state.reset_for_new_file();

        assert_eq!(state.position, 0.0);
        assert_eq!(state.duration, 0.0);
        assert!(!state.paused);
        assert!(!state.loaded);
        assert!(!state.ended);
        assert_eq!(state.speed, 1.25, "die Abspielgeschwindigkeit bleibt");
    }

    #[test]
    fn errors_are_explained_in_german_without_type_names() {
        for err in [
            MpvError::Start("x".to_string()),
            MpvError::Ipc("y".to_string()),
            MpvError::NotInstalled,
            MpvError::Io(std::io::Error::other("z")),
        ] {
            let message = err.to_string();
            assert!(!message.contains("MpvError"), "{message}");
            assert!(!message.is_empty());
        }
    }

    #[test]
    fn a_missing_mpv_says_what_to_do() {
        assert!(MpvError::NotInstalled.to_string().contains("installieren"));
    }

    // ── Observation ids ──

    /// The ids are part of the protocol with mpv and are compared as numbers.
    #[test]
    fn observation_ids_are_distinct() {
        let ids = [
            observe::TIME_POS,
            observe::DURATION,
            observe::PAUSE,
            observe::TRACK_LIST,
            observe::SPEED,
            observe::CORE_IDLE,
            observe::EOF_REACHED,
        ];
        let mut sorted = ids.to_vec();
        sorted.sort_unstable();
        sorted.dedup();
        assert_eq!(sorted.len(), ids.len(), "doppelte Beobachtungs-ID");
    }

    /// Every player instance needs its own socket. With the process id alone, two
    /// players in one process computed the same path and the second connected to the
    /// first one's mpv — found by running the integration tests in parallel, which is
    /// the only place two players coexist today.
    #[test]
    fn instance_tags_are_unique_within_a_process() {
        let tags: Vec<String> = (0..32).map(|_| instance_tag()).collect();
        let mut unique = tags.clone();
        unique.sort();
        unique.dedup();
        assert_eq!(unique.len(), tags.len(), "Endpunkt-Kollision: {tags:?}");
    }

    /// And unique across processes, which the process id supplies.
    #[test]
    fn an_instance_tag_contains_the_process_id() {
        assert!(instance_tag().starts_with(&std::process::id().to_string()));
    }

    #[test]
    fn endpoints_for_different_tags_differ() {
        assert_ne!(ipc_endpoint("a"), ipc_endpoint("b"));
        assert!(ipc_endpoint("a").contains("streamarr-mpv-a"));
    }

    #[test]
    fn track_kinds_round_trip_through_their_mpv_names() {
        for kind in [TrackKind::Video, TrackKind::Audio, TrackKind::Subtitle] {
            assert_eq!(TrackKind::from_mpv(kind.as_str()), Some(kind));
        }
        assert_eq!(TrackKind::from_mpv("mystery"), None);
    }
}
