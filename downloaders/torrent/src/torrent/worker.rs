use crate::config::Config;
use crate::db::Database;
use crate::models::job::JobStatus;
use crate::queue::priority_queue::PriorityQueue;
use crate::torrent::engine::{TorrentEngine, TorrentHandle};
use crate::webhooks::client::{WebhookClient, WebhookEvent, WebhookPayload};
use base64::Engine;
use chrono::Utc;
use std::path::{Component, Path, PathBuf};
use std::sync::Arc;
use tracing::{error, info, warn};
use uuid::Uuid;

/// Resolve a caller-supplied destination path against the configured download
/// root. Rejects absolute paths that escape the root and any traversal
/// segments. The downloader API has no auth right now, so this is the only
/// thing keeping a hostile caller from writing outside the bind mount.
fn sanitize_destination(root: &Path, requested: Option<&str>) -> Result<PathBuf, String> {
    let root_canonical = root
        .canonicalize()
        .unwrap_or_else(|_| root.to_path_buf());

    match requested {
        Some(s) if !s.is_empty() => {
            let p = Path::new(s);
            if p.is_absolute() {
                let abs_canonical = p.canonicalize().unwrap_or_else(|_| p.to_path_buf());
                if !abs_canonical.starts_with(&root_canonical) {
                    return Err(format!(
                        "destination {:?} escapes download root {:?}",
                        p, root_canonical
                    ));
                }
                Ok(abs_canonical)
            } else {
                for component in p.components() {
                    if matches!(
                        component,
                        Component::ParentDir | Component::RootDir | Component::Prefix(_)
                    ) {
                        return Err(format!("destination {:?} contains traversal components", p));
                    }
                }
                Ok(root_canonical.join(p))
            }
        }
        _ => Ok(root_canonical),
    }
}

pub struct DownloadWorker {
    config: Config,
    queue: Arc<PriorityQueue>,
    db: Arc<Database>,
    engine: Arc<TorrentEngine>,
    webhook_client: Arc<WebhookClient>,
}

impl DownloadWorker {
    pub fn new(
        config: Config,
        queue: Arc<PriorityQueue>,
        db: Arc<Database>,
        engine: Arc<TorrentEngine>,
        webhook_client: Arc<WebhookClient>,
    ) -> Self {
        Self {
            config,
            queue,
            db,
            engine,
            webhook_client,
        }
    }

    pub async fn run(self: Arc<Self>) {
        // Re-queue pending jobs from database on startup
        let pending = self.db.load_pending_jobs();
        for job in &pending {
            info!("Re-queuing job {} from database", job.id);
            self.queue.push(crate::models::job::QueueEntry {
                job_id: job.id,
                priority: job.priority,
                created_at: job.created_at,
            });
        }
        if !pending.is_empty() {
            info!("Re-queued {} pending jobs from database", pending.len());
        }

        let semaphore = Arc::new(tokio::sync::Semaphore::new(
            self.config.download.max_concurrent_jobs,
        ));

        loop {
            let entry = self.queue.pop_wait().await;
            let permit = semaphore.clone().acquire_owned().await.unwrap();
            let worker = self.clone();

            tokio::spawn(async move {
                worker.process_job(entry.job_id).await;
                drop(permit);
            });
        }
    }

    async fn process_job(&self, job_id: Uuid) {
        info!("Starting torrent download for job {}", job_id);

        let mut job = match self.db.get_job(job_id) {
            Some(j) => j,
            None => {
                warn!("Job {} not found, skipping", job_id);
                return;
            }
        };

        if job.status == JobStatus::Cancelled {
            return;
        }

        // Mark as downloading
        job.status = JobStatus::Downloading;
        job.started_at = Some(Utc::now());
        self.db.update_job(&job);

        let webhook_url = job
            .webhook_url
            .clone()
            .unwrap_or_else(|| self.webhook_client.default_url().to_string());

        let dest_dir = match sanitize_destination(
            &self.config.download.directory,
            job.destination.as_deref(),
        ) {
            Ok(p) => p,
            Err(e) => {
                self.fail_job(job_id, &format!("Invalid destination: {}", e), &webhook_url)
                    .await;
                return;
            }
        };

        // Add torrent to engine
        let handle = if let Some(ref magnet) = job.magnet_uri {
            self.engine.add_magnet(magnet, Some(dest_dir)).await
        } else if let Some(ref content) = job.torrent_content {
            let bytes = match base64::engine::general_purpose::STANDARD.decode(content) {
                Ok(b) => b,
                Err(e) => {
                    self.fail_job(job_id, &format!("Invalid base64 torrent content: {}", e), &webhook_url)
                        .await;
                    return;
                }
            };
            self.engine.add_torrent_bytes(&bytes, Some(dest_dir)).await
        } else {
            self.fail_job(job_id, "No torrent source (magnet or file) found", &webhook_url)
                .await;
            return;
        };

        let handle = match handle {
            Ok(h) => h,
            Err(e) => {
                self.fail_job(job_id, &format!("Failed to add torrent: {}", e), &webhook_url)
                    .await;
                return;
            }
        };

        // Poll status until complete
        self.monitor_torrent(job_id, &handle, &webhook_url).await;
    }

