//! "Report a problem": collecting what a diagnosis needs, and sending it.
//!
//! Plan task 4.5. The web UI has a logger, but a support report for the desktop
//! app needs three things the WebView cannot reach:
//!
//!   * **The player's logs.** mpv writes its own log file (that is the *supported*
//!     way to keep its diagnostics — redirecting stderr produced 0-byte files,
//!     defect 2 of spike 0.3), and the GStreamer pipeline logs into the shell.
//!     Both live on disk, outside the WebView.
//!   * **The versions that matter.** mpv's and GStreamer's, not just the app's.
//!     "It does not play" is unanswerable without them: the difference between
//!     mpv 0.41 and 0.35 is a different set of options, and a missing GStreamer
//!     plugin is invisible from the app's own version.
//!   * **The capability claims the app made.** The server picks a resolution and
//!     a codec from what the client claims; a wrong claim produces a stream that
//!     plays badly, and nothing in the logs would say what was claimed.
//!
//! # What is deliberately not collected
//!
//! No tokens, no server address, no filesystem paths, no machine identifiers.
//! The report is built from fixed fields plus the *tail* of the log files, and the
//! command takes no arguments — the UI cannot ask for a different file or an
//! extra path. A support report that can be pointed at arbitrary files is a file
//! exfiltration primitive.
//!
//! The server end (`POST /api/client-logs`) bounds the payload itself: 4096 bytes
//! of message, 8 KiB of context, 6 levels of nesting. The limits here are
//! stricter than the server's, because a truncated report that arrives is worth
//! more than a complete one that is rejected.

use std::path::{Path, PathBuf};

use serde::{Deserialize, Serialize};

use streamarr_desktop_player::mpv_caps::MpvCapabilities;

/// How much of each log file is included.
///
/// The *tail*, not the head: a failure is at the end, and mpv's startup banner
/// would fill the budget with version strings that the report already carries in
/// structured form.
const LOG_TAIL_BYTES: u64 = 6 * 1024;

/// How many log files are considered.
///
/// Every player instance gets its own file (a fixed name would race when two
/// players run, which the plan forbids by design), so a directory accumulates
/// them. The newest are the interesting ones.
const MAX_LOG_FILES: usize = 3;

/// The collected report, before it is flattened into a message.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Report {
    /// The app version, as the bundle carries it.
    pub app_version: String,
    /// The platform, e.g. `linux-wayland`.
    pub platform: String,
    /// mpv's own version, from `mpv --version`.
    ///
    /// `None` when mpv is absent, which is itself a finding: the report says
    /// "not installed" rather than omitting the field, because an omitted field
    /// is indistinguishable from a collection that failed.
    pub mpv_version: Option<String>,
    /// The video outputs mpv offers, which decides whether HDR can be passed
    /// through.
    pub mpv_video_outputs: Vec<String>,
    /// The GStreamer version, when the shell was built with the feature.
    pub gstreamer_version: Option<String>,
    /// What the app told the server it could decode.
    pub capabilities: Option<String>,
    /// The tail of the player logs, newest first.
    pub log_excerpts: Vec<LogExcerpt>,
}

/// One log file's tail.
#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct LogExcerpt {
    /// The file's name — **not** its path. A path would leak the user's home
    /// directory and the profile name into a report that gets uploaded.
    pub name: String,
    pub tail: String,
    /// Whether the tail was cut, so a reader knows the excerpt is partial.
    pub truncated: bool,
}

impl Report {
    /// Renders the report as the `message` the server expects.
    ///
    /// A single text block rather than structured `context`: the server stores
    /// the message as a log line, and a human reading it in a log file wants the
    /// versions on top. `context` is left for the caller to add the few
    /// machine-readable fields.
    pub fn to_message(&self) -> String {
        let mut out = String::new();
        out.push_str("Desktop client report\n");
        out.push_str(&format!("App: {}\n", self.app_version));
        out.push_str(&format!("Platform: {}\n", self.platform));
        match &self.mpv_version {
            Some(version) => out.push_str(&format!("mpv: {version}\n")),
            None => out.push_str("mpv: not installed\n"),
        }
        if !self.mpv_video_outputs.is_empty() {
            out.push_str(&format!("mpv vo: {}\n", self.mpv_video_outputs.join(", ")));
        }
        match &self.gstreamer_version {
            Some(version) => out.push_str(&format!("GStreamer: {version}\n")),
            None => out.push_str("GStreamer: not in this build\n"),
        }
        if let Some(capabilities) = &self.capabilities {
            out.push_str(&format!("Capabilities: {capabilities}\n"));
        }
        for excerpt in &self.log_excerpts {
            out.push_str(&format!(
                "\n--- {} ({}) ---\n{}",
                excerpt.name,
                if excerpt.truncated {
                    "gekürzt"
                } else {
                    "vollständig"
                },
                excerpt.tail
            ));
        }
        out
    }

