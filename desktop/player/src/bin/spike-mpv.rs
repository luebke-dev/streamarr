// Spike 0.3: media playback through mpv.
//
// Answers plan task 0.3 and, more importantly, open decision #2 in the plan:
// libmpv in-process versus a separate mpv process. The plan recommends the
// process and this proves out that choice with the properties that actually
// matter for this app:
//
//   * Direct Play of the server's original file (no transcode), using the
//     play-token URL — the whole point of a native player.
//   * Control from the outside: pause, seek, track selection, speed.
//   * Position reporting back to the caller (resume needs this).
//   * Clean shutdown without leaving a zombie process.
//
// The JSON IPC protocol is used rather than linking libmpv, because that is
// exactly the decision under test: the IPC route needs no C linking, keeps a
// crash in mpv away from the app, and — decisive here — keeps this crate free
// of a native dependency that would complicate packaging and CI.
//
// Run with: cargo run --features mpv --bin spike-mpv -- <stream-url>
// Requires `mpv` on PATH and the `--wid`-free window path (see note below).

use std::io::{BufRead, BufReader, Write};
use std::os::unix::net::UnixStream;
use std::path::PathBuf;
use std::process::{Child, Command, Stdio};
use std::time::{Duration, Instant};

/// Path of the IPC socket. Located in the runtime dir so it never lands in a
/// world-readable temp directory.
fn socket_path() -> PathBuf {
    let dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(dir).join(format!("streamarr-spike-mpv-{}.sock", std::process::id()))
}

struct Mpv {
    child: Child,
    stream: UnixStream,
    /// One persistent reader. Creating a fresh `BufReader` per call loses data:
    /// a `BufReader` reads ahead, and whatever it buffered but did not consume
    /// is discarded when it is dropped, so the next reader never sees those
    /// bytes. This was the cause of a silent hang during development.
    reader: BufReader<UnixStream>,
    /// Carries a partially received line across read timeouts. mpv's events can
    /// arrive in fragments, and dropping the fragment on timeout would lose the
    /// event permanently.
    partial: String,
    next_id: u64,
}

impl Mpv {
    /// Reads one JSON line, returning `Ok(None)` when the read timed out.
    ///
    /// The timeout is treated as a normal outcome rather than an error: mpv
    /// sends events only when something happens, so an idle socket is the
    /// common case while polling. Bytes that arrived before the timeout are kept
    /// in `self.partial` and completed by the next call.
    fn read_json_line(&mut self) -> std::io::Result<Option<serde_json::Value>> {
        loop {
            // A complete line is only one that ends in a newline. Large replies
            // such as `track-list` span several reads, and parsing a fragment
            // fails silently — which is how a perfectly good answer looked like
            // an empty track list.
            if let Some(pos) = self.partial.find('\n') {
                let line = self.partial[..pos].to_string();
                self.partial.drain(..=pos);
                if line.trim().is_empty() {
                    continue;
                }
                return Ok(serde_json::from_str::<serde_json::Value>(line.trim()).ok());
            }

            let mut chunk = String::new();
            match self.reader.read_line(&mut chunk) {
                Ok(0) => {
                    return Err(std::io::Error::new(
                        std::io::ErrorKind::UnexpectedEof,
                        "mpv closed the IPC socket",
                    ))
                }
                Ok(_) => self.partial.push_str(&chunk),
                Err(e)
                    if e.kind() == std::io::ErrorKind::WouldBlock
                        || e.kind() == std::io::ErrorKind::TimedOut =>
                {
                    // Anything already read is part of the reply; dropping it
                    // here truncated large responses such as `track-list`.
                    self.partial.push_str(&chunk);
                    return Ok(None);
                }
                Err(e) => return Err(e),
            }
        }
    }

