use crate::config::SpotifyConfig;
use crate::db::Database;
use crate::models::job::{JobStatus, QueueEntry};
use crate::queue::priority_queue::PriorityQueue;
use crate::webhooks::client::{WebhookClient, WebhookEvent, WebhookPayload};
use chrono::Utc;
use librespot_core::{
    authentication::Credentials,
    cache::Cache,
    config::SessionConfig,
    session::Session,
    SpotifyUri,
};
use librespot_oauth::OAuthClientBuilder;
use librespot_playback::{
    audio_backend::{Sink, SinkError, SinkResult},
    config::{Bitrate, PlayerConfig},
    convert::Converter,
    decoder::AudioPacket,
    mixer::NoOpVolume,
    player::{Player, PlayerEvent},
};
use std::fs::{self, File};
use std::io::Write;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::{info, warn};
use uuid::Uuid;

const CLIENT_ID: &str = "65b708073fc0480ea92a077233ca87bd";
const REDIRECT_URI: &str = "http://127.0.0.1:8898/login";
const SCOPES: &[&str] = &[
    "streaming",
    "user-read-playback-state",
    "user-modify-playback-state",
    "user-read-currently-playing",
];

struct FileSink {
    file: File,
}

impl Sink for FileSink {
    fn write(&mut self, packet: AudioPacket, _converter: &mut Converter) -> SinkResult<()> {
        match packet {
            AudioPacket::Raw(data) => self
                .file
                .write_all(&data)
                .map_err(|e| SinkError::OnWrite(e.to_string())),
            AudioPacket::Samples(_) => Ok(()),
        }
    }
}

pub async fn authenticate(config: &SpotifyConfig) -> Session {
    let cache = build_cache(config);

    let credentials = if let Some(cached) = cache.credentials() {
        info!("Using cached credentials");
        cached
    } else {
        info!("No cached credentials — starting OAuth login on port 8898");
        let token = tokio::task::spawn_blocking(|| {
            OAuthClientBuilder::new(CLIENT_ID, REDIRECT_URI, SCOPES.to_vec())
                .build()
                .expect("Failed to build OAuth client")
                .get_access_token()
                .expect("OAuth login failed")
        })
        .await
        .expect("OAuth task panicked");
        Credentials::with_access_token(&token.access_token)
    };

    connect_session(cache, credentials)
        .await
        .expect("Failed to connect to Spotify on initial start-up")
}

fn build_cache(config: &SpotifyConfig) -> Cache {
    Cache::new(
        Some(&config.config_dir),
        None::<&String>,
        None::<&String>,
        None,
    )
    .expect("Failed to create Spotify cache")
}

async fn connect_session(cache: Cache, credentials: Credentials) -> Result<Session, String> {
    let session = Session::new(SessionConfig::default(), Some(cache));
    info!("Connecting to Spotify…");
    session
        .connect(credentials, true)
        .await
        .map_err(|e| format!("Failed to connect to Spotify: {e}"))?;
    info!("Connected");
    Ok(session)
}

/// Re-establish a working Spotify session **without** the interactive OAuth
/// flow.  Reads the persisted refresh credentials from the cache (these
/// survive the in-memory session going stale) and reconnects.
///
/// This is the recovery path that historically required a full container
/// restart: the in-memory `Session` would die (TLS reset, server kicked us,
/// long idle), but the cached refresh token was still perfectly valid.
pub async fn refresh_session(config: &SpotifyConfig) -> Result<Session, String> {
    let cache = build_cache(config);
    let credentials = cache
        .credentials()
        .ok_or_else(|| "No cached credentials available for refresh".to_string())?;
    connect_session(cache, credentials).await
}

/// Returns a healthy session, reconnecting transparently if the current one
/// has been invalidated by librespot (server-initiated disconnect, idle
/// timeout, etc.).  All callers go through this helper so there is a single
/// recovery path.
pub async fn ensure_session(
    session_lock: &RwLock<Option<Session>>,
    config: &SpotifyConfig,
) -> Result<Session, String> {
    {
        let guard = session_lock.read().await;
        if let Some(session) = guard.as_ref() {
            if !session.is_invalid() {
                return Ok(session.clone());
            }
        }
    }

    // Acquire the write lock and re-check: another task may have refreshed.
    let mut guard = session_lock.write().await;
    if let Some(session) = guard.as_ref() {
        if !session.is_invalid() {
            return Ok(session.clone());
        }
        warn!("Spotify session invalid — reconnecting from cached credentials");
        session.shutdown();
    } else {
        warn!("No active Spotify session — reconnecting from cached credentials");
    }

    let session = refresh_session(config).await?;
    *guard = Some(session.clone());
    Ok(session)
}