    /// Whether the report says anything beyond the versions.
    ///
    /// A report with no logs is not useless — "which version, on which platform"
    /// answers a real class of question — but the UI should say so rather than
    /// implying logs are attached.
    pub fn has_logs(&self) -> bool {
        self.log_excerpts.iter().any(|e| !e.tail.is_empty())
    }

    /// The server's message limit is 4096 bytes; this keeps a report under it.
    ///
    /// Truncation happens here rather than at the server, because a rejected
    /// report is a report the user thinks was sent.
    pub const SERVER_MESSAGE_LIMIT: usize = 4096;

    /// Trims the report until it fits the server's limit.
    ///
    /// Logs are dropped before anything else: the versions and the capability
    /// claims are short and are the parts that make a report answerable.
    pub fn fit_to_server_limit(&mut self) {
        if self.to_message().len() <= Self::SERVER_MESSAGE_LIMIT {
            return;
        }
        // Drop the oldest excerpts first.
        while self.to_message().len() > Self::SERVER_MESSAGE_LIMIT && !self.log_excerpts.is_empty()
        {
            self.log_excerpts.pop();
        }
        // Still too long: trim the remaining excerpt.
        if self.to_message().len() > Self::SERVER_MESSAGE_LIMIT {
            for excerpt in &mut self.log_excerpts {
                excerpt.tail.truncate(Self::SERVER_MESSAGE_LIMIT / 2);
                excerpt.truncated = true;
            }
        }
        // The versions alone could still exceed the limit only if a version
        // string were absurd; cut the whole thing so the caller never sends a
        // payload the server will reject.
        if self.to_message().len() > Self::SERVER_MESSAGE_LIMIT {
            let message = self.to_message();
            let mut cut = String::from("Desktop client report (gekürzt)\n");
            // Cut on a char boundary, which `truncate` does not check.
            for ch in message.chars() {
                if cut.len() + ch.len_utf8() >= Self::SERVER_MESSAGE_LIMIT {
                    break;
                }
                cut.push(ch);
            }
            self.log_excerpts.clear();
            self.capabilities = Some(cut);
        }
    }
}

/// Reads the tail of a file, on a character boundary.
///
/// Returns the text and whether it was cut. A byte offset into UTF-8 can land
/// inside a character, so the first partial character is discarded rather than
/// producing a replacement glyph in the middle of a log line.
pub fn read_tail(path: &Path, limit: u64) -> std::io::Result<(String, bool)> {
    use std::io::{Read, Seek, SeekFrom};
    let mut file = std::fs::File::open(path)?;
    let length = file.metadata()?.len();
    let truncated = length > limit;
    if truncated {
        file.seek(SeekFrom::Start(length - limit))?;
    }
    let mut buffer = Vec::new();
    file.read_to_end(&mut buffer)?;

    // The byte offset we seeked to can land *inside* a UTF-8 character, and
    // `from_utf8_lossy` would then turn the broken head into a replacement glyph
    // (U+FFFD) that stays in the log. Found by a test that cut 51 bytes into a run
    // of two-byte characters and got `"\u{FFFD}äää…"`.
    //
    // So the partial head is dropped *before* decoding. The bytes to skip are the
    // leading UTF-8 *continuation* bytes — those with the pattern `10xxxxxx`
    // (`0x80..=0xBF`). They can only belong to a character whose start was cut off.
    //
    // `Utf8Error::valid_up_to` is the wrong tool here and the first attempt used
    // it: when the cut lands inside a character, `valid_up_to()` is **0**, so
    // skipping that many bytes skips nothing and the replacement glyph stays.
    // Measured with a run of two-byte characters cut at an odd offset.
    let bytes = if truncated {
        let skip = buffer
            .iter()
            .take_while(|byte| (**byte & 0b1100_0000) == 0b1000_0000)
            .count();
        &buffer[skip..]
    } else {
        &buffer[..]
    };
    let text = String::from_utf8_lossy(bytes).to_string();

    // Then drop the partial first *line*: a log that starts mid-word reads as
    // corruption even when every character is intact.
    let text = if truncated {
        match text.find('\n') {
            Some(index) => text[index + 1..].to_string(),
            // One enormous line with no newline: keep it, but say it is cut.
            None => text,
        }
    } else {
        text
    };
    Ok((text, truncated))
}