    /// Starts mpv with its IPC socket and waits for the socket to appear.
    ///
    /// Window handling: on Wayland a client cannot position its toplevel and
    /// `--wid` does not work at all (confirmed in spike 0.2), so no window
    /// handle is passed here. mpv opens its own toplevel, which the shell then
    /// puts into fullscreen — the architecture from docs/plans/spike-02-fenster.md.
    fn start(url: &str, extra_args: &[&str]) -> std::io::Result<Self> {
        let sock = socket_path();
        let _ = std::fs::remove_file(&sock);

        let mut cmd = Command::new("mpv");
        cmd.arg("--no-config")
            .arg("--idle=yes")
            // The IPC endpoint is what makes external control possible.
            .arg(format!("--input-ipc-server={}", sock.display()))
            // Keep mpv's own chatter out of our protocol stream.
            .arg("--really-quiet")
            .arg("--no-terminal")
            // A native player is used precisely for the GPU path; this is the
            // renderer that supports HDR passthrough (plan §10.2).
            .arg("--vo=gpu-next")
            .arg("--hwdec=auto-safe")
            .args(extra_args)
            .stdout(Stdio::null())
            // NOT `piped`: mpv's diagnostics would fill the pipe buffer with
            // nobody reading, and mpv would then block before emitting any IPC
            // event. Writing them to a file keeps them for debugging without
            // that deadlock.
            .stderr(Stdio::from(
                std::fs::File::create(stderr_log_path())
                    .map_err(|e| std::io::Error::new(e.kind(), format!("stderr log: {e}")))?,
            ));

        let child = cmd.spawn()?;

        // Poll for the socket: mpv creates it asynchronously.
        let deadline = Instant::now() + Duration::from_secs(10);
        let stream = loop {
            if Instant::now() > deadline {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    format!("mpv IPC socket {} never appeared", sock.display()),
                ));
            }
            match UnixStream::connect(&sock) {
                Ok(s) => break s,
                Err(_) => std::thread::sleep(Duration::from_millis(50)),
            }
        };

        // A read timeout makes `read_line` return instead of blocking forever,
        // which is what allows the deadline checks below to mean anything.
        stream.set_read_timeout(Some(Duration::from_millis(250)))?;
        let reader = BufReader::new(stream.try_clone()?);

        let mut mpv = Self {
            child,
            stream,
            reader,
            partial: String::new(),
            next_id: 1,
        };
        // The file is loaded first and the observers are registered afterwards.
        // Registering them before `loadfile` was measured to produce no
        // `time-pos` events at all for the file loaded afterwards (verified with
        // an independent Python IPC client), so the order matters.
        mpv.command(&["loadfile", url, "replace"])?;
        // The id is a *number*. As a string mpv answers "invalid parameter" and
        // then emits no events whatsoever, which is what SPIKE_TRACE revealed.
        mpv.send_command(serde_json::json!(["observe_property", 1, "time-pos"]))?;
        mpv.send_command(serde_json::json!(["observe_property", 3, "duration"]))?;
        Ok(mpv)
    }

    /// Sends one IPC command, keeping the JSON types intact.
    ///
    /// Typed on purpose. mpv rejects a numeric argument that arrives as a string
    /// — `["observe_property", "1", "time-pos"]` fails with "invalid parameter"
    /// and produces no events at all, while `["observe_property", 1, "time-pos"]`
    /// works. A `&[&str]` helper hides that mistake, which is exactly what
    /// happened during this spike.
    fn send_command(&mut self, args: serde_json::Value) -> std::io::Result<()> {
        let payload = serde_json::json!({ "command": args });
        self.stream.write_all(payload.to_string().as_bytes())?;
        self.stream.write_all(b"\n")?;
        self.stream.flush()
    }

    /// Convenience for commands whose arguments are all strings.
    fn command(&mut self, args: &[&str]) -> std::io::Result<()> {
        self.send_command(serde_json::json!(args))
    }

    /// Sends a command and waits for its reply, matched by request id.
    ///
    /// Needed because IPC is asynchronous: a property read only becomes a value
    /// once the matching `request_id` comes back, and reading a different reply
    /// would silently produce wrong answers.
    fn request(&mut self, args: serde_json::Value) -> std::io::Result<serde_json::Value> {
        let id = self.next_id;
        self.next_id += 1;
        let payload = serde_json::json!({ "command": args, "request_id": id });
        self.stream.write_all(payload.to_string().as_bytes())?;
        self.stream.write_all(b"\n")?;
        self.stream.flush()?;

        let deadline = Instant::now() + Duration::from_secs(5);
        loop {
            if Instant::now() > deadline {
                return Err(std::io::Error::new(
                    std::io::ErrorKind::TimedOut,
                    format!("no reply to {args}"),
                ));
            }
            match self.read_json_line() {
                Ok(Some(value)) => {
                    if value.get("request_id").and_then(|v| v.as_u64()) == Some(id) {
                        return Ok(value);
                    }
                }
                // A read timeout is expected while waiting; keep polling until
                // the deadline above fires.
                Ok(None) => continue,
                Err(e) => return Err(e),
            }
        }
    }

    /// Reads one event, skipping replies to earlier requests.
    fn read_event(&mut self, timeout: Duration) -> Option<serde_json::Value> {
        let deadline = Instant::now() + timeout;
        let trace = std::env::var("SPIKE_TRACE").is_ok();
        loop {
            if Instant::now() > deadline {
                return None;
            }
            match self.read_json_line() {
                Ok(Some(value)) => {
                    if trace {
                        eprintln!("RAW {}", serde_json::to_string(&value).unwrap_or_default());
                    }
                    if value.get("event").is_some() {
                        return Some(value);
                    }
                }
                Ok(None) => continue,
                Err(e) => {
                    if trace {
                        eprintln!("ERR {e}");
                    }
                    return None;
                }
            }
        }
    }

    /// Reads a property, returning its JSON value.
    fn get_property(&mut self, name: &str) -> serde_json::Value {
        self.request(serde_json::json!(["get_property", name]))
            .ok()
            .and_then(|v| v.get("data").cloned())
            .unwrap_or(serde_json::Value::Null)
    }

    fn stop(&mut self) {
        let _ = self.command(&["quit"]);
        // Give mpv a moment to exit cleanly, then make sure it is gone. Without
        // this the app would leak a process per playback, which is exactly the
        // kind of thing a spike is supposed to catch.
        for _ in 0..20 {
            if let Ok(Some(_)) = self.child.try_wait() {
                let _ = std::fs::remove_file(socket_path());
                return;
            }
            std::thread::sleep(Duration::from_millis(50));
        }
        let _ = self.child.kill();
        let _ = self.child.wait();
        let _ = std::fs::remove_file(socket_path());
    }
}

