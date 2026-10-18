//! The game stream's toolbar state: what the buttons do, and what the stats show.
//!
//! Plan task 3.5. The web client's toolbar has five controls — fullscreen,
//! match-resolution, lock-mouse, stats, disconnect — and the native client must
//! offer the same. The *decisions* are collected here as plain state so they can
//! be tested without a window, a compositor or a running stream: a pointer lock
//! that is released when the stream stops, a resize that is not asked for twice,
//! a stats overlay that shows a rate rather than a total.
//!
//! # Why the stats live here
//!
//! The browser reads `pc.getStats()`; a native pipeline has no such call and
//! takes its numbers from GStreamer instead. The *shape* of what is displayed is
//! the same, and it is not cosmetic: the interesting number during a game is the
//! current rate, not the total since the start, and a rate computed from a
//! stale counter reports a healthy stream while the picture has already frozen.

use std::time::{Duration, Instant};

use serde::{Deserialize, Serialize};

use crate::protocol::{clamp_resize, MIN_DIMENSION};

/// Which surface the pointer lock applies to.
///
/// Only two states, deliberately: the browser has a third (lock pending, before
/// the user grants it), and treating that as "locked" is how a client ends up
/// sending relative movement while the cursor is still visible and moving.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PointerLock {
    Released,
    Locked,
}

impl PointerLock {
    /// Whether mouse movement should be sent as relative deltas.
    pub fn sends_relative(self) -> bool {
        matches!(self, Self::Locked)
    }

    /// The browser's naming, so the UI can share one template with the web
    /// client.
    pub fn label(self) -> &'static str {
        match self {
            Self::Released => "Lock Mouse",
            Self::Locked => "Unlock Mouse",
        }
    }
}

/// A toolbar action, named as the web client names it.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ToolbarAction {
    ToggleFullscreen,
    MatchResolution,
    TogglePointerLock,
    ToggleStats,
    Disconnect,
}

impl ToolbarAction {
    pub const ALL: [Self; 5] = [
        Self::ToggleFullscreen,
        Self::MatchResolution,
        Self::TogglePointerLock,
        Self::ToggleStats,
        Self::Disconnect,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::ToggleFullscreen => "Fullscreen",
            Self::MatchResolution => "Match Resolution",
            Self::TogglePointerLock => "Lock Mouse",
            Self::ToggleStats => "Stats",
            Self::Disconnect => "Disconnect",
        }
    }
}

/// What the caller should do about an action.
///
/// Returned instead of performed, so the decision ("a disconnect ends the
/// stream") is testable while the effect (closing a window) stays in the shell.
#[derive(Debug, Clone, Copy, PartialEq)]
pub enum ActionEffect {
    /// Nothing further; the state change alone was the point.
    StateOnly,
    /// Rebuild the stream at this size. The server tears down its whole WebRTC
    /// pipeline for this, so it must not be sent casually.
    Resize { width: u32, height: u32 },
    /// Tear the session down: notify the server and release the window.
    Disconnect,
}

/// The toolbar's state, and the rules for changing it.
#[derive(Debug, Clone)]
pub struct Toolbar {
    fullscreen: bool,
    pointer_lock: PointerLock,
    stats_visible: bool,
    /// Size requested from the server, to suppress a repeat request.
    last_resize: Option<(u32, u32)>,
    /// Last surface size seen, for `MatchResolution`.
    surface: Option<(u32, u32)>,
}

impl Default for Toolbar {
    fn default() -> Self {
        Self::new()
    }
}

impl Toolbar {
    pub fn new() -> Self {
        Self {
            fullscreen: false,
            pointer_lock: PointerLock::Released,
            stats_visible: false,
            last_resize: None,
            surface: None,
        }
    }

    pub fn fullscreen(&self) -> bool {
        self.fullscreen
    }

    pub fn pointer_lock(&self) -> PointerLock {
        self.pointer_lock
    }

