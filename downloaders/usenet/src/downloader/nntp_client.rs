use crate::config::UsenetConfig;
use crate::error::AppError;
use chrono::{DateTime, Utc};
use std::sync::atomic::{AtomicBool, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::io::{AsyncBufReadExt, AsyncWriteExt, BufReader, ReadHalf, WriteHalf};
use tokio::net::TcpStream;
use tokio_rustls::client::TlsStream;
use tokio_rustls::TlsConnector;
use tracing::{debug, info, warn};

type TlsReader = BufReader<ReadHalf<TlsStream<TcpStream>>>;
type TlsWriter = WriteHalf<TlsStream<TcpStream>>;
type PlainReader = BufReader<tokio::net::tcp::OwnedReadHalf>;
type PlainWriter = tokio::net::tcp::OwnedWriteHalf;

/// NNTP error codes that mean "article not found" — should trigger backup server fallback.
/// 411 = no such group, 423 = no article with that number, 430 = no article with that message-id,
/// 451 = server internal fault (SABnzbd treats as missing to allow retry on another server)
const ARTICLE_MISSING_CODES: &[&str] = &["411", "423", "430", "451"];

/// Check if an error string indicates an article-not-found condition.
pub fn is_article_missing(err: &str) -> bool {
    ARTICLE_MISSING_CODES.iter().any(|code| err.contains(code))
        || err.contains("not found on any server")
}

// --- Server penalty model (mirrors SABnzbd downloader.py:44-51) ---
// How long a server is skipped after a connection/auth failure, so other
// articles don't each pay the full connect/read timeout on a dead server.
const PENALTY_UNKNOWN: Duration = Duration::from_secs(3 * 60);
const PENALTY_502: Duration = Duration::from_secs(5 * 60);
const PENALTY_TIMEOUT: Duration = Duration::from_secs(10 * 60);
const PENALTY_TOOMANY: Duration = Duration::from_secs(10 * 60);
const PENALTY_PERM: Duration = Duration::from_secs(10 * 60);

/// What to do with a server pool after a failure.
enum Penalty {
    /// Article-level (411/423/430/451): the server is healthy, just fetch
    /// the article elsewhere. Never blocks the server.
    ArticleLevel,
    /// One-off request failure (single read/body error). Counts toward the
    /// bad-connection tally but does not block on its own.
    Transient,
    /// Block the server pool for this long, then auto-resume.
    Block(Duration),
    /// Permanent problem (bad credentials): deactivate for this long.
    Deactivate(Duration),
}

fn clues_too_many(msg: &str) -> bool {
    let m = msg.to_lowercase();
    m.contains("too many")
        || m.contains("connection limit")
        || m.contains("maximum")
        || m.contains("concurrent")
}

fn clues_login(msg: &str) -> bool {
    let m = msg.to_lowercase();
    m.contains("authentication")
        || m.contains("auth")
        || m.contains("login")
        || m.contains("password")
        || m.contains("permission")
}

/// Extract a 3-digit NNTP status code from an error message, if present.
/// Only a whitespace-delimited token that is *entirely* 3 digits counts, so
/// embedded numbers like the `:563` port in "connect to host:563" or digits
/// inside a `<...>` message-id can't be mistaken for a status code. Our error
/// strings always render the code as its own token ("…failed: 481 …",
/// "BODY failed for <id>: 430 …").
fn nntp_code(err: &str) -> Option<u16> {
    err.split_whitespace().find_map(|tok| {
        let t = tok.trim_end_matches([',', '.', ';']);
        if t.len() == 3 && t.bytes().all(|b| b.is_ascii_digit()) {
            t.parse::<u16>().ok().filter(|&c| (100..600).contains(&c))
        } else {
            None
        }
    })
}

/// Classify an NNTP/connection error into a server penalty.
fn classify_error(err: &str) -> Penalty {
    if is_article_missing(err) {
        return Penalty::ArticleLevel;
    }
    let code = nntp_code(err);
    let is = |c: u16| code == Some(c);

    // Permanent auth/login failure → deactivate.
    if err.contains("Authentication failed")
        || is(481)
        || is(482)
        || is(452)
        || is(381)
        || ((is(500) || is(502)) && clues_login(err))
    {
        return Penalty::Deactivate(PENALTY_PERM);
    }
    // Too many connections / account sharing.
    if (is(502) || is(400) || is(481) || is(482)) && clues_too_many(err) {
        return Penalty::Block(PENALTY_TOOMANY);
    }
    // Connect / handshake / socket failure → server unreachable. Block now so
    // every other article skips it instead of each paying the connect timeout.
    if err.contains("Failed to connect")
        || err.contains("Connection timeout")
        || err.contains("TLS handshake")
        || err.contains("Connection closed")
        || err.contains("Connection refused")
    {
        return Penalty::Block(PENALTY_TIMEOUT);
    }
    if is(502) || is(482) {
        return Penalty::Block(PENALTY_502);
    }
    // Read/write timeout mid-request or other one-off → transient.
    if err.contains("timeout") || err.contains("Read failed") || err.contains("Write failed") {
        return Penalty::Transient;
    }
    Penalty::Block(PENALTY_UNKNOWN)
}

enum Reader {
    Plain(PlainReader),
    Tls(TlsReader),
}

enum Writer {
    Plain(PlainWriter),
    Tls(TlsWriter),
}

pub struct NntpClient {
    reader: Reader,
    writer: Writer,
    current_group: Option<String>,
    timeout: Duration,
}

impl NntpClient {
    pub async fn connect(config: &UsenetConfig, timeout: Duration) -> Result<Self, AppError> {
        let addr = format!("{}:{}", config.host, config.port);
        let tcp_stream = tokio::time::timeout(
            timeout,
            TcpStream::connect(&addr),
        )
        .await
        .map_err(|_| AppError::Nntp(format!("Connection timeout to {}", addr)))?
        .map_err(|e| AppError::Nntp(format!("Failed to connect to {}: {}", addr, e)))?;

        let mut client = if config.tls {
            let mut root_store = rustls::RootCertStore::empty();
            root_store.extend(webpki_roots::TLS_SERVER_ROOTS.iter().cloned());

            let tls_config = rustls::ClientConfig::builder()
                .with_root_certificates(root_store)
                .with_no_client_auth();

            let connector = TlsConnector::from(Arc::new(tls_config));
            let server_name = config
                .host
                .clone()
                .try_into()
                .map_err(|e| AppError::Nntp(format!("Invalid server name: {}", e)))?;

            let tls_stream = tokio::time::timeout(
                timeout,
                connector.connect(server_name, tcp_stream),
            )
            .await
            .map_err(|_| AppError::Nntp(format!("TLS handshake timeout for {}", addr)))?
            .map_err(|e| AppError::Nntp(format!("TLS handshake failed: {}", e)))?;

            let (read_half, write_half) = tokio::io::split(tls_stream);
            Self {
                reader: Reader::Tls(BufReader::new(read_half)),
                writer: Writer::Tls(write_half),
                current_group: None,
                timeout,
            }
        } else {
            let (read_half, write_half) = tcp_stream.into_split();
            Self {
                reader: Reader::Plain(BufReader::new(read_half)),
                writer: Writer::Plain(write_half),
                current_group: None,
                timeout,
            }
        };

        let greeting = client.read_line_timeout().await?;
        debug!("NNTP greeting: {}", greeting.trim());
        Ok(client)
    }

    pub async fn authenticate(&mut self, username: &str, password: &str) -> Result<(), AppError> {
        self.send_command(&format!("AUTHINFO USER {}", username))
            .await?;
        let response = self.read_line_timeout().await?;

        if response.starts_with("381") {
            self.send_command(&format!("AUTHINFO PASS {}", password))
                .await?;
            let response = self.read_line_timeout().await?;
            if !response.starts_with("281") {
                return Err(AppError::Nntp(format!(
                    "Authentication failed: {}",
                    response.trim()
                )));
            }
        } else if !response.starts_with("281") {
            return Err(AppError::Nntp(format!(
                "Authentication failed: {}",
                response.trim()
            )));
        }

        debug!("NNTP authentication successful");
        Ok(())
    }

    pub async fn body(&mut self, message_id: &str) -> Result<Vec<u8>, AppError> {
        let cmd = if message_id.starts_with('<') {
            format!("BODY {}", message_id)
        } else {
            format!("BODY <{}>", message_id)
        };

        self.send_command(&cmd).await?;
        let response = self.read_line_timeout().await?;

        if !response.starts_with("222") {
            return Err(AppError::Nntp(format!(
                "BODY failed for {}: {}",
                message_id,
                response.trim()
            )));
        }

        self.read_multiline_body().await
    }

    pub async fn stat(&mut self, message_id: &str) -> Result<bool, AppError> {
        let cmd = if message_id.starts_with('<') {
            format!("STAT {}", message_id)
        } else {
            format!("STAT <{}>", message_id)
        };

        self.send_command(&cmd).await?;
        let response = self.read_line_timeout().await?;
        Ok(response.starts_with("223"))
    }

    /// Send multiple BODY commands and read all responses without waiting between each.
    /// Returns a Vec of (message_id, Result<body>) in the same order as the input.
    /// Falls back to sequential if `pipeline_depth` is 1.
    pub async fn fetch_pipelined(
        &mut self,
        message_ids: &[String],
    ) -> Result<Vec<(String, Result<Vec<u8>, AppError>)>, AppError> {
        if message_ids.is_empty() {
            return Ok(Vec::new());
        }

        // Send all BODY commands first
        for mid in message_ids {
            let cmd = if mid.starts_with('<') {
                format!("BODY {}\r\n", mid)
            } else {
                format!("BODY <{}>\r\n", mid)
            };
            debug!("NNTP pipeline > BODY {}", mid);
            let bytes = cmd.as_bytes();
            let write_result = match &mut self.writer {
                Writer::Plain(w) => tokio::time::timeout(self.timeout, async {
                    w.write_all(bytes).await?;
                    w.flush().await
                })
                .await,
                Writer::Tls(w) => tokio::time::timeout(self.timeout, async {
                    w.write_all(bytes).await?;
                    w.flush().await
                })
                .await,
            };
            match write_result {
                Ok(Ok(())) => {}
                Ok(Err(e)) => return Err(AppError::Nntp(format!("Pipeline write failed: {}", e))),
                Err(_) => return Err(AppError::Nntp("Pipeline write timeout".to_string())),
            }
        }

        // Now read all responses
        let mut results = Vec::with_capacity(message_ids.len());
        for mid in message_ids {
            let response = self.read_line_timeout().await?;
            if response.starts_with("222") {
                let body = self.read_multiline_body().await;
                results.push((mid.clone(), body));
            } else {
                results.push((
                    mid.clone(),
                    Err(AppError::Nntp(format!(
                        "BODY failed for {}: {}",
                        mid,
                        response.trim()
                    ))),
                ));
            }
        }

        Ok(results)
    }

    pub async fn group(&mut self, group: &str) -> Result<(), AppError> {
        if let Some(ref current) = self.current_group {
            if current == group {
                return Ok(());
            }
        }

        self.send_command(&format!("GROUP {}", group)).await?;
        let response = self.read_line_timeout().await?;
        if response.starts_with("211") {
            self.current_group = Some(group.to_string());
            debug!("NNTP group set to: {}", group);
            Ok(())
        } else {
            warn!("NNTP GROUP command failed for {}: {}", group, response.trim());
            Err(AppError::Nntp(format!(
                "GROUP command failed for {}: {}",
                group,
                response.trim()
            )))
        }
    }

    pub async fn article(&mut self, message_id: &str) -> Result<Vec<u8>, AppError> {
        let cmd = if message_id.starts_with('<') {
            format!("ARTICLE {}", message_id)
        } else {
            format!("ARTICLE <{}>", message_id)
        };

        self.send_command(&cmd).await?;
        let response = self.read_line_timeout().await?;

        if !response.starts_with("220") {
            return Err(AppError::Nntp(format!(
                "ARTICLE failed for {}: {}",
                message_id,
                response.trim()
            )));
        }

        // Skip headers, read body only
        let mut body = Vec::new();
        let mut past_headers = false;
        loop {
            let line = self.read_raw_line_timeout().await?;
            if line == b".\r\n" || line == b".\n" {
                break;
            }

            if !past_headers {
                if line == b"\r\n" || line == b"\n" {
                    past_headers = true;
                }
                continue;
            }

            if line.starts_with(b"..") {
                body.extend_from_slice(&line[1..]);
            } else {
                body.extend_from_slice(&line);
            }
        }

        Ok(body)
    }

    pub async fn keepalive(&mut self) -> Result<(), AppError> {
        self.send_command("DATE").await?;
        let response = self.read_line_timeout().await?;
        if response.starts_with("111") {
            Ok(())
        } else {
            Err(AppError::Nntp(format!(
                "Keepalive failed: {}",
                response.trim()
            )))
        }
    }

    pub async fn quit(&mut self) -> Result<(), AppError> {
        self.send_command("QUIT").await?;
        let _ = self.read_line_timeout().await;
        Ok(())
    }

    /// Read a multi-line NNTP body response (dot-stuffed, terminated by ".\r\n").
    async fn read_multiline_body(&mut self) -> Result<Vec<u8>, AppError> {
        let mut body = Vec::new();
        loop {
            let line = self.read_raw_line_timeout().await?;
            if line == b".\r\n" || line == b".\n" {
                break;
            }
            if line.starts_with(b"..") {
                body.extend_from_slice(&line[1..]);
            } else {
                body.extend_from_slice(&line);
            }
        }
        Ok(body)
    }

    async fn send_command(&mut self, cmd: &str) -> Result<(), AppError> {
        debug!(
            "NNTP > {}",
            if cmd.starts_with("AUTHINFO PASS") {
                "AUTHINFO PASS ***"
            } else {
                cmd
            }
        );
        let data = format!("{}\r\n", cmd);
        let bytes = data.as_bytes();

        let write_result = match &mut self.writer {
            Writer::Plain(w) => {
                tokio::time::timeout(self.timeout, async {
                    w.write_all(bytes).await?;
                    w.flush().await
                }).await
            }
            Writer::Tls(w) => {
                tokio::time::timeout(self.timeout, async {
                    w.write_all(bytes).await?;
                    w.flush().await
                }).await
            }
        };

        match write_result {
            Ok(Ok(())) => Ok(()),
            Ok(Err(e)) => Err(AppError::Nntp(format!("Write failed: {}", e))),
            Err(_) => Err(AppError::Nntp("Write timeout".to_string())),
        }
    }

    async fn read_line_timeout(&mut self) -> Result<String, AppError> {
        let mut line = String::new();
        let read_result = tokio::time::timeout(self.timeout, async {
            match &mut self.reader {
                Reader::Plain(r) => r.read_line(&mut line).await,
                Reader::Tls(r) => r.read_line(&mut line).await,
            }
        })
        .await;

        match read_result {
            Ok(Ok(_)) => {
                debug!("NNTP < {}", line.trim());
                Ok(line)
            }
            Ok(Err(e)) => Err(AppError::Nntp(format!("Read failed: {}", e))),
            Err(_) => Err(AppError::Nntp("Read timeout".to_string())),
        }
    }

    async fn read_raw_line_timeout(&mut self) -> Result<Vec<u8>, AppError> {
        let mut buf = Vec::new();
        let read_result = tokio::time::timeout(self.timeout, async {
            match &mut self.reader {
                Reader::Plain(r) => read_until_newline(r, &mut buf).await,
                Reader::Tls(r) => read_until_newline(r, &mut buf).await,
            }
        })
        .await;

        match read_result {
            Ok(Ok(())) => Ok(buf),
            Ok(Err(e)) => Err(e),
            Err(_) => Err(AppError::Nntp("Read timeout".to_string())),
        }
    }
}

/// Returns true if the server's retention period has expired for the given publish date.
/// A retention of 0 means unlimited (never skip).
fn server_expired(config: &UsenetConfig, publish_date: Option<DateTime<Utc>>) -> bool {
    if config.retention_days == 0 {
        return false;
    }
    let Some(date) = publish_date else {
        return false;
    };
    let age_days = (Utc::now() - date).num_days();
    if age_days < 0 {
        return false;
    }
    age_days as u64 > config.retention_days
}

async fn read_until_newline<R: AsyncBufReadExt + Unpin>(
    reader: &mut R,
    buf: &mut Vec<u8>,
) -> Result<(), AppError> {
    loop {
        let available = reader
            .fill_buf()
            .await
            .map_err(|e| AppError::Nntp(format!("Read failed: {}", e)))?;
        if available.is_empty() {
            return Err(AppError::Nntp("Connection closed".to_string()));
        }
        if let Some(pos) = available.iter().position(|&b| b == b'\n') {
            buf.extend_from_slice(&available[..=pos]);
            let consume = pos + 1;
            reader.consume(consume);
            break;
        } else {
            let len = available.len();
            buf.extend_from_slice(available);
            reader.consume(len);
        }
    }
    Ok(())
}

/// Single-server connection pool with health/penalty tracking.
struct SingleServerPool {
    config: UsenetConfig,
    timeout: Duration,
    connections: tokio::sync::Mutex<Vec<NntpClient>>,
    semaphore: tokio::sync::Semaphore,
    /// `false` after a permanent (auth) failure until the penalty elapses.
    active: AtomicBool,
    /// Wall-clock instant before which this server is skipped entirely.
    blocked_until: std::sync::Mutex<Option<Instant>>,
    /// Consecutive one-off connection failures (drives the optional-server
    /// auto-deactivate / required-server block thresholds).
    bad_cons: AtomicUsize,
    /// Ensures the "server blocked" warning is logged once per outage.
    block_logged: AtomicBool,
}

impl SingleServerPool {
    fn new(config: UsenetConfig, timeout: Duration) -> Self {
        let max_conns = config.connections;
        Self {
            config,
            timeout,
            connections: tokio::sync::Mutex::new(Vec::new()),
            semaphore: tokio::sync::Semaphore::new(max_conns),
            active: AtomicBool::new(true),
            blocked_until: std::sync::Mutex::new(None),
            bad_cons: AtomicUsize::new(0),
            block_logged: AtomicBool::new(false),
        }
    }

    /// Is this server currently usable? Auto-resumes (and clears the bad
    /// counters) once a block window has elapsed — SABnzbd's scheduled
    /// `trigger_server` re-enable, without a separate scheduler.
    fn available(&self) -> bool {
        let mut bu = self.blocked_until.lock().unwrap();
        if let Some(t) = *bu {
            if Instant::now() >= t {
                *bu = None;
                drop(bu);
                self.bad_cons.store(0, Ordering::Relaxed);
                self.active.store(true, Ordering::Release);
                self.block_logged.store(false, Ordering::Relaxed);
                info!(
                    "Server {} penalty elapsed — reactivating",
                    self.config.host
                );
                return true;
            }
            return false;
        }
        drop(bu);
        self.active.load(Ordering::Acquire)
    }

    /// Block this server for `d`; `deactivate` also flips the active flag
    /// (used for permanent auth errors). The longer of any existing window
    /// and the new one wins.
    fn block_for(&self, d: Duration, deactivate: bool, err: &str) {
        let until = Instant::now() + d;
        {
            let mut bu = self.blocked_until.lock().unwrap();
            *bu = Some(match *bu {
                Some(existing) if existing > until => existing,
                _ => until,
            });
        }
        if deactivate {
            self.active.store(false, Ordering::Release);
        }
        if !self.block_logged.swap(true, Ordering::Relaxed) {
            let snippet: String = err.chars().take(120).collect();
            warn!(
                "Server {} blocked for {}s{}: {}",
                self.config.host,
                d.as_secs(),
                if deactivate { " (deactivated)" } else { "" },
                snippet
            );
        }
    }

    /// Apply the penalty for a failure. Article-level failures never block.
    fn penalize(&self, err: &str) {
        match classify_error(err) {
            Penalty::ArticleLevel => {}
            Penalty::Transient => {
                let n = self.bad_cons.fetch_add(1, Ordering::Relaxed) + 1;
                // Optional servers follow SABnzbd's ~30%-bad threshold;
                // the required primary gets a much higher bar so a few bad
                // articles don't sideline it.
                let threshold = if self.config.optional {
                    ((self.config.connections as f64) * 0.3).ceil() as usize
                } else {
                    self.config.connections.max(4) * 3
                };
                if n >= threshold.max(1) {
                    self.block_for(PENALTY_TIMEOUT, self.config.optional, err);
                }
            }
            Penalty::Block(d) => self.block_for(d, false, err),
            Penalty::Deactivate(d) => self.block_for(d, true, err),
        }
    }

    /// A request succeeded — clear the recent-failure tally.
    fn note_success(&self) {
        self.bad_cons.store(0, Ordering::Relaxed);
        self.block_logged.store(false, Ordering::Relaxed);
    }

    /// Open the pool's connections in parallel (best-effort). The old
    /// sequential version stalled startup for `connections * connect_timeout`
    /// (up to ~20 min) when a server was down; opening them concurrently
    /// bounds the worst case to a single connect timeout. Prewarm failures
    /// are not penalized — the first real fetch classifies and blocks the
    /// server appropriately.
    async fn prewarm(&self) {
        let mut set = tokio::task::JoinSet::new();
        for _ in 0..self.config.connections {
            let config = self.config.clone();
            let timeout = self.timeout;
            set.spawn(async move {
                let mut client = NntpClient::connect(&config, timeout).await?;
                client
                    .authenticate(&config.username, &config.password)
                    .await?;
                Ok::<NntpClient, AppError>(client)
            });
        }

        let mut conns = self.connections.lock().await;
        let mut first_err: Option<String> = None;
        while let Some(joined) = set.join_next().await {
            match joined {
                Ok(Ok(client)) => conns.push(client),
                Ok(Err(e)) => {
                    if first_err.is_none() {
                        first_err = Some(e.to_string());
                    }
                }
                Err(e) => {
                    if first_err.is_none() {
                        first_err = Some(e.to_string());
                    }
                }
            }
        }

        if conns.is_empty() {
            warn!(
                "Pre-warm: 0/{} connections to {} ({})",
                self.config.connections,
                self.config.host,
                first_err.as_deref().unwrap_or("unknown error")
            );
        } else {
            info!(
                "Pre-warmed {} connections to {}",
                conns.len(),
                self.config.host
            );
        }
    }

    async fn keepalive_all(&self) {
        let mut conns = self.connections.lock().await;
        let mut i = 0;
        while i < conns.len() {
            match conns[i].keepalive().await {
                Ok(()) => i += 1,
                Err(e) => {
                    warn!("Keepalive failed for connection {}, discarding: {}", i, e);
                    conns.remove(i);
                }
            }
        }
    }

    async fn acquire(&self) -> Result<NntpPoolGuard<'_>, AppError> {
        // Skip a blocked/deactivated server immediately — no connect attempt,
        // so callers don't each pay the connect timeout on a dead server.
        if !self.available() {
            return Err(AppError::Nntp(format!(
                "Server {} temporarily blocked",
                self.config.host
            )));
        }

        let permit = self
            .semaphore
            .acquire()
            .await
            .map_err(|e| AppError::Nntp(format!("Semaphore error: {}", e)))?;

        let client = {
            let mut conns = self.connections.lock().await;
            conns.pop()
        };

        let client = match client {
            Some(c) => c,
            None => {
                let mut client = match NntpClient::connect(&self.config, self.timeout).await {
                    Ok(c) => c,
                    Err(e) => {
                        self.penalize(&e.to_string());
                        return Err(e);
                    }
                };
                if let Err(e) = client
                    .authenticate(&self.config.username, &self.config.password)
                    .await
                {
                    self.penalize(&e.to_string());
                    return Err(e);
                }
                client
            }
        };

        Ok(NntpPoolGuard {
            client: Some(client),
            pool_conns: &self.connections,
            _permit: permit,
        })
    }
}