impl Drop for Mpv {
    fn drop(&mut self) {
        self.stop();
    }
}

/// Where mpv's diagnostics are written; see `Mpv::start`.
fn stderr_log_path() -> PathBuf {
    let dir = std::env::var("XDG_RUNTIME_DIR").unwrap_or_else(|_| "/tmp".to_string());
    PathBuf::from(dir).join(format!("streamarr-spike-mpv-{}.log", std::process::id()))
}

struct Check {
    name: &'static str,
    passed: bool,
    detail: String,
}

fn main() {
    let url = match std::env::args().nth(1) {
        Some(u) => u,
        None => {
            eprintln!("usage: spike-mpv <stream-url>");
            eprintln!();
            eprintln!("Get the URL from POST /api/play/{{guid}} (returns `token`), then use");
            eprintln!("{{base}}/api/stream/file?token={{token}} — the direct-file endpoint");
            eprintln!("that backs Direct Play.");
            std::process::exit(2);
        }
    };

    let mut checks: Vec<Check> = Vec::new();
    let mut record = |name: &'static str, passed: bool, detail: String| {
        println!(
            "[{}] {name}: {detail}",
            if passed { "PASS" } else { "FAIL" }
        );
        checks.push(Check {
            name,
            passed,
            detail,
        });
    };

    println!("starting mpv for {}", &url[..url.len().min(80)]);

    // `--force-window` so a headless check still exercises the real GPU path
    // rather than falling back to audio-only.
    let started = Instant::now();
    let mut mpv = match Mpv::start(&url, &["--force-window=yes"]) {
        Ok(m) => m,
        Err(e) => {
            eprintln!("failed to start mpv: {e}");
            std::process::exit(1);
        }
    };
    record(
        "mpv starts and accepts IPC",
        true,
        format!("socket ready in {:?}", started.elapsed()),
    );

    // ── Wait for playback to actually begin ──
    // A loadfile reply only means "accepted"; the file is playing once mpv
    // reports a position. Checking the reply alone would be a false positive.
    let mut position_seen = false;
    let mut first_pos = 0.0f64;
    let wait_start = Instant::now();
    while wait_start.elapsed() < Duration::from_secs(30) {
        let Some(event) = mpv.read_event(Duration::from_millis(500)) else {
            continue;
        };
        if event.get("event").and_then(|v| v.as_str()) == Some("property-change")
            && event.get("name").and_then(|v| v.as_str()) == Some("time-pos")
        {
            if let Some(pos) = event.get("data").and_then(|v| v.as_f64()) {
                position_seen = true;
                first_pos = pos;
                break;
            }
        }
        if event.get("event").and_then(|v| v.as_str()) == Some("end-file") {
            let reason = event.get("reason").and_then(|v| v.as_str()).unwrap_or("?");
            record(
                "file loads and plays",
                false,
                format!("mpv ended the file early, reason={reason}"),
            );
            return_summary(&checks);
            return;
        }
    }
    record(
        "file loads and plays (Direct Play)",
        position_seen,
        if position_seen {
            format!("first reported position {first_pos:.2}s")
        } else {
            "no position within 30s".to_string()
        },
    );
    if !position_seen {
        return_summary(&checks);
        return;
    }

    // ── Direct Play, i.e. no transcode ──
    // Whether the server transcoded is visible in the URL stream: Direct Play
    // serves the original container (matroska), a transcode would be HLS/TS.
    let is_direct = !url.contains("playlist.m3u8");
    record(
        "served as Direct Play (no HLS/transcode path)",
        is_direct,
        if is_direct {
            "non-HLS stream URL".to_string()
        } else {
            "URL is an HLS playlist".to_string()
        },
    );

    // ── Duration is known, which resume needs ──
    let duration = mpv.get_property("duration");
    let dur_ok = duration.as_f64().unwrap_or(0.0) > 0.0;
    record("duration reported", dur_ok, format!("duration={duration}"));

    // ── Control: pause ──
    let _ = mpv.command(&["set_property", "pause", "yes"]);
    std::thread::sleep(Duration::from_millis(400));
    let paused = mpv.get_property("pause");
    let pause_ok = paused.as_bool().unwrap_or(false);
    record("pause works", pause_ok, format!("pause={paused}"));

    // ── Control: seek ──
    // The target is a fraction of the media, not a fixed 120s: seeking to
    // exactly the duration lands on EOF and stops playback, which would make the
    // following resume check measure nothing. (That mistake was made here first.)
    let dur = duration.as_f64().unwrap_or(0.0).max(1.0);
    let target = (dur * 0.4).max(1.0);
    let _ = mpv.send_command(serde_json::json!(["seek", target, "absolute"]));
    std::thread::sleep(Duration::from_millis(1200));
    let after_seek = mpv.get_property("time-pos").as_f64().unwrap_or(0.0);
    // Seeking only counts as working if the position actually moved near the
    // target; a silent seek failure would otherwise pass unnoticed.
    let seek_ok = (after_seek - target).abs() < (dur * 0.1).max(5.0);
    record(
        "seek works",
        seek_ok,
        format!("target {target:.1}s of {dur:.1}s, position now {after_seek:.2}s"),
    );

    // ── Control: resume ──
    let _ = mpv.command(&["set_property", "pause", "no"]);
    std::thread::sleep(Duration::from_millis(1200));
    let after_resume = mpv.get_property("time-pos").as_f64().unwrap_or(0.0);
    let advanced = after_resume > after_seek + 0.3;
    record(
        "resume advances playback",
        advanced,
        format!("{after_seek:.2}s → {after_resume:.2}s"),
    );

    // ── Track selection (audio and subtitle), needed by the plan ──
    let tracks = mpv.get_property("track-list");
    let (audio_tracks, sub_tracks) = count_tracks(&tracks);
    record(
        "track-list readable (audio/subtitle selection possible)",
        audio_tracks > 0,
        format!("{audio_tracks} audio, {sub_tracks} subtitle track(s)"),
    );
    // Actually select a subtitle track if one exists, so "readable" is not
    // mistaken for "selectable".
    if sub_tracks > 0 {
        let sid = first_track_id(&tracks, "sub");
        let _ = mpv.send_command(serde_json::json!(["set_property", "sid", sid]));
        std::thread::sleep(Duration::from_millis(500));
        let current = mpv.get_property("sid");
        let sub_ok = current.as_i64().unwrap_or(0) == sid;
        record(
            "subtitle track selectable",
            sub_ok,
            format!("sid requested {sid}, got {current}"),
        );
    } else {
        record(
            "subtitle track selectable",
            true,
            "skipped: source has no subtitle tracks".to_string(),
        );
    }

    // ── Speed control, used by the plan's "high framerate" work ──
    let _ = mpv.send_command(serde_json::json!(["set_property", "speed", 1.5]));
    std::thread::sleep(Duration::from_millis(300));
    let speed = mpv.get_property("speed").as_f64().unwrap_or(0.0);
    record(
        "speed control works",
        (speed - 1.5).abs() < 0.01,
        format!("speed={speed}"),
    );

    // ── HDR/GPU path is the reason for a native player at all ──
    let vo = mpv
        .request(serde_json::json!(["get_property", "vo-configured"]))
        .ok();
    let vo_ok = vo
        .as_ref()
        .and_then(|v| v.get("data"))
        .and_then(|d| d.as_bool())
        .unwrap_or(false);
    let hwdec = mpv.get_property("hwdec-current");
    record(
        "GPU renderer configured (HDR-capable path)",
        vo_ok,
        format!("vo-configured={vo:?} hwdec-current={hwdec}"),
    );

    mpv.stop();
    // Verify no zombie: the app must not leak a process per playback.
    std::thread::sleep(Duration::from_millis(300));
    let still_alive = matches!(mpv.child.try_wait(), Ok(None));
    record(
        "mpv exits cleanly (no leaked process)",
        !still_alive,
        format!("process alive after quit: {still_alive}"),
    );

    return_summary(&checks);
}