/// The newest log files in a directory, newest first.
///
/// Sorted by modification time rather than by name: mpv's log names carry a pid,
/// and lexical order would be meaningless.
pub fn newest_logs(dir: &Path, limit: usize) -> Vec<PathBuf> {
    let Ok(entries) = std::fs::read_dir(dir) else {
        return Vec::new();
    };
    let mut files: Vec<(std::time::SystemTime, PathBuf)> = entries
        .filter_map(|entry| entry.ok())
        .filter(|entry| entry.file_type().map(|t| t.is_file()).unwrap_or(false))
        .filter(|entry| {
            entry
                .file_name()
                .to_string_lossy()
                .starts_with("streamarr-mpv-")
        })
        .filter_map(|entry| {
            let modified = entry.metadata().ok()?.modified().ok()?;
            Some((modified, entry.path()))
        })
        .collect();
    // Newest first: `Reverse` is clearer than a hand-written comparison and says
    // the intent (descending by time) rather than the mechanics.
    files.sort_by_key(|(modified, _)| std::cmp::Reverse(*modified));
    files
        .into_iter()
        .take(limit)
        .map(|(_, path)| path)
        .collect()
}

/// Collects a report from what is on this machine.
///
/// Takes the already-measured mpv capabilities rather than probing again: the
/// probe starts a process, and doing it twice for one report would make the
/// report itself a side effect worth avoiding.
pub fn collect(
    app_version: &str,
    platform: &str,
    mpv: Option<&MpvCapabilities>,
    gstreamer_version: Option<String>,
    capabilities: Option<String>,
    log_dir: &Path,
) -> Report {
    // `version` is optional in the probe result (a failed `--version` call must
    // not abort the whole probe), and the sets are ordered so the report is
    // stable between runs.
    let (mpv_version, mpv_video_outputs) = match mpv {
        Some(caps) => (
            caps.version.clone(),
            caps.video_outputs.iter().cloned().collect(),
        ),
        None => (None, Vec::new()),
    };

    let mut log_excerpts = Vec::new();
    for path in newest_logs(log_dir, MAX_LOG_FILES) {
        let Ok((tail, truncated)) = read_tail(&path, LOG_TAIL_BYTES) else {
            continue;
        };
        if tail.trim().is_empty() {
            // An empty log is not worth a section. mpv writes a 0-byte file when
            // it fails before initialising, and an empty section reads like a
            // bug in the report.
            continue;
        }
        log_excerpts.push(LogExcerpt {
            // Only the file name: a full path would put the user's home
            // directory into an uploaded report.
            name: path
                .file_name()
                .map(|n| n.to_string_lossy().to_string())
                .unwrap_or_else(|| "log".to_string()),
            tail: redact_secrets(&tail),
            truncated,
        });
    }

    let mut report = Report {
        app_version: app_version.to_string(),
        platform: platform.to_string(),
        mpv_version,
        mpv_video_outputs,
        gstreamer_version,
        capabilities,
        log_excerpts,
    };
    report.fit_to_server_limit();
    report
}

/// Headers and query keys whose value is a credential.
///
/// Lower-case, and the `=` is part of the key: `token=` cannot match the word
/// "tokenization", which is the kind of false positive that would make the redaction
/// look broken and get removed.
const SECRET_KEYS: [&str; 6] = [
    "token=",
    "password=",
    "passwd=",
    "api_key=",
    "apikey=",
    "secret=",
];

/// Whether a character can be part of a credential value.
///
/// Deliberately narrow. A value ends at whitespace, at `&`, at a quote and at anything
/// else — over-redacting a log line costs a little diagnosis, under-redacting costs a
/// credential.
fn is_credential_char(c: char) -> bool {
    c.is_ascii_alphanumeric() || matches!(c, '-' | '_' | '.' | '~' | '+' | '/')
}

/// Replaces credential values with `<redacted>`, keeping everything around them.
///
/// # Why this is not optional
///
/// mpv logs the URLs it opens and the options it is given, and both carry the **play
/// token**: the HLS manifest arrives as `playlist.m3u8?token=…` and the token is also
/// handed over as an `Authorization: Bearer` header. Measured in a real log file: four
/// occurrences of the token from a single playback.
///
/// The tail of these logs is what a support report uploads, so without this the app
/// would send the user's play tokens to the server as part of a bug report. The token is
/// short-lived and session-scoped, which makes it a small leak and not a harmless one —
/// it is valid for the duration of a stream, and the report is sent precisely when
/// something has gone wrong and the user least wants a second problem.
///
/// Redacting here rather than preventing the log line is the right layer: mpv will log
/// the manifest URL in any case, and a filter on the way out covers every source of a
/// credential in a log instead of the one that was noticed today.
pub fn redact_secrets(text: &str) -> String {
    let mut out = text.to_string();
    for key in SECRET_KEYS {
        out = redact_after(&out, key);
    }
    redact_after(&out, "Bearer ")
}