    pub fn stats_visible(&self) -> bool {
        self.stats_visible
    }

    pub fn last_resize(&self) -> Option<(u32, u32)> {
        self.last_resize
    }

    /// Records the surface's current physical size.
    ///
    /// Kept even while not streaming, so "Match Resolution" works on the first
    /// press rather than needing one to learn the size.
    pub fn set_surface_size(&mut self, width: u32, height: u32) {
        if width >= MIN_DIMENSION && height >= MIN_DIMENSION {
            self.surface = Some((width, height));
        }
    }

    /// Applies an action.
    ///
    /// `stream_size` is the size the stream currently has, used to decide
    /// whether a resize is a real change.
    pub fn apply(
        &mut self,
        action: ToolbarAction,
        stream_size: Option<(u32, u32)>,
    ) -> ActionEffect {
        match action {
            ToolbarAction::ToggleFullscreen => {
                self.fullscreen = !self.fullscreen;
                ActionEffect::StateOnly
            }
            ToolbarAction::TogglePointerLock => {
                self.pointer_lock = match self.pointer_lock {
                    PointerLock::Released => PointerLock::Locked,
                    PointerLock::Locked => PointerLock::Released,
                };
                ActionEffect::StateOnly
            }
            ToolbarAction::ToggleStats => {
                self.stats_visible = !self.stats_visible;
                ActionEffect::StateOnly
            }
            ToolbarAction::MatchResolution => {
                let Some((width, height)) = self.surface else {
                    // The window has never been measured. Doing nothing is
                    // honest; guessing 1920×1080 would rebuild the server's
                    // pipeline to a size the user is not looking at.
                    return ActionEffect::StateOnly;
                };
                // The comparison is against the *stream*, not the last request:
                // the server clamps to even dimensions and to its own limits, so
                // a request can succeed while yielding a different size than
                // asked for. Comparing to the request would then suppress the
                // correction the user is asking for.
                match clamp_resize(width, height, stream_size.unwrap_or((0, 0))) {
                    Some((width, height)) => {
                        self.last_resize = Some((width, height));
                        ActionEffect::Resize { width, height }
                    }
                    None => ActionEffect::StateOnly,
                }
            }
            ToolbarAction::Disconnect => {
                // Releasing the lock here rather than leaving it to the caller:
                // a cursor that stays hidden after the stream ends leaves the
                // user unable to click anything.
                self.pointer_lock = PointerLock::Released;
                ActionEffect::Disconnect
            }
        }
    }

    /// The stream ended on its own — the server closed it, or it failed.
    ///
    /// Unlike a user disconnect this also drops the fullscreen flag: the window
    /// is about to disappear, and a window that returns fullscreen the next time
    /// it is shown surprises the user.
    pub fn stream_ended(&mut self) {
        self.pointer_lock = PointerLock::Released;
        self.stats_visible = false;
        self.fullscreen = false;
        self.last_resize = None;
    }

    /// Confirms the server accepted a size, so the toolbar stops asking for it.
    pub fn resize_confirmed(&mut self, width: u32, height: u32) {
        self.last_resize = Some((width, height));
    }
}

// ---------------------------------------------------------------------------
// Live statistics
// ---------------------------------------------------------------------------

/// One reading of GStreamer's counters.
///
/// Absolute values, as the pipeline reports them: totals since the stream began.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct StatsSample {
    /// Total bytes received.
    pub bytes: u64,
    /// Total frames the decoder produced.
    pub frames: u64,
    /// Total packets the jitter buffer discarded.
    pub packets_lost: u64,
    /// Cumulative time spent decoding.
    pub decode_time: Duration,
}