pub struct DownloadResult {
    pub path: String,
    pub file_size: i64,
}

pub async fn download_track(
    session: &Session,
    output_dir: &PathBuf,
    uri_str: &str,
    bitrate: Bitrate,
) -> Result<DownloadResult, String> {
    let spotify_uri = SpotifyUri::from_uri(uri_str).map_err(|e| e.to_string())?;
    let track_id = spotify_uri.to_id().map_err(|e| e.to_string())?;
    let output_path = output_dir.join(format!("{track_id}.ogg"));

    if output_path.exists() {
        let file_size = fs::metadata(&output_path).map(|m| m.len() as i64).unwrap_or(0);
        return Ok(DownloadResult {
            path: output_path.to_string_lossy().into_owned(),
            file_size,
        });
    }

    let file = File::create(&output_path).map_err(|e| e.to_string())?;

    let player_config = PlayerConfig {
        bitrate,
        passthrough: true,
        ..Default::default()
    };

    let player = Player::new(
        player_config,
        session.clone(),
        Box::new(NoOpVolume),
        move || Box::new(FileSink { file }),
    );

    let mut events = player.get_player_event_channel();
    player.load(spotify_uri, true, 0);

    let result = loop {
        match events.recv().await {
            Some(PlayerEvent::EndOfTrack { .. }) => break Ok(()),
            Some(PlayerEvent::Unavailable { .. }) => {
                break Err(format!("Track {track_id} is unavailable"))
            }
            None => break Ok(()),
            _ => {}
        }
    };

    if result.is_err() {
        let _ = fs::remove_file(&output_path);
    }

    result?;
    let file_size = fs::metadata(&output_path).map(|m| m.len() as i64).unwrap_or(0);
    Ok(DownloadResult {
        path: output_path.to_string_lossy().into_owned(),
        file_size,
    })
}

/// Parses a track_id input (URI, URL, or bare ID) into a spotify:track:... URI string.
pub fn normalize_track_id(input: &str) -> Result<(String, String), String> {
    let uri_str = if input.starts_with("spotify:") {
        input.to_string()
    } else if input.starts_with("https://open.spotify.com/track/") {
        let path = input.trim_start_matches("https://open.spotify.com/track/");
        let id = path.split(['?', '/']).next().unwrap_or(path);
        format!("spotify:track:{id}")
    } else {
        format!("spotify:track:{}", input)
    };

    let spotify_uri =
        SpotifyUri::from_uri(&uri_str).map_err(|e| format!("Invalid track id: {e}"))?;
    let track_id = spotify_uri.to_id().map_err(|e| e.to_string())?;

    Ok((uri_str, track_id))
}

pub struct DownloadWorker {
    session_lock: Arc<RwLock<Option<Session>>>,
    config: SpotifyConfig,
    output_dir: PathBuf,
    default_bitrate: Bitrate,
    db: Arc<Database>,
    queue: Arc<PriorityQueue>,
    webhook_client: Arc<WebhookClient>,
}

impl DownloadWorker {
    pub fn new(
        session_lock: Arc<RwLock<Option<Session>>>,
        config: SpotifyConfig,
        output_dir: PathBuf,
        default_bitrate: Bitrate,
        db: Arc<Database>,
        queue: Arc<PriorityQueue>,
        webhook_client: Arc<WebhookClient>,
    ) -> Self {
        Self {
            session_lock,
            config,
            output_dir,
            default_bitrate,
            db,
            queue,
            webhook_client,
        }
    }

    pub async fn run(&self) {
        // Re-queue pending jobs from database on startup
        let pending = self.db.load_pending_jobs();
        for job in &pending {
            info!("Re-queuing job {} from database", job.id);
            self.queue.push(QueueEntry {
                job_id: job.id,
                priority: job.priority,
                created_at: job.created_at,
            });
        }
        if !pending.is_empty() {
            info!("Re-queued {} pending jobs from database", pending.len());
        }

        info!("Worker ready");

        loop {
            let entry = self.queue.pop_wait().await;
            self.process_job(entry.job_id).await;
        }
    }