/// Redacts the value that follows every occurrence of `needle`.
///
/// ASCII-only case folding on purpose: `to_lowercase` can change a string's byte length
/// ("İ" becomes two bytes), which would make the offsets found in the folded copy point
/// into the wrong place of the original. `to_ascii_lowercase` cannot.
fn redact_after(text: &str, needle: &str) -> String {
    let lowered = text.to_ascii_lowercase();
    let needle_lower = needle.to_ascii_lowercase();
    let mut out = String::with_capacity(text.len());
    let mut cursor = 0usize;

    while let Some(offset) = lowered[cursor..].find(&needle_lower) {
        let after_key = cursor + offset + needle.len();
        out.push_str(&text[cursor..after_key]);

        // A quoted value is common in config-file syntax (`token="…"`), and stopping at
        // the quote would leave the credential in place while looking redacted.
        let rest = &text[after_key..];
        let quote_len = rest
            .chars()
            .next()
            .filter(|c| *c == '"' || *c == '\'')
            .map(char::len_utf8)
            .unwrap_or(0);
        if quote_len > 0 {
            out.push_str(&text[after_key..after_key + quote_len]);
        }

        let value_start = after_key + quote_len;
        let value_end = text[value_start..]
            .char_indices()
            .find(|(_, c)| !is_credential_char(*c))
            .map(|(index, _)| value_start + index)
            .unwrap_or(text.len());

        if value_end > value_start {
            out.push_str("<redacted>");
        }
        cursor = value_end;
    }

    out.push_str(&text[cursor..]);
    out
}

#[cfg(test)]
mod tests {
    use super::*;

    fn report_with_logs(count: usize, each: usize) -> Report {
        let logs = (0..count)
            .map(|i| LogExcerpt {
                name: format!("streamarr-mpv-{i}.log"),
                tail: "x".repeat(each),
                truncated: false,
            })
            .collect();
        Report {
            app_version: "2026.2.1".to_string(),
            platform: "linux-wayland".to_string(),
            mpv_version: Some("mpv v0.41.0".to_string()),
            mpv_video_outputs: vec!["gpu-next".to_string(), "gpu".to_string()],
            gstreamer_version: Some("1.28.7".to_string()),
            capabilities: Some("hardware_decode=true".to_string()),
            log_excerpts: logs,
        }
    }

    /// The leak this filter exists for, written from a real log line.
    #[test]
    fn a_play_token_in_a_manifest_url_is_redacted() {
        // Verbatim shape, measured in an mpv log: mpv logs every URL it opens, and the
        // manifest URL carries the play token.
        let line = "[   0.037][v][stream_callback] Opening https://streamarr.example/api/stream/s1/playlist.m3u8?token=mxsHi5KvsIVXiQyYHZPbo61pMDVQ_tZUN7kOfwOp0aI";
        let out = redact_secrets(line);
        assert!(
            !out.contains("mxsHi5KvsIVXiQyYHZPbo61pMDVQ"),
            "das Token steht noch drin"
        );
        assert!(out.contains("token=<redacted>"));
        // The rest of the line has to survive: a report that lost the URL would be
        // useless for exactly the failure it documents.
        assert!(out.contains("playlist.m3u8?"));
        assert!(out.contains("Opening"));
    }

    #[test]
    fn an_authorization_header_is_redacted() {
        let line = "[   0.002][v][cplayer] Setting option 'http-header-fields' = 'Authorization: Bearer mxsHi5KvsIVXiQyYHZPbo61pMDVQ_tZUN7kOfwOp0aI' (flags = 4)";
        let out = redact_secrets(line);
        assert!(!out.contains("mxsHi5KvsIVXiQyYHZPbo61pMDVQ"));
        assert!(out.contains("Authorization: Bearer <redacted>"));
        assert!(out.contains("Setting option"));
    }

    #[test]
    fn a_quoted_value_is_redacted_and_the_quotes_stay() {
        // Stopping at the quote would leave the credential in place while looking
        // redacted, which is worse than not filtering: it reads as verified.
        let out = redact_secrets("token=\"abc123\"");
        assert!(!out.contains("abc123"));
        assert_eq!(out, "token=\"<redacted>\"");
    }

    #[test]
    fn every_occurrence_is_redacted_not_just_the_first() {
        // A real log had four.
        let out = redact_secrets("token=aaa token=bbb&api_key=ccc");
        assert!(!out.contains("aaa") && !out.contains("bbb") && !out.contains("ccc"));
        assert_eq!(out, "token=<redacted> token=<redacted>&api_key=<redacted>");
    }

    #[test]
    fn an_empty_value_is_left_alone() {
        // `token=` with nothing after it must not become `token=<redacted>`, which would
        // claim a credential was removed where there never was one.
        assert_eq!(redact_secrets("token= end"), "token= end");
    }

    #[test]
    fn ordinary_words_are_not_mangled() {
        // `token=` needs the `=`, and this is why it is part of the key rather than a
        // separate check: a filter that redacts the word "token" would damage the
        // diagnostics it is supposed to preserve.
        let line = "tokenization failed, the token count is 4, tokens: 12";
        assert_eq!(redact_secrets(line), line);
    }