    async fn monitor_torrent(&self, job_id: Uuid, handle: &TorrentHandle, webhook_url: &str) {
        loop {
            tokio::time::sleep(tokio::time::Duration::from_secs(1)).await;

            // Check if cancelled
            if let Some(job) = self.db.get_job(job_id) {
                if job.status == JobStatus::Cancelled {
                    let _ = self.engine.cancel(handle).await;
                    return;
                }
            } else {
                let _ = self.engine.cancel(handle).await;
                return;
            }

            let status = match self.engine.get_status(handle) {
                Ok(s) => s,
                Err(e) => {
                    self.fail_job(job_id, &format!("Engine status error: {}", e), webhook_url)
                        .await;
                    return;
                }
            };

            if let Some(ref err) = status.error {
                self.fail_job(job_id, err, webhook_url).await;
                let _ = self.engine.cancel(handle).await;
                return;
            }

            // Update job in database
            if let Some(mut job) = self.db.get_job(job_id) {
                job.progress = status.progress;
                job.total_bytes = status.total_bytes;
                job.downloaded_bytes = status.downloaded_bytes;
                job.uploaded_bytes = status.uploaded_bytes;
                job.download_speed = status.download_speed;
                job.upload_speed = status.upload_speed;
                job.peers_connected = status.peers_connected;
                job.seeds_connected = status.seeds_connected;

                if status.finished && job.status == JobStatus::Downloading {
                    let seed_ratio = self.config.torrent.seed_ratio;
                    if seed_ratio > 0.0 {
                        job.status = JobStatus::Seeding;
                    } else {
                        job.status = JobStatus::Completed;
                        job.completed_at = Some(Utc::now());
                        job.progress = 100.0;
                    }
                }

                // Check seed ratio
                if job.status == JobStatus::Seeding && status.total_bytes > 0 {
                    let ratio =
                        status.uploaded_bytes as f64 / status.total_bytes as f64;
                    if ratio >= self.config.torrent.seed_ratio {
                        job.status = JobStatus::Completed;
                        job.completed_at = Some(Utc::now());
                    }
                }

                self.db.update_job(&job);

                if job.status == JobStatus::Completed {
                    let _ = self.engine.cancel(handle).await;

                    let dest_dir = sanitize_destination(
                        &self.config.download.directory,
                        job.destination.as_deref(),
                    )
                    .ok();
                    if let Some(dir) = dest_dir {
                        if let Err(e) = Self::extract_archives(&dir).await {
                            warn!("Job {} archive extraction failed: {}", job_id, e);
                        }
                    }

                    info!("Job {} completed successfully", job_id);
                    self.send_webhook(
                        webhook_url,
                        WebhookEvent::JobCompleted,
                        job_id,
                        &job.name,
                        &job.category,
                        &job.destination,
                        None,
                    )
                    .await;
                    return;
                }
            }
        }
    }

    async fn fail_job(&self, job_id: Uuid, error_msg: &str, webhook_url: &str) {
        error!("Job {} failed: {}", job_id, error_msg);

        let (name, category, destination) = {
            if let Some(mut job) = self.db.get_job(job_id) {
                job.status = JobStatus::Failed;
                job.error = Some(error_msg.to_string());
                job.completed_at = Some(Utc::now());
                self.db.update_job(&job);
                (job.name, job.category, job.destination)
            } else {
                return;
            }
        };

        self.send_webhook(
            webhook_url,
            WebhookEvent::JobFailed,
            job_id,
            &name,
            &category,
            &destination,
            Some(error_msg.to_string()),
        )
        .await;
    }

    /// Walk `dir` up to two levels deep and extract any .zip/.rar archives in
    /// place via `7z`. Archives are removed after successful extraction so the
    /// importer only sees the unpacked files.
    async fn extract_archives(dir: &Path) -> Result<(), String> {
        let archives = Self::find_archives(dir, 2).await;
        if archives.is_empty() {
            return Ok(());
        }

        for archive in archives {
            let parent = match archive.parent() {
                Some(p) => p.to_path_buf(),
                None => continue,
            };
            info!("Extracting archive: {}", archive.display());
            let mut cmd = tokio::process::Command::new("7z");
            cmd.args(["x", "-y", "-bd"]);
            cmd.arg(format!("-o{}", parent.display()));
            cmd.arg(&archive);
            let output = cmd
                .output()
                .await
                .map_err(|e| format!("Failed to execute 7z: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                return Err(format!(
                    "Extraction of {} failed: {} {}",
                    archive.display(),
                    stdout.trim(),
                    stderr.trim()
                ));
            }

            let _ = tokio::fs::remove_file(&archive).await;
        }

        Ok(())
    }

    async fn find_archives(dir: &Path, depth: usize) -> Vec<PathBuf> {
        let mut found = Vec::new();
        let Ok(mut read_dir) = tokio::fs::read_dir(dir).await else {
            return found;
        };
        while let Ok(Some(entry)) = read_dir.next_entry().await {
            let path = entry.path();
            let file_type = match entry.file_type().await {
                Ok(t) => t,
                Err(_) => continue,
            };
            if file_type.is_file() {
                let lower = entry.file_name().to_string_lossy().to_lowercase();
                if lower.ends_with(".zip") || lower.ends_with(".rar") {
                    found.push(path);
                }
            } else if file_type.is_dir() && depth > 0 {
                let nested = Box::pin(Self::find_archives(&path, depth - 1)).await;
                found.extend(nested);
            }
        }
        found
    }

    async fn send_webhook(
        &self,
        url: &str,
        event: WebhookEvent,
        job_id: Uuid,
        name: &str,
        category: &Option<String>,
        destination: &Option<String>,
        error: Option<String>,
    ) {
        if url.is_empty() {
            return;
        }

        self.webhook_client
            .send(
                url,
                &WebhookPayload {
                    event,
                    job_id,
                    name: name.to_string(),
                    category: category.clone(),
                    destination: destination.clone(),
                    error,
                    timestamp: Utc::now(),
                },
            )
            .await;
    }
}