/// What the stats overlay displays, in the units the web client uses.
///
/// `Serialize` and `Deserialize` because it crosses the IPC boundary: the shell
/// reads it from the game thread and the UI renders it. The core crate stays free
/// of Tauri — this is plain serde, which the crate already uses for the wire
/// contract.
#[derive(Debug, Clone, Copy, PartialEq, Default, Serialize, Deserialize)]
pub struct LiveStats {
    pub mbps: f64,
    pub fps: f64,
    pub frames: u64,
    pub rtt_ms: Option<f64>,
    pub jitter_ms: Option<f64>,
    pub packets_lost: u64,
    pub resolution: Option<(u32, u32)>,
    /// Mean decode time per frame, in milliseconds.
    pub decode_ms: f64,
    /// How long the stream has been running.
    pub elapsed: Duration,
}

/// Turns absolute counters into the rates the overlay shows.
///
/// Kept as a small state machine because the rates need two samples and a time
/// difference: `bytes` alone says nothing about whether the stream is currently
/// healthy, and a rate computed against a stale total keeps reporting the last
/// good value after the picture has already stopped.
#[derive(Debug, Clone)]
pub struct StatsTracker {
    last: Option<(StatsSample, Instant)>,
    /// Smoothed bitrate, in Mbit/s.
    mbps: f64,
    /// Smoothed frames per second.
    fps: f64,
    /// The most recent sample, for the cumulative fields.
    latest: Option<StatsSample>,
    resolution: Option<(u32, u32)>,
    rtt_ms: Option<f64>,
    jitter_ms: Option<f64>,
    started: Instant,
}

/// How heavily a new reading is weighted into the displayed rate.
///
/// A raw per-interval rate jumps by a factor of two on a single lost packet,
/// which makes the overlay unreadable exactly when it is most needed. A quarter
/// keeps it responsive (four readings ≈ one second at 4 Hz) without flickering.
const SMOOTHING: f64 = 0.25;

impl StatsTracker {
    pub fn new() -> Self {
        Self {
            last: None,
            mbps: 0.0,
            fps: 0.0,
            latest: None,
            resolution: None,
            rtt_ms: None,
            jitter_ms: None,
            started: Instant::now(),
        }
    }

    /// Feeds a reading. Two readings are needed before a rate is reported.
    pub fn push(&mut self, sample: StatsSample, now: Instant) {
        if let Some((previous, at)) = self.last {
            let dt = now.saturating_duration_since(at).as_secs_f64();
            // A zero or absurd interval (two readings in the same millisecond,
            // or a clock that jumped) would produce an infinite or wildly wrong
            // rate. Ignoring it keeps the last good value instead.
            if dt > 0.001 && dt < 60.0 {
                let delta_bytes = sample.bytes.saturating_sub(previous.bytes);
                let delta_frames = sample.frames.saturating_sub(previous.frames);
                let instant_mbps = (delta_bytes as f64 * 8.0) / dt / 1_000_000.0;
                let instant_fps = delta_frames as f64 / dt;
                self.mbps = self.mbps * (1.0 - SMOOTHING) + instant_mbps * SMOOTHING;
                self.fps = self.fps * (1.0 - SMOOTHING) + instant_fps * SMOOTHING;
            }
        }
        self.last = Some((sample, now));
        self.latest = Some(sample);
    }

    /// The stream's own size, as reported by the pipeline's caps.
    pub fn set_resolution(&mut self, width: u32, height: u32) {
        self.resolution = Some((width, height));
    }

    /// Round-trip time from the ICE candidate pair, when known.
    ///
    /// `None` is a real state: ICE statistics are only available once a pair has
    /// succeeded, and showing `0 ms` before that would claim a perfect link.
    pub fn set_rtt(&mut self, rtt_ms: Option<f64>) {
        self.rtt_ms = rtt_ms.filter(|v| v.is_finite() && *v >= 0.0);
    }

    pub fn set_jitter(&mut self, jitter_ms: Option<f64>) {
        self.jitter_ms = jitter_ms.filter(|v| v.is_finite() && *v >= 0.0);
    }