    #[test]
    fn the_report_redacts_the_tails_it_collects() {
        // The unit above could pass while `collect` forgot to call it, which is the whole
        // reason this test exists: the filter has to sit on the path to the upload.
        let dir = std::env::temp_dir().join("streamarr-report-redact");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(
            dir.join("streamarr-mpv-1.log"),
            "Opening https://s/api/stream/x/playlist.m3u8?token=SUPERSECRETVALUE\n",
        )
        .unwrap();

        let report = collect("2026.2.1", "linux-wayland", None, None, None, &dir);
        let text = serde_json::to_string(&report).unwrap();
        assert!(
            !text.contains("SUPERSECRETVALUE"),
            "das Token steht im Bericht: {text}"
        );
        assert!(text.contains("<redacted>"));
    }

    #[test]
    fn a_password_and_a_secret_key_are_redacted_too() {
        // Not because this app logs them today, but because the filter is on the way out
        // and the cost of covering them is one array entry.
        let out = redact_secrets("password=hunter2 secret=s3cr3t");
        assert!(!out.contains("hunter2") && !out.contains("s3cr3t"));
    }

    #[test]
    fn the_message_carries_the_versions_on_top() {
        let message = report_with_logs(0, 0).to_message();
        let lines: Vec<&str> = message.lines().take(5).collect();
        assert!(lines[0].contains("Desktop client report"));
        assert!(lines[1].contains("2026.2.1"));
        assert!(lines[2].contains("linux-wayland"));
        assert!(lines[3].contains("mpv v0.41.0"));
        // A reader wants to know which version and which platform before reading
        // any log excerpt.
        assert!(message.find("mpv v0.41.0").unwrap() < message.len());
    }

    #[test]
    fn a_missing_mpv_is_stated_rather_than_omitted() {
        let mut report = report_with_logs(0, 0);
        report.mpv_version = None;
        report.mpv_video_outputs.clear();
        let message = report.to_message();
        // "mpv: not installed" is a finding; an absent line looks like a
        // collection that failed.
        assert!(message.contains("mpv: not installed"), "{message}");
    }

    #[test]
    fn a_build_without_gstreamer_says_so() {
        let mut report = report_with_logs(0, 0);
        report.gstreamer_version = None;
        let message = report.to_message();
        // Not "unknown": this build genuinely does not link GStreamer, and the
        // difference matters when a user reports that games do not start.
        assert!(
            message.contains("GStreamer: not in this build"),
            "{message}"
        );
    }

    #[test]
    fn the_capability_claims_are_included() {
        // The server picks a resolution and codec from these; a wrong claim
        // produces a stream that plays badly with nothing in the logs to say why.
        let message = report_with_logs(0, 0).to_message();
        assert!(message.contains("hardware_decode=true"), "{message}");
    }

    #[test]
    fn has_logs_reflects_reality() {
        assert!(!report_with_logs(0, 0).has_logs());
        assert!(report_with_logs(1, 10).has_logs());
        // An excerpt with an empty tail is not a log.
        let mut report = report_with_logs(0, 0);
        report.log_excerpts.push(LogExcerpt {
            name: "leer.log".to_string(),
            tail: String::new(),
            truncated: false,
        });
        assert!(!report.has_logs());
    }

    #[test]
    fn a_report_within_the_limit_is_untouched() {
        let mut report = report_with_logs(1, 100);
        let before = report.to_message();
        report.fit_to_server_limit();
        assert_eq!(report.to_message(), before);
        assert!(report.to_message().len() <= Report::SERVER_MESSAGE_LIMIT);
    }

    #[test]
    fn an_oversized_report_is_trimmed_to_fit() {
        // The server rejects a message over 4096 bytes, and a rejected report is
        // one the user believes was sent.
        let mut report = report_with_logs(3, 5_000);
        assert!(report.to_message().len() > Report::SERVER_MESSAGE_LIMIT);
        report.fit_to_server_limit();
        assert!(
            report.to_message().len() <= Report::SERVER_MESSAGE_LIMIT,
            "Länge {}",
            report.to_message().len()
        );
    }

    #[test]
    fn trimming_drops_logs_before_versions() {
        let mut report = report_with_logs(3, 5_000);
        report.fit_to_server_limit();
        let message = report.to_message();
        // The versions are what make a report answerable; the logs are the bulk.
        assert!(message.contains("2026.2.1"), "{message}");
        assert!(message.contains("mpv v0.41.0"), "{message}");
        assert!(message.contains("linux-wayland"), "{message}");
    }

    #[test]
    fn a_truncated_excerpt_is_marked_as_such() {
        let mut report = report_with_logs(0, 0);
        report.log_excerpts.push(LogExcerpt {
            name: "a.log".to_string(),
            tail: "Zeile\n".to_string(),
            truncated: true,
        });
        // A reader must be able to tell a complete log from an excerpt, or they
        // will look for a message that was never included.
        assert!(
            report.to_message().contains("gekürzt"),
            "{}",
            report.to_message()
        );
    }