/// Connection pool with primary + backup server fallback.
/// When an article is not found on the primary server, backup servers
/// are tried in order — just like SABnzbd.
pub struct NntpPool {
    primary: SingleServerPool,
    primary_config: UsenetConfig,
    backups: Vec<SingleServerPool>,
    backup_configs: Vec<UsenetConfig>,
    /// Number of BODY commands to pipeline per connection.
    pipeline_depth: usize,
}

impl NntpPool {
    pub fn new(config: UsenetConfig, timeout: Duration) -> Self {
        Self {
            primary: SingleServerPool::new(config.clone(), timeout),
            primary_config: config,
            backups: Vec::new(),
            backup_configs: Vec::new(),
            pipeline_depth: 1,
        }
    }

    pub fn with_backups(config: UsenetConfig, backup_configs: Vec<UsenetConfig>, timeout: Duration) -> Self {
        let backups = backup_configs.iter().map(|c| SingleServerPool::new(c.clone(), timeout)).collect();
        Self {
            primary: SingleServerPool::new(config.clone(), timeout),
            primary_config: config,
            backup_configs,
            backups,
            pipeline_depth: 1,
        }
    }

    /// Set the pipeline depth (number of BODY commands sent before reading responses).
    pub fn with_pipeline_depth(mut self, depth: usize) -> Self {
        self.pipeline_depth = depth.max(1);
        self
    }