    /// The current display values.
    pub fn snapshot(&self, now: Instant) -> LiveStats {
        let (frames, packets_lost, decode_ms) = match self.latest {
            Some(sample) => (
                sample.frames,
                sample.packets_lost,
                if sample.frames > 0 {
                    sample.decode_time.as_secs_f64() * 1000.0 / sample.frames as f64
                } else {
                    0.0
                },
            ),
            None => (0, 0, 0.0),
        };
        LiveStats {
            mbps: self.mbps,
            fps: self.fps,
            frames,
            rtt_ms: self.rtt_ms,
            jitter_ms: self.jitter_ms,
            packets_lost,
            resolution: self.resolution,
            decode_ms,
            elapsed: now.saturating_duration_since(self.started),
        }
    }
}

impl Default for StatsTracker {
    fn default() -> Self {
        Self::new()
    }
}

/// The overlay's text, so the wording is tested rather than invented per call
/// site — and so it can be translated in one place.
impl LiveStats {
    /// One line per reading, in the order the web client shows them.
    pub fn lines(&self) -> Vec<String> {
        let resolution = match self.resolution {
            Some((w, h)) => format!("{w}x{h}"),
            None => "—".to_string(),
        };
        // An unknown RTT prints as a dash rather than as zero: "0 ms" is a claim
        // about the link, and before ICE has settled there is nothing to claim.
        let rtt = match self.rtt_ms {
            Some(ms) => format!("{ms:.0} ms"),
            None => "—".to_string(),
        };
        let jitter = match self.jitter_ms {
            Some(ms) => format!("{ms:.0} ms"),
            None => "—".to_string(),
        };
        vec![
            format!("{:.1} Mbit/s", self.mbps),
            format!("{:.0} fps", self.fps),
            resolution,
            format!("{rtt} RTT"),
            format!("{jitter} Jitter"),
            format!("{} verloren", self.packets_lost),
            format!("{:.1} ms Decode", self.decode_ms),
            format!("{:.0} s", self.elapsed.as_secs_f64()),
        ]
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn toolbar_with_surface() -> Toolbar {
        let mut toolbar = Toolbar::new();
        toolbar.set_surface_size(2560, 1440);
        toolbar
    }

    #[test]
    fn the_toolbar_offers_the_five_web_controls() {
        let labels: Vec<&str> = ToolbarAction::ALL.iter().map(|a| a.label()).collect();
        assert_eq!(
            labels,
            vec![
                "Fullscreen",
                "Match Resolution",
                "Lock Mouse",
                "Stats",
                "Disconnect"
            ]
        );
    }

    #[test]
    fn toggles_flip_and_change_nothing_else() {
        let mut toolbar = Toolbar::new();
        assert!(!toolbar.fullscreen());
        assert_eq!(
            toolbar.apply(ToolbarAction::ToggleFullscreen, None),
            ActionEffect::StateOnly
        );
        assert!(toolbar.fullscreen());

        assert!(!toolbar.stats_visible());
        toolbar.apply(ToolbarAction::ToggleStats, None);
        assert!(toolbar.stats_visible());
        toolbar.apply(ToolbarAction::ToggleStats, None);
        assert!(!toolbar.stats_visible());

        // Fullscreen survived the stats toggles.
        assert!(toolbar.fullscreen());
    }

    #[test]
    fn the_pointer_lock_cycles_and_decides_the_mouse_mode() {
        let mut toolbar = Toolbar::new();
        assert_eq!(toolbar.pointer_lock(), PointerLock::Released);
        assert!(!toolbar.pointer_lock().sends_relative());
        assert_eq!(toolbar.pointer_lock().label(), "Lock Mouse");

        toolbar.apply(ToolbarAction::TogglePointerLock, None);
        assert_eq!(toolbar.pointer_lock(), PointerLock::Locked);
        assert!(toolbar.pointer_lock().sends_relative());
        assert_eq!(toolbar.pointer_lock().label(), "Unlock Mouse");

        toolbar.apply(ToolbarAction::TogglePointerLock, None);
        assert_eq!(toolbar.pointer_lock(), PointerLock::Released);
    }

    #[test]
    fn match_resolution_asks_for_the_surface_size() {
        let mut toolbar = toolbar_with_surface();
        let effect = toolbar.apply(ToolbarAction::MatchResolution, Some((1280, 720)));
        assert_eq!(
            effect,
            ActionEffect::Resize {
                width: 2560,
                height: 1440
            }
        );
        assert_eq!(toolbar.last_resize(), Some((2560, 1440)));
    }

    #[test]
    fn match_resolution_does_nothing_without_a_measured_surface() {
        // No measurement yet: better to do nothing than to rebuild the
        // server's pipeline for a guessed size.
        let mut toolbar = Toolbar::new();
        assert_eq!(
            toolbar.apply(ToolbarAction::MatchResolution, Some((1280, 720))),
            ActionEffect::StateOnly
        );
        assert_eq!(toolbar.last_resize(), None);
    }

    #[test]
    fn match_resolution_is_silent_when_the_stream_already_matches() {
        let mut toolbar = toolbar_with_surface();
        // Within the dead zone: the server would reject it anyway.
        assert_eq!(
            toolbar.apply(ToolbarAction::MatchResolution, Some((2558, 1442))),
            ActionEffect::StateOnly
        );
    }

    #[test]
    fn match_resolution_corrects_a_stream_that_differs_from_the_request() {
        // The server clamps to even numbers and its own limits, so what was
        // asked for and what is running can differ. The user pressing the
        // button again must produce a request, not silence.
        let mut toolbar = Toolbar::new();
        toolbar.set_surface_size(2559, 1441);
        toolbar.resize_confirmed(2560, 1442);
        let effect = toolbar.apply(ToolbarAction::MatchResolution, Some((1920, 1080)));
        assert!(
            matches!(effect, ActionEffect::Resize { .. }),
            "die Abweichung wurde verschluckt: {effect:?}"
        );
    }

    #[test]
    fn disconnect_releases_the_pointer_lock() {
        let mut toolbar = Toolbar::new();
        toolbar.apply(ToolbarAction::TogglePointerLock, None);
        assert!(toolbar.pointer_lock().sends_relative());

        assert_eq!(
            toolbar.apply(ToolbarAction::Disconnect, None),
            ActionEffect::Disconnect
        );
        // Otherwise the cursor stays hidden with nothing left to click.
        assert_eq!(toolbar.pointer_lock(), PointerLock::Released);
    }

    #[test]
    fn a_finished_stream_resets_the_toolbar() {
        let mut toolbar = toolbar_with_surface();
        toolbar.apply(ToolbarAction::ToggleFullscreen, None);
        toolbar.apply(ToolbarAction::TogglePointerLock, None);
        toolbar.apply(ToolbarAction::ToggleStats, None);
        toolbar.apply(ToolbarAction::MatchResolution, Some((1280, 720)));

        toolbar.stream_ended();
        assert!(!toolbar.fullscreen(), "Vollbild darf nicht überleben");
        assert_eq!(toolbar.pointer_lock(), PointerLock::Released);
        assert!(!toolbar.stats_visible());
        assert_eq!(
            toolbar.last_resize(),
            None,
            "die alte Größe darf die nächste Sitzung nicht blockieren"
        );
    }

    #[test]
    fn a_tiny_surface_is_not_recorded() {
        let mut toolbar = Toolbar::new();
        toolbar.set_surface_size(10, 10);
        assert_eq!(
            toolbar.apply(ToolbarAction::MatchResolution, None),
            ActionEffect::StateOnly
        );
    }

    // ── Stats ──

    fn sample(bytes: u64, frames: u64) -> StatsSample {
        StatsSample {
            bytes,
            frames,
            packets_lost: 0,
            decode_time: Duration::ZERO,
        }
    }

    #[test]
    fn the_first_reading_reports_no_rate_yet() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(sample(1_000_000, 60), t0);
        let stats = tracker.snapshot(t0);
        // One sample gives a total, not a rate. Reporting 0 Mbit/s would look
        // like a dead stream; reporting the total as a rate would be a lie.
        assert_eq!(stats.mbps, 0.0);
        assert_eq!(stats.fps, 0.0);
        assert_eq!(stats.frames, 60);
    }