    #[test]
    fn read_tail_returns_a_short_file_whole() {
        let dir = std::env::temp_dir().join("streamarr-report-short");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("short.log");
        std::fs::write(&path, "Zeile eins\nZeile zwei\n").unwrap();
        let (text, truncated) = read_tail(&path, 1024).unwrap();
        assert_eq!(text, "Zeile eins\nZeile zwei\n");
        assert!(!truncated);
    }

    #[test]
    fn read_tail_cuts_on_a_line_boundary() {
        let dir = std::env::temp_dir().join("streamarr-report-cut");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("long.log");
        // Ten lines of ten characters; read the last 25 bytes.
        let content: String = (0..10).map(|i| format!("Zeile{i:04}\n")).collect();
        std::fs::write(&path, &content).unwrap();
        let (text, truncated) = read_tail(&path, 25).unwrap();
        assert!(truncated);
        // A partial first line reads as corruption, so it is dropped.
        assert!(!text.starts_with("ile"), "angefangene Zeile: {text:?}");
        assert!(text.ends_with('\n'));
    }

    #[test]
    fn read_tail_does_not_split_a_character() {
        let dir = std::env::temp_dir().join("streamarr-report-utf8");
        let _ = std::fs::create_dir_all(&dir);
        let path = dir.join("utf8.log");
        // Multi-byte characters throughout, so a byte-offset cut lands inside one.
        let content = "ä".repeat(100);
        std::fs::write(&path, &content).unwrap();
        let (text, truncated) = read_tail(&path, 51).unwrap();
        assert!(truncated);
        // Every character is intact; a split would produce a replacement glyph.
        assert!(!text.contains('\u{FFFD}'), "kaputtes Zeichen in {text:?}");
    }

    #[test]
    fn read_tail_of_a_missing_file_is_an_error_not_a_panic() {
        let missing = std::env::temp_dir().join("streamarr-gibt-es-nicht.log");
        let _ = std::fs::remove_file(&missing);
        assert!(read_tail(&missing, 128).is_err());
    }