    /// Mark the shared session as invalid so the next caller reconnects.
    /// We do not assume which kind of error means "auth dead", so any
    /// download failure forces a re-check on the next attempt; a still-
    /// healthy session passes the `is_invalid()` check unchanged.
    async fn invalidate_session(&self) {
        let guard = self.session_lock.read().await;
        if let Some(session) = guard.as_ref() {
            session.shutdown();
        }
    }

    async fn try_download(&self, uri_str: &str) -> Result<DownloadResult, String> {
        let session = ensure_session(&self.session_lock, &self.config).await?;
        download_track(&session, &self.output_dir, uri_str, self.default_bitrate).await
    }

    async fn process_job(&self, job_id: Uuid) {
        let mut job = match self.db.get_job(job_id) {
            Some(j) => j,
            None => return,
        };

        if job.status == JobStatus::Cancelled {
            return;
        }

        job.status = JobStatus::Downloading;
        job.started_at = Some(Utc::now());
        self.db.update_job(&job);

        let webhook_url = job
            .webhook_url
            .clone()
            .unwrap_or_else(|| self.webhook_client.default_url().to_string());

        info!("Processing job {job_id} (track {})", job.track_id);

        let uri_str = format!("spotify:track:{}", job.track_id);
        let mut result = self.try_download(&uri_str).await;

        // One automatic retry: most "stale session" symptoms surface as
        // a download failure on a session that *looks* alive but isn't.
        // Force a reconnect and try once more before giving up.
        if let Err(ref err) = result {
            warn!(
                "Job {job_id} failed on first attempt ({err}); invalidating session and retrying"
            );
            self.invalidate_session().await;
            result = self.try_download(&uri_str).await;
        }

        if let Some(mut job) = self.db.get_job(job_id) {
            job.completed_at = Some(Utc::now());
            match result {
                Ok(dl) => {
                    job.status = JobStatus::Completed;
                    job.progress = 100.0;
                    job.path = Some(dl.path.clone());
                    job.file_size = Some(dl.file_size);
                    self.db.update_job(&job);
                    info!("Job {job_id} completed");
                    // Report the downloader's own output base dir as `path`
                    // and the produced file's basename in `files`; the
                    // backend applies its single mount translation to `path`.
                    let file_name = std::path::Path::new(&dl.path)
                        .file_name()
                        .map(|n| n.to_string_lossy().into_owned());
                    let files = file_name.into_iter().collect::<Vec<_>>();
                    let output_base = Some(self.output_dir.to_string_lossy().into_owned());
                    self.send_webhook(
                        &webhook_url,
                        WebhookEvent::JobCompleted,
                        job_id,
                        &job.track_id,
                        &job.category,
                        &job.destination,
                        output_base,
                        files,
                        None,
                    )
                    .await;
                }
                Err(err) => {
                    job.status = JobStatus::Failed;
                    job.error = Some(err.clone());
                    self.db.update_job(&job);
                    info!("Job {job_id} failed: {err}");
                    self.send_webhook(
                        &webhook_url,
                        WebhookEvent::JobFailed,
                        job_id,
                        &job.track_id,
                        &job.category,
                        &job.destination,
                        None,
                        Vec::new(),
                        Some(err),
                    )
                    .await;
                }
            }
        }
    }

    #[allow(clippy::too_many_arguments)]
    async fn send_webhook(
        &self,
        url: &str,
        event: WebhookEvent,
        job_id: Uuid,
        name: &str,
        category: &Option<String>,
        destination: &Option<String>,
        path: Option<String>,
        files: Vec<String>,
        error: Option<String>,
    ) {
        if url.is_empty() {
            return;
        }

        self.webhook_client
            .send(
                url,
                &WebhookPayload {
                    id: job_id,
                    status: event.status_str(),
                    name: name.to_string(),
                    category: category.clone(),
                    destination: destination.clone(),
                    path,
                    error,
                    timestamp: Utc::now(),
                    files,
                },
            )
            .await;
    }
}