    #[test]
    fn two_readings_produce_a_rate() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        // 1 MB in 0.1 s = 80 Mbit/s.
        tracker.push(sample(0, 0), t0);
        tracker.push(sample(1_000_000, 6), t0 + Duration::from_millis(100));
        let stats = tracker.snapshot(t0 + Duration::from_millis(100));
        // Smoothed from zero, so a quarter of the instant value.
        assert!((stats.mbps - 20.0).abs() < 0.01, "mbps war {}", stats.mbps);
        assert!((stats.fps - 15.0).abs() < 0.01, "fps war {}", stats.fps);
        assert_eq!(stats.frames, 6);
    }

    #[test]
    fn a_stalled_stream_reports_a_falling_rate() {
        // The point of a rate rather than a total: when the picture stops, the
        // overlay has to show it. With totals it would look healthy forever.
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(sample(0, 0), t0);
        tracker.push(sample(1_000_000, 60), t0 + Duration::from_millis(100));
        let busy = tracker.snapshot(t0).mbps;

        tracker.push(sample(1_000_000, 60), t0 + Duration::from_millis(200));
        tracker.push(sample(1_000_000, 60), t0 + Duration::from_millis(300));
        let stalled = tracker.snapshot(t0).mbps;
        assert!(stalled < busy, "gestoppt: {stalled} war nicht unter {busy}");
        assert!(stalled >= 0.0);
    }

    #[test]
    fn a_zero_interval_does_not_produce_an_infinite_rate() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(sample(0, 0), t0);
        // Same instant, large delta: dividing by the interval would give
        // infinity.
        tracker.push(sample(1_000_000_000, 60), t0);
        let stats = tracker.snapshot(t0);
        assert!(stats.mbps.is_finite(), "mbps war {}", stats.mbps);
        assert!(stats.fps.is_finite());
        assert_eq!(stats.mbps, 0.0, "die letzte gute Rate muss bleiben");
    }

    #[test]
    fn a_counter_reset_does_not_produce_a_negative_rate() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(sample(5_000_000, 300), t0);
        // A new pipeline (a reconnect, a resize) restarts the counters.
        tracker.push(sample(0, 0), t0 + Duration::from_millis(100));
        let stats = tracker.snapshot(t0);
        assert!(stats.mbps >= 0.0, "mbps war {}", stats.mbps);
        assert!(stats.fps >= 0.0);
    }

    #[test]
    fn decode_time_is_reported_per_frame() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(
            StatsSample {
                bytes: 0,
                frames: 100,
                packets_lost: 3,
                decode_time: Duration::from_millis(500),
            },
            t0,
        );
        let stats = tracker.snapshot(t0);
        // 500 ms for 100 frames = 5 ms each.
        assert!(
            (stats.decode_ms - 5.0).abs() < 0.001,
            "war {}",
            stats.decode_ms
        );
        assert_eq!(stats.packets_lost, 3);
    }

    #[test]
    fn decode_time_is_not_divided_by_zero() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(
            StatsSample {
                bytes: 0,
                frames: 0,
                packets_lost: 0,
                decode_time: Duration::from_millis(500),
            },
            t0,
        );
        assert_eq!(tracker.snapshot(t0).decode_ms, 0.0);
    }

    #[test]
    fn an_unknown_rtt_is_not_printed_as_zero() {
        let tracker = StatsTracker::new();
        let lines = tracker.snapshot(Instant::now()).lines();
        // "0 ms RTT" would claim a perfect link before ICE has settled.
        assert!(
            lines.iter().any(|l| l == "— RTT"),
            "unbekannte Laufzeit muss als Strich erscheinen: {lines:?}"
        );
    }

    #[test]
    fn an_unknown_jitter_is_not_printed_as_zero() {
        // Found by mutating the jitter branch to print "0 ms": no test failed.
        // The jitter has its own unknown state, and printing zero there claims a
        // perfectly steady stream before anything has been measured.
        let tracker = StatsTracker::new();
        let lines = tracker.snapshot(Instant::now()).lines();
        assert!(
            lines.iter().any(|l| l == "— Jitter"),
            "unbekannter Jitter muss als Strich erscheinen: {lines:?}"
        );
    }

    #[test]
    fn a_known_jitter_is_printed_in_milliseconds() {
        let mut tracker = StatsTracker::new();
        tracker.set_jitter(Some(4.6));
        let lines = tracker.snapshot(Instant::now()).lines();
        assert!(lines.iter().any(|l| l == "5 ms Jitter"), "{lines:?}");
    }

    #[test]
    fn a_nonsensical_jitter_is_rejected() {
        let mut tracker = StatsTracker::new();
        tracker.set_jitter(Some(f64::NAN));
        assert_eq!(tracker.snapshot(Instant::now()).jitter_ms, None);
        tracker.set_jitter(Some(-1.0));
        assert_eq!(tracker.snapshot(Instant::now()).jitter_ms, None);
    }

    #[test]
    fn a_known_rtt_is_printed_in_milliseconds() {
        let mut tracker = StatsTracker::new();
        tracker.set_rtt(Some(23.4));
        let lines = tracker.snapshot(Instant::now()).lines();
        assert!(lines.iter().any(|l| l == "23 ms RTT"), "{lines:?}");
    }

    #[test]
    fn a_nonsensical_rtt_is_rejected() {
        let mut tracker = StatsTracker::new();
        tracker.set_rtt(Some(f64::NAN));
        assert_eq!(tracker.snapshot(Instant::now()).rtt_ms, None);
        tracker.set_rtt(Some(-5.0));
        assert_eq!(tracker.snapshot(Instant::now()).rtt_ms, None);
        // Infinite is not a measurement either.
        tracker.set_rtt(Some(f64::INFINITY));
        assert_eq!(tracker.snapshot(Instant::now()).rtt_ms, None);
    }

    #[test]
    fn an_unknown_resolution_is_not_printed_as_a_size() {
        let tracker = StatsTracker::new();
        let lines = tracker.snapshot(Instant::now()).lines();
        assert!(lines.iter().any(|l| l == "—"), "{lines:?}");
    }

    #[test]
    fn the_overlay_shows_every_field_the_web_client_shows() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.set_resolution(2560, 1440);
        tracker.set_rtt(Some(12.0));
        tracker.set_jitter(Some(3.0));
        tracker.push(sample(0, 0), t0);
        tracker.push(sample(1_000_000, 60), t0 + Duration::from_millis(100));

        let lines = tracker.snapshot(t0 + Duration::from_millis(100)).lines();
        assert_eq!(lines.len(), 8, "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("Mbit/s")), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("fps")), "{lines:?}");
        assert!(lines.iter().any(|l| l == "2560x1440"), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("RTT")), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("Jitter")), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("verloren")), "{lines:?}");
        assert!(lines.iter().any(|l| l.contains("Decode")), "{lines:?}");
    }

    #[test]
    fn elapsed_time_grows_with_the_clock() {
        let mut tracker = StatsTracker::new();
        let t0 = Instant::now();
        tracker.push(sample(0, 0), t0);
        let early = tracker.snapshot(t0).elapsed;
        let later = tracker.snapshot(t0 + Duration::from_secs(30)).elapsed;
        assert!(later > early);
        assert!(later >= Duration::from_secs(30));
    }
}