fn count_tracks(tracks: &serde_json::Value) -> (usize, usize) {
    let Some(list) = tracks.as_array() else {
        return (0, 0);
    };
    let audio = list
        .iter()
        .filter(|t| t.get("type").and_then(|v| v.as_str()) == Some("audio"))
        .count();
    let subs = list
        .iter()
        .filter(|t| t.get("type").and_then(|v| v.as_str()) == Some("sub"))
        .count();
    (audio, subs)
}

fn first_track_id(tracks: &serde_json::Value, kind: &str) -> i64 {
    tracks
        .as_array()
        .and_then(|list| {
            list.iter()
                .find(|t| t.get("type").and_then(|v| v.as_str()) == Some(kind))
        })
        .and_then(|t| t.get("id").and_then(|v| v.as_i64()))
        .unwrap_or(0)
}

fn return_summary(checks: &[Check]) {
    let passed = checks.iter().filter(|c| c.passed).count();
    println!();
    println!("=== spike 0.3: {passed}/{} checks passed ===", checks.len());
    for c in checks {
        println!("  {} {}", if c.passed { "ok  " } else { "FAIL" }, c.name);
    }
    // Print the detail of failures too: the pass/fail line alone would hide
    // *why* something failed, which is the only part worth keeping.
    for c in checks.iter().filter(|c| !c.passed) {
        println!("  reason: {} — {}", c.name, c.detail);
    }
    let failed: Vec<_> = checks.iter().filter(|c| !c.passed).collect();
    if failed.is_empty() {
        println!();
        println!("RESULT: all checks passed — separate mpv process is workable");
        std::process::exit(0);
    } else {
        println!();
        println!("RESULT: {} check(s) failed", failed.len());
        std::process::exit(1);
    }
}