    /// Acquire a connection from the primary pool.
    pub async fn acquire(&self) -> Result<NntpPoolGuard<'_>, AppError> {
        self.primary.acquire().await
    }

    /// Number of server pools (primary + backups).
    pub fn server_count(&self) -> usize {
        1 + self.backups.len()
    }

    /// Servers (primary + backups) in selection order: ascending `priority`,
    /// the primary winning ties (pushed first; `sort_by_key` is stable).
    /// Mirrors SABnzbd's server priority levels.
    fn ordered_servers(&self) -> Vec<(&SingleServerPool, &UsenetConfig)> {
        let mut v: Vec<(&SingleServerPool, &UsenetConfig)> =
            Vec::with_capacity(1 + self.backups.len());
        v.push((&self.primary, &self.primary_config));
        for (b, c) in self.backups.iter().zip(self.backup_configs.iter()) {
            v.push((b, c));
        }
        v.sort_by_key(|(_, c)| c.priority);
        v
    }

    /// Pre-check a sample of message IDs using STAT to detect dead/DMCA'd releases.
    /// Returns (missing_count, sampled_count).
    /// If >50% are missing, the release is considered unavailable.
    pub async fn pre_check(&self, message_ids: &[String], groups: &[String]) -> Result<(usize, usize), AppError> {
        const SAMPLE_SIZE: usize = 10;

        if message_ids.is_empty() {
            return Ok((0, 0));
        }

        // Pick a uniform sample: up to SAMPLE_SIZE evenly distributed across all segments
        let sample: Vec<&String> = if message_ids.len() <= SAMPLE_SIZE {
            message_ids.iter().collect()
        } else {
            let step = message_ids.len() / SAMPLE_SIZE;
            (0..SAMPLE_SIZE).map(|i| &message_ids[i * step]).collect()
        };

        let sampled = sample.len();
        let mut missing = 0usize;

        for mid in &sample {
            let mut guard = self.primary.acquire().await?;
            if !groups.is_empty() {
                if let Err(e) = guard.client_mut().group(&groups[0]).await {
                    debug!("pre_check GROUP failed (non-fatal): {}", e);
                }
            }
            match guard.client_mut().stat(mid).await {
                Ok(true) => {
                    guard.release().await;
                }
                Ok(false) => {
                    guard.release().await;
                    missing += 1;
                    debug!("pre_check: STAT 430 for {}", mid);
                }
                Err(e) => {
                    guard.discard();
                    // Connection error during pre-check — treat as inconclusive, not missing
                    warn!("pre_check STAT error for {}: {}", mid, e);
                }
            }
        }

        info!("Pre-check: {}/{} sampled articles missing on primary server", missing, sampled);
        Ok((missing, sampled))
    }

    /// Fetch an article body, trying servers in priority order and skipping
    /// any that are retention-expired or currently blocked. A blocked server
    /// is skipped instantly (no connect attempt), so a dead primary no longer
    /// costs the connect timeout on every single article — the core fix vs.
    /// the old fixed primary→backup-every-time loop.
    /// `publish_date` is used to skip servers whose retention has expired.
    pub async fn fetch_article(
        &self,
        message_id: &str,
        groups: &[String],
        publish_date: Option<DateTime<Utc>>,
    ) -> Result<Vec<u8>, AppError> {
        let mut last_err: Option<AppError> = None;
        let mut tried_any = false;

        for (pool, cfg) in self.ordered_servers() {
            if server_expired(cfg, publish_date) {
                debug!(
                    "Skipping {} for {} — retention {} days exceeded",
                    cfg.host, message_id, cfg.retention_days
                );
                continue;
            }
            if !pool.available() {
                debug!("Skipping {} for {} — server blocked", cfg.host, message_id);
                continue;
            }
            tried_any = true;
            match self.try_fetch_with_group(pool, message_id, groups).await {
                Ok(body) => return Ok(body),
                Err(e) => {
                    debug!("Article {} failed on {}: {}", message_id, cfg.host, e);
                    last_err = Some(e);
                }
            }
        }

        if !tried_any {
            return Err(AppError::Nntp(format!(
                "Article {}: no servers available (all blocked or retention-expired)",
                message_id
            )));
        }
        // Keeps the "not found on any server" marker that worker::fetch_segment
        // matches via is_article_missing().
        Err(AppError::Nntp(format!(
            "Article {} not found on any server: {}",
            message_id,
            last_err.map(|e| e.to_string()).unwrap_or_default()
        )))
    }

    /// Fetch a batch of articles using pipelining on a single connection.
    /// Returns results in the same order as `message_ids`.
    /// `publish_date` is used for retention checks.
    pub async fn fetch_pipelined_batch(
        &self,
        message_ids: &[String],
        groups: &[String],
        publish_date: Option<DateTime<Utc>>,
    ) -> Vec<(String, Result<Vec<u8>, AppError>)> {
        // Pipeline against the highest-priority server that is available and
        // within retention. If that wholesale attempt fails, fall through to
        // the robust per-article path (which handles failover + penalties).
        if let Some((pool, _cfg)) = self
            .ordered_servers()
            .into_iter()
            .find(|(pool, cfg)| !server_expired(cfg, publish_date) && pool.available())
        {
            if let Ok(results) = self
                .try_fetch_pipelined_with_group(pool, message_ids, groups)
                .await
            {
                return results;
            }
        }

        // Fall back to per-article fetch (handles per-article failover logic)
        let mut results = Vec::with_capacity(message_ids.len());
        for mid in message_ids {
            let body = self.fetch_article(mid, groups, publish_date).await;
            results.push((mid.clone(), body));
        }
        results
    }

    /// Pipeline fetch from a specific pool.
    async fn try_fetch_pipelined_with_group(
        &self,
        pool: &SingleServerPool,
        message_ids: &[String],
        groups: &[String],
    ) -> Result<Vec<(String, Result<Vec<u8>, AppError>)>, AppError> {
        let mut guard = pool.acquire().await?;

        if !groups.is_empty() {
            if let Err(e) = guard.client_mut().group(&groups[0]).await {
                debug!("GROUP command failed (non-fatal): {}", e);
            }
        }

        match guard.client_mut().fetch_pipelined(message_ids).await {
            Ok(results) => {
                guard.release().await;
                pool.note_success();
                Ok(results)
            }
            Err(e) => {
                guard.discard();
                pool.penalize(&e.to_string());
                Err(e)
            }
        }
    }

    /// Fetch from a specific server pool, sending GROUP command first if needed.
    async fn try_fetch_with_group(
        &self,
        pool: &SingleServerPool,
        message_id: &str,
        groups: &[String],
    ) -> Result<Vec<u8>, AppError> {
        let mut guard = pool.acquire().await?;

        // Send GROUP command — some servers require it before BODY works
        if !groups.is_empty() {
            if let Err(e) = guard.client_mut().group(&groups[0]).await {
                debug!("GROUP command failed (non-fatal): {}", e);
            }
        }

        match guard.client_mut().body(message_id).await {
            Ok(body) => {
                guard.release().await;
                pool.note_success();
                Ok(body)
            }
            Err(e) => {
                guard.discard();
                // Article-missing (430 etc.) classifies as ArticleLevel and
                // does NOT block the server; connection-level errors do.
                pool.penalize(&e.to_string());
                Err(e)
            }
        }
    }

    pub async fn prewarm(&self) {
        self.primary.prewarm().await;
        for (i, backup) in self.backups.iter().enumerate() {
            info!("Pre-warming backup server {}", i + 1);
            backup.prewarm().await;
        }
    }

    pub async fn keepalive_all(&self) {
        self.primary.keepalive_all().await;
        for backup in &self.backups {
            backup.keepalive_all().await;
        }
    }
}