    #[test]
    fn newest_logs_picks_the_most_recent_and_ignores_other_files() {
        let dir = std::env::temp_dir().join("streamarr-report-newest");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("streamarr-mpv-1-1.log"), "alt").unwrap();
        // A foreign file must not be picked up: this function decides what leaves
        // the machine.
        std::fs::write(dir.join("etwas-anderes.log"), "privat").unwrap();
        let picked = newest_logs(&dir, 5);
        assert_eq!(picked.len(), 1, "{picked:?}");
        assert!(picked[0].to_string_lossy().contains("streamarr-mpv-"));
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn newest_logs_honours_its_limit() {
        let dir = std::env::temp_dir().join("streamarr-report-limit");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        for i in 0..6 {
            std::fs::write(dir.join(format!("streamarr-mpv-{i}-1.log")), "x").unwrap();
        }
        assert_eq!(newest_logs(&dir, 3).len(), 3);
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn newest_logs_of_a_missing_directory_is_empty() {
        // A first run has no log directory yet; that is not an error.
        assert!(newest_logs(Path::new("/gibt/es/nicht"), 3).is_empty());
    }

    #[test]
    fn collect_includes_only_the_log_file_name_never_a_path() {
        let dir = std::env::temp_dir().join("streamarr-report-collect");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        std::fs::write(dir.join("streamarr-mpv-9-1.log"), "Start\nFehler\n").unwrap();

        let report = collect("2026.2.1", "linux-wayland", None, None, None, &dir);
        assert_eq!(report.log_excerpts.len(), 1);
        let name = &report.log_excerpts[0].name;
        // The whole point: a path would upload the user's home directory.
        assert_eq!(name, "streamarr-mpv-9-1.log");
        assert!(!name.contains('/'), "Pfad im Bericht: {name}");
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn collect_skips_empty_log_files() {
        let dir = std::env::temp_dir().join("streamarr-report-empty");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        // mpv writes a 0-byte file when it fails before initialising; an empty
        // section would read like a bug in the report.
        std::fs::write(dir.join("streamarr-mpv-1-1.log"), "").unwrap();
        let report = collect("2026.2.1", "linux", None, None, None, &dir);
        assert!(report.log_excerpts.is_empty());
        let _ = std::fs::remove_dir_all(&dir);
    }

    #[test]
    fn collect_trims_to_the_server_limit() {
        let dir = std::env::temp_dir().join("streamarr-report-big");
        let _ = std::fs::remove_dir_all(&dir);
        std::fs::create_dir_all(&dir).unwrap();
        let big = "Zeile mit Inhalt\n".repeat(2000);
        std::fs::write(dir.join("streamarr-mpv-1-1.log"), &big).unwrap();
        let report = collect("2026.2.1", "linux", None, None, None, &dir);
        assert!(report.to_message().len() <= Report::SERVER_MESSAGE_LIMIT);
        let _ = std::fs::remove_dir_all(&dir);
    }
}

// ---------------------------------------------------------------------------
// The command
// ---------------------------------------------------------------------------

use tauri::State;

use super::bridge::current_access_token_for_report;
use crate::AppState;

/// What the UI learns after asking for a report.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
#[serde(tag = "kind", rename_all = "camelCase")]
pub enum ReportOutcome {
    /// The server accepted it. `detail` is for a log line, not for the user.
    Sent { bytes: usize, has_logs: bool },
    /// The report was built but could not be sent, with the reason.
    ///
    /// Distinct from a failure to *build* one: the user can retry, and the
    /// collected text is still on screen for them to copy.
    NotSent {
        problem: String,
        advice: Option<String>,
        message: String,
    },
}

/// Builds a support report and sends it to the server's log endpoint.
///
/// Takes **no arguments**. That is the security property, not an oversight: a
/// command that accepted a file path or an extra field would be a way for the
/// WebView to read arbitrary files through a "report". Everything included is
/// chosen here.
///
/// The body it posts is the server's own schema
/// (`backend/src/streamarr/api/v1/client_logs.py`): `level`, `message`, `source`
/// and a small `context`. The server bounds the message at 4096 bytes and the
/// context at 8 KiB, and `Report::fit_to_server_limit` keeps the message under
/// that before it is sent — a report rejected by the server is one the user
/// believes was sent.
#[tauri::command]
pub async fn report_problem(
    app: tauri::AppHandle,
    state: State<'_, AppState>,
) -> Result<ReportOutcome, String> {
    // The app version comes from the bundle rather than from a constant here, so
    // a report cannot claim a version the build does not have.
    let app_version = state.app_version();
    let platform = format!("{}-{}", std::env::consts::OS, display_server());

    // Measured through the app handle, because the display size comes from the
    // window. Passed in rather than reached for: the alternative would be an
    // `AppState` method that silently returns nothing off the main thread, and a
    // capability claim that is quietly absent is worse than one that is measured.
    let capabilities = capabilities_summary(&app);

    // The log directory is derived from the runtime dir the player uses, not
    // passed in. `None` when there is no runtime dir at all, which a Linux
    // session always has and a test process may not.
    let log_dir = state.player_log_dir();
    let report = match &log_dir {
        Some(dir) => collect(
            &app_version,
            &platform,
            None,
            gstreamer_version(),
            capabilities,
            dir,
        ),
        None => collect(
            &app_version,
            &platform,
            None,
            gstreamer_version(),
            capabilities,
            Path::new("/nonexistent"),
        ),
    };

    let has_logs = report.has_logs();
    let payload = serde_json::json!({
        "level": "info",
        "message": report.to_message(),
        "source": "desktop-app",
        "context": {
            "app_version": report.app_version,
            "platform": report.platform,
            // A boolean rather than the claims themselves: they also appear in
            // the message, and duplicating them would spend the context budget
            // twice over.
            "capabilities_reported": report.capabilities.is_some(),
            "logs_attached": has_logs,
        },
    });
    let body = payload.to_string();

    let client = match state.api() {
        Ok(client) => client,
        Err(err) => {
            let server = state.device_server();
            let (kind, detail) = err.failure();
            let diagnosis = crate::api::diagnose(&server, kind, &detail);
            return Ok(ReportOutcome::NotSent {
                problem: diagnosis.problem,
                advice: diagnosis.advice,
                message: report.to_message(),
            });
        }
    };

    // The access token, as for every other call. `None` is not an error here:
    // the endpoint requires authentication, so an anonymous report comes back
    // 401 and is reported as "not sent" with the server's own explanation.
    let mut headers = Vec::new();
    if let Some(token) = current_access_token_for_report(&state)? {
        headers.push(("Authorization".to_string(), format!("Bearer {token}")));
    }
    headers.push(("Content-Type".to_string(), "application/json".to_string()));

    let request = crate::api::RawRequest {
        method: "POST".to_string(),
        path: "/api/client-logs".to_string(),
        // `None` means the active profile's server — and with it the resolve pin.
        // A report must go to the server the user is actually using, and the pin
        // is the shell's job for every request, not a special case here.
        base_url: None,
        headers,
        body: Some(body.clone()),
        timeout_ms: Some(20_000),
    };

    match client.raw_request(&request).await {
        Ok(response) if (200..300).contains(&response.status) => Ok(ReportOutcome::Sent {
            bytes: body.len(),
            has_logs,
        }),
        Ok(response) => Ok(ReportOutcome::NotSent {
            // The server's own words, not a paraphrase: it knows why it refused.
            problem: format!(
                "Der Server hat den Bericht abgelehnt (HTTP {}).",
                response.status
            ),
            // The body is an enum, not a string: a binary response has no text to
            // show, and pretending otherwise would put base64 in a dialog.
            advice: match &response.body {
                crate::api::RawBody::Text(text) => Some(truncate_for_advice(text)),
                _ => None,
            },
            message: report.to_message(),
        }),
        Err(err) => {
            let server = state.device_server();
            let (kind, detail) = err.failure();
            let diagnosis = crate::api::diagnose(&server, kind, &detail);
            Ok(ReportOutcome::NotSent {
                problem: diagnosis.problem,
                advice: diagnosis.advice,
                message: report.to_message(),
            })
        }
    }
}

/// The capability claims the app would send to the server, as one line.
///
/// They matter for a support report because the server picks a resolution and a
/// codec from them: a wrong claim produces a stream that plays badly, and nothing
/// in any log would say what was claimed.
fn capabilities_summary(app: &tauri::AppHandle) -> Option<String> {
    // The display size is part of the claim, so it is measured rather than
    // assumed — the same defect as the hardcoded 1920 in `register_capabilities`,
    // which existed once already.
    let width = crate::commands::session::current_display_size(app)
        .map(|(width, _)| width)
        .unwrap_or(0);
    let detected = crate::commands::session::detect_capabilities(width);
    let caps = &detected.capabilities;

    // Built by hand rather than with `serde_json`: `Capabilities` is sent to the
    // server as *query parameters* and deliberately has no `Serialize`. Deriving
    // one here would create a second, silently different definition of the claim —
    // and this is exactly the claim whose accuracy a report is supposed to
    // establish.
    Some(format!(
        "video={:?} audio={:?} max_resolution={:?} hdr={} hwdecode={} app={}/{}",
        caps.video_codecs,
        caps.audio_codecs,
        caps.max_resolution,
        caps.supports_hdr,
        caps.hardware_decode,
        caps.app_name,
        caps.app_version,
    ))
}

/// The GStreamer version, when this build links it.
///
/// Reported as `None` rather than as an empty string when the feature is off:
/// "this build does not have GStreamer" and "GStreamer reported no version" are
/// different findings.
fn gstreamer_version() -> Option<String> {
    // No `cfg(feature = "spike")` here, and that is not an omission. The shell
    // does **not** enable the core's `spike` feature: the game pipeline is
    // implemented and proven in `desktop/player`, but it is not yet wired into the
    // shell, so this build links no GStreamer at all. A `cfg` on a feature the
    // crate does not have is a warning, and rightly so — it would claim a
    // conditional that can never be true.
    //
    // When the shell does enable it, this function is where the version is read,
    // and the package dependencies in `tauri.conf.json` have to grow with it.
    None
}

/// Which display server the app is on, for the platform string.
///
/// `WAYLAND_DISPLAY` before `DISPLAY`, because a Wayland session usually exports
/// both and the sink choice depends on it — the report should say what the app
/// would actually pick.
fn display_server() -> &'static str {
    if std::env::var_os("WAYLAND_DISPLAY").is_some() {
        "wayland"
    } else if std::env::var_os("DISPLAY").is_some() {
        "x11"
    } else {
        "headless"
    }
}

/// A bounded excerpt of the server's answer, for the advice line.
///
/// Bounded because the server's error body can be an HTML page from a proxy,
/// which is not something to put in a dialog.
fn truncate_for_advice(body: &str) -> String {
    let text = body.trim();
    let cut: String = text.chars().take(300).collect();
    if text.chars().count() > 300 {
        format!("{cut}…")
    } else {
        cut
    }
}

/// A one-line summary for the UI, without the log bodies.
///
/// Offered as a separate command so the interface can show *what* a report would
/// contain before the user sends it. Sending something unseen to a server is not
/// a thing to do quietly.
#[tauri::command]
pub fn report_preview(app: tauri::AppHandle, state: State<'_, AppState>) -> ReportPreview {
    let log_dir = state.player_log_dir();
    let report = match &log_dir {
        Some(dir) => collect(
            &state.app_version(),
            &format!("{}-{}", std::env::consts::OS, display_server()),
            None,
            gstreamer_version(),
            capabilities_summary(&app),
            dir,
        ),
        None => collect(
            &state.app_version(),
            &format!("{}-{}", std::env::consts::OS, display_server()),
            None,
            gstreamer_version(),
            capabilities_summary(&app),
            Path::new("/nonexistent"),
        ),
    };
    ReportPreview {
        app_version: report.app_version.clone(),
        platform: report.platform.clone(),
        mpv_version: report.mpv_version.clone(),
        gstreamer_version: report.gstreamer_version.clone(),
        log_count: report.log_excerpts.len(),
        log_bytes: report.log_excerpts.iter().map(|e| e.tail.len()).sum(),
        has_logs: report.has_logs(),
    }
}

/// What the UI shows before a report is sent.
#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct ReportPreview {
    pub app_version: String,
    pub platform: String,
    pub mpv_version: Option<String>,
    pub gstreamer_version: Option<String>,
    /// How many log files would be attached.
    pub log_count: usize,
    /// Total size of the included excerpts.
    pub log_bytes: usize,
    pub has_logs: bool,
}