pub struct NntpPoolGuard<'a> {
    client: Option<NntpClient>,
    pool_conns: &'a tokio::sync::Mutex<Vec<NntpClient>>,
    _permit: tokio::sync::SemaphorePermit<'a>,
}

impl<'a> NntpPoolGuard<'a> {
    pub fn client_mut(&mut self) -> &mut NntpClient {
        self.client.as_mut().unwrap()
    }

    /// Return the connection to the pool explicitly (before drop).
    pub async fn release(mut self) {
        if let Some(client) = self.client.take() {
            let mut conns = self.pool_conns.lock().await;
            conns.push(client);
        }
    }

    /// Discard the connection (don't return to pool). Use after errors.
    pub fn discard(mut self) {
        self.client.take(); // Drop the client without returning to pool
    }
}

impl<'a> Drop for NntpPoolGuard<'a> {
    fn drop(&mut self) {
        if let Some(client) = self.client.take() {
            if let Ok(mut conns) = self.pool_conns.try_lock() {
                conns.push(client);
            }
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cfg(optional: bool) -> UsenetConfig {
        UsenetConfig {
            host: "news.example.com".into(),
            port: 563,
            tls: true,
            username: "u".into(),
            password: "p".into(),
            connections: 10,
            retention_days: 0,
            priority: 0,
            optional,
        }
    }

    #[test]
    fn nntp_code_ignores_message_ids() {
        assert_eq!(nntp_code("Authentication failed: 481 No permission"), Some(481));
        assert_eq!(nntp_code("BODY failed for <abc123@host>: 430 no such article"), Some(430));
        // Digits inside a message-id must not be picked up as a status code.
        assert_eq!(nntp_code("BODY failed for <451999@x>: 222 ok"), Some(222));
        assert_eq!(nntp_code("Failed to connect to host:563: refused"), None);
    }

    #[test]
    fn classify_distinguishes_article_from_server_errors() {
        assert!(matches!(
            classify_error("BODY failed for <x@y>: 430 no such article"),
            Penalty::ArticleLevel
        ));
        assert!(matches!(
            classify_error("Authentication failed: 481 bad user"),
            Penalty::Deactivate(_)
        ));
        assert!(matches!(
            classify_error("Failed to connect to news.x:563: connection refused"),
            Penalty::Block(d) if d == PENALTY_TIMEOUT
        ));
        assert!(matches!(
            classify_error("BODY failed for <x@y>: 502 too many connections"),
            Penalty::Block(d) if d == PENALTY_TOOMANY
        ));
        assert!(matches!(
            classify_error("Read timeout"),
            Penalty::Transient
        ));
    }

    #[test]
    fn block_makes_server_unavailable_then_auto_resumes() {
        let pool = SingleServerPool::new(cfg(false), Duration::from_secs(1));
        assert!(pool.available());

        // A short block makes it unavailable...
        pool.block_for(Duration::from_millis(60), false, "boom");
        assert!(!pool.available());

        // ...and it auto-resumes once the window elapses, clearing bad_cons.
        pool.bad_cons.store(5, Ordering::Relaxed);
        std::thread::sleep(Duration::from_millis(80));
        assert!(pool.available());
        assert_eq!(pool.bad_cons.load(Ordering::Relaxed), 0);
    }

    #[test]
    fn missing_articles_never_block_the_server() {
        let pool = SingleServerPool::new(cfg(true), Duration::from_secs(1));
        for _ in 0..100 {
            pool.penalize("BODY failed for <x@y>: 430 no such article");
        }
        assert!(pool.available(), "article-missing must not block the server");
    }

    #[test]
    fn optional_server_deactivates_after_enough_transient_failures() {
        let pool = SingleServerPool::new(cfg(true), Duration::from_secs(1));
        // threshold = ceil(connections * 0.3) = ceil(10 * 0.3) = 3
        pool.penalize("Read timeout");
        pool.penalize("Read timeout");
        assert!(pool.available());
        pool.penalize("Read timeout");
        assert!(!pool.available(), "optional server should block at 30% bad");
    }
}
