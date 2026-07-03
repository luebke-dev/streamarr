use crate::config::Config;
use crate::db::Database;
use crate::downloader::cache::ArticleCache;
use crate::downloader::control::DownloadControl;
use crate::downloader::decoder::{decode_yenc, is_dmca_content};
use crate::downloader::nntp_client::{is_article_missing, NntpPool};
use crate::downloader::nzb_parser::parse_nzb;
use crate::downloader::par2file::{
    classify_par2_output, recovery_blocks_in_volume, Par2Outcome,
};
use crate::models::job::{Job, JobStatus};
use crate::queue::priority_queue::PriorityQueue;
use crate::webhooks::client::{WebhookClient, WebhookEvent, WebhookPayload};
use chrono::{DateTime, Utc};
use rand::Rng;
use std::collections::HashMap;
use std::path::{Component, Path, PathBuf};
use std::sync::atomic::{AtomicU64, AtomicUsize, Ordering};
use std::sync::Arc;
use std::time::Duration;
use tokio::io::AsyncWriteExt;
use tokio::sync::RwLock;
use tracing::{error, info, warn};
use uuid::Uuid;

/// Resolve a caller-supplied destination path against the configured download
/// root. Rejects absolute paths, traversal segments, and anything that resolves
/// outside the root. The API has no auth right now, so callers can ask for any
/// path; this keeps writes inside the bind-mounted volume.
fn sanitize_destination(root: &Path, requested: Option<&str>, fallback_name: &str) -> Result<PathBuf, String> {
    let root_canonical = root
        .canonicalize()
        .unwrap_or_else(|_| root.to_path_buf());

    let candidate = match requested {
        Some(s) if !s.is_empty() => {
            let p = Path::new(s);
            if p.is_absolute() {
                let abs_canonical = p
                    .canonicalize()
                    .unwrap_or_else(|_| p.to_path_buf());
                if !abs_canonical.starts_with(&root_canonical) {
                    return Err(format!(
                        "destination {:?} escapes download root {:?}",
                        p, root_canonical
                    ));
                }
                abs_canonical
            } else {
                for component in p.components() {
                    if matches!(component, Component::ParentDir | Component::RootDir | Component::Prefix(_)) {
                        return Err(format!("destination {:?} contains traversal components", p));
                    }
                }
                root_canonical.join(p)
            }
        }
        _ => root_canonical.join(fallback_name),
    };

    Ok(candidate)
}

pub type JobStore = Arc<RwLock<HashMap<Uuid, Job>>>;

pub struct DownloadWorker {
    config: Config,
    queue: Arc<PriorityQueue>,
    jobs: JobStore,
    db: Arc<Database>,
    nntp_pool: Arc<NntpPool>,
    webhook_client: Arc<WebhookClient>,
    article_cache: ArticleCache,
    control: Arc<DownloadControl>,
}

impl DownloadWorker {
    pub fn new(
        config: Config,
        queue: Arc<PriorityQueue>,
        jobs: JobStore,
        db: Arc<Database>,
        webhook_client: Arc<WebhookClient>,
        control: Arc<DownloadControl>,
    ) -> Self {
        let timeout = Duration::from_secs(config.nntp.timeout_secs);
        let pipeline_depth = config.nntp.pipeline_requests;
        let nntp_pool = Arc::new(if config.backup_servers.is_empty() {
            NntpPool::new(config.usenet.clone(), timeout)
                .with_pipeline_depth(pipeline_depth)
        } else {
            info!("Configured {} backup server(s)", config.backup_servers.len());
            NntpPool::with_backups(config.usenet.clone(), config.backup_servers.clone(), timeout)
                .with_pipeline_depth(pipeline_depth)
        });
        let article_cache = ArticleCache::new(config.download.article_cache_mb * 1024 * 1024);
        Self {
            config,
            queue,
            jobs,
            db,
            nntp_pool,
            webhook_client,
            article_cache,
            control,
        }
    }

    pub async fn run(self: Arc<Self>) {
        let semaphore = Arc::new(tokio::sync::Semaphore::new(
            self.config.download.max_concurrent_jobs,
        ));

        self.nntp_pool.prewarm().await;

        let pool = self.nntp_pool.clone();
        let _keepalive_handle = tokio::spawn(async move {
            loop {
                tokio::time::sleep(Duration::from_secs(60)).await;
                pool.keepalive_all().await;
            }
        });

        loop {
            // Don't start new jobs while globally paused (queued jobs wait).
            self.control.wait_if_paused().await;
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
        info!("Starting download for job {}", job_id);

        if self.config.download.propagation_delay_secs > 0 {
            info!("Job {} waiting {}s for propagation", job_id, self.config.download.propagation_delay_secs);
            tokio::time::sleep(Duration::from_secs(self.config.download.propagation_delay_secs)).await;
        }

        let (nzb_content, raw_destination, webhook_url, job_name) = {
            let mut jobs = self.jobs.write().await;
            let job = match jobs.get_mut(&job_id) {
                Some(j) => j,
                None => {
                    warn!("Job {} not found in memory, attempting webhook from DB record", job_id);
                    drop(jobs);
                    if let Some(db_job) = self.db.get_job(&job_id).ok().flatten() {
                        let url = db_job.webhook_url.clone()
                            .unwrap_or_else(|| self.webhook_client.default_url().to_string());
                        self.fail_job(job_id, "Job dropped from in-memory queue", &url).await;
                    }
                    return;
                }
            };
            if job.status == JobStatus::Cancelled { return; }
            job.status = JobStatus::Downloading;
            job.started_at = Some(Utc::now());
            let _ = self.db.update_job_status(&job_id, &JobStatus::Downloading, None, job.started_at, None);
            let webhook = job.webhook_url.clone()
                .unwrap_or_else(|| self.webhook_client.default_url().to_string());
            (job.nzb_content.clone(), job.destination.clone(), webhook, job.name.clone())
        };

        let dest_dir = match sanitize_destination(
            &self.config.download.directory,
            raw_destination.as_deref(),
            &job_name,
        ) {
            Ok(p) => p.to_string_lossy().into_owned(),
            Err(e) => {
                self.fail_job(job_id, &format!("Invalid destination: {}", e), &webhook_url).await;
                return;
            }
        };

        let nzb = match parse_nzb(&nzb_content) {
            Ok(nzb) => nzb,
            Err(e) => { self.fail_job(job_id, &format!("NZB parse error: {}", e), &webhook_url).await; return; }
        };

        let publish_date: Option<DateTime<Utc>> = nzb.publish_date;

        // --- Pre-check: STAT a sample of segments to detect dead/DMCA'd releases ---
        // Collect all message IDs and groups from the first data file for sampling.
        let (precheck_ids, precheck_groups) = {
            let data_files: Vec<_> = nzb.files.iter().filter(|f| !f.is_par2()).collect();
            let ids: Vec<String> = data_files.iter()
                .flat_map(|f| f.segments.iter().map(|s| s.message_id.clone()))
                .collect();
            let groups: Vec<String> = data_files.first()
                .map(|f| f.groups.clone())
                .unwrap_or_default();
            (ids, groups)
        };

        if !precheck_ids.is_empty() {
            match self.nntp_pool.pre_check(&precheck_ids, &precheck_groups).await {
                Ok((missing, sampled)) if sampled > 0 => {
                    let pct = (missing as f64 / sampled as f64) * 100.0;
                    if pct > 50.0 {
                        self.fail_job(
                            job_id,
                            &format!("Pre-check failed: {}/{} sampled articles missing ({:.0}%) — release is likely dead or DMCA'd", missing, sampled, pct),
                            &webhook_url,
                        ).await;
                        return;
                    }
                    if missing > 0 {
                        warn!("Job {}: pre-check found {}/{} missing articles ({:.0}%) — continuing with download", job_id, missing, sampled, pct);
                    } else {
                        info!("Job {}: pre-check passed ({} articles verified on server)", job_id, sampled);
                    }
                }
                Ok(_) => {}
                Err(e) => {
                    warn!("Job {}: pre-check error ({}), continuing anyway", job_id, e);
                }
            }
        }

        let total_bytes = nzb.total_bytes();
        { let mut jobs = self.jobs.write().await; if let Some(job) = jobs.get_mut(&job_id) { job.total_bytes = total_bytes; } }

        let dest_path = PathBuf::from(&dest_dir);
        let temp_path = self.config.download.temp_directory.join(job_id.to_string());

        if let Err(e) = tokio::fs::create_dir_all(&dest_path).await {
            self.fail_job(job_id, &format!("Cannot create dest dir: {}", e), &webhook_url).await; return;
        }
        if let Err(e) = tokio::fs::create_dir_all(&temp_path).await {
            self.fail_job(job_id, &format!("Cannot create temp dir: {}", e), &webhook_url).await; return;
        }

        let downloaded_bytes = Arc::new(AtomicU64::new(0));

        // Progress reporter
        let progress_jobs = self.jobs.clone();
        let progress_db = self.db.clone();
        let progress_counter = downloaded_bytes.clone();
        let progress_total = total_bytes;
        let progress_handle = tokio::spawn(async move {
            let mut db_tick = 0u32;
            let mut last_bytes = 0u64;
            // EWMA-smoothed speed so the UI number doesn't jitter every tick
            // (SABnzbd bpsmeter); resets to 0 while parked since bytes stall.
            let mut speed_ewma = 0.0f64;
            const TICK: f64 = 0.5;
            loop {
                tokio::time::sleep(Duration::from_millis(500)).await;
                let bytes = progress_counter.load(Ordering::Relaxed);
                let progress = if progress_total > 0 { (bytes as f64 / progress_total as f64) * 100.0 } else { 0.0 };
                let instant = ((bytes.saturating_sub(last_bytes)) as f64 / TICK).max(0.0);
                speed_ewma = 0.4 * instant + 0.6 * speed_ewma;
                last_bytes = bytes;
                let speed = speed_ewma as u64;
                let mut jobs = progress_jobs.write().await;
                if let Some(job) = jobs.get_mut(&job_id) {
                    job.downloaded_bytes = bytes;
                    job.progress = progress;
                    job.speed_bps = speed;
                    // Keep reporting through Paused so the UI shows the parked
                    // job; stop only on a terminal state.
                    if matches!(
                        job.status,
                        JobStatus::Completed | JobStatus::Failed | JobStatus::Cancelled
                    ) {
                        break;
                    }
                } else { break; }
                drop(jobs);
                db_tick += 1;
                if db_tick % 10 == 0 {
                    let _ = progress_db.update_job_progress(&job_id, progress, bytes, progress_total, speed);
                }
            }
        });

        let (essential_files, par2_volumes) = nzb.split_par2_volumes();
        let has_par2_files = nzb.has_par2();
        let nzb_password = nzb.password.clone();

        if !par2_volumes.is_empty() {
            info!("Job {}: {} essential files + {} PAR2 volumes (on-demand)", job_id, essential_files.len(), par2_volumes.len());
        }

        let total_failed = Arc::new(AtomicUsize::new(0));
        let perm_missing = Arc::new(AtomicUsize::new(0));

        // Count total RAR volumes for direct unpack tracking
        let total_rar_volumes: usize = essential_files.iter()
            .filter(|f| f.filename.to_lowercase().ends_with(".rar"))
            .count();
        let completed_rar_volumes = Arc::new(AtomicUsize::new(0));

        // Channel to notify when a RAR volume file is written
        let (rar_done_tx, mut rar_done_rx) = tokio::sync::mpsc::channel::<PathBuf>(total_rar_volumes.max(1));

        // Spawn Direct Unpack task — starts extracting as soon as part01 arrives.
        // unrar reads volumes sequentially and will block waiting for later parts
        // to appear on disk as they are downloaded.
        let unpack_temp = temp_path.clone();
        let unpack_password = nzb_password.clone();
        let unpack_handle = if self.config.download.direct_unpack && total_rar_volumes > 0 {
            Some(tokio::spawn(async move {
                // Wait until part01 (or the only .rar) arrives, then launch unrar.
                // unrar will block internally waiting for subsequent volumes.
                let mut first_rar: Option<PathBuf> = None;

                while let Some(path) = rar_done_rx.recv().await {
                    let name = path.file_name().unwrap_or_default().to_string_lossy().to_lowercase();
                    // Accept a plain .rar or a .part01/.part001 volume as the trigger
                    let is_first_volume = !name.contains(".part")
                        || name.contains(".part01.rar")
                        || name.contains(".part001.rar");
                    if is_first_volume && first_rar.is_none() {
                        first_rar = Some(path.clone());
                        // Start unrar now — it will block waiting for subsequent volumes
                        break;
                    }
                }

                // If we didn't receive the first volume via channel, scan the directory
                let rar_file = if let Some(f) = first_rar {
                    f
                } else {
                    match Self::find_first_rar(&unpack_temp).await {
                        Some(f) => f,
                        None => return Err("No RAR files found for extraction".to_string()),
                    }
                };

                info!("Direct Unpack: starting unrar on {} (remaining volumes download in parallel)", rar_file.display());

                let mut cmd = tokio::process::Command::new("unrar");
                cmd.args(["x", "-y", "-o+"]);
                if let Some(ref pw) = unpack_password {
                    cmd.arg(format!("-p{}", pw));
                } else {
                    cmd.arg("-p-");
                }
                cmd.arg(&rar_file);
                cmd.arg(format!("{}/", unpack_temp.display()));

                // Use a long timeout — unrar may block waiting for volumes to appear
                let output = tokio::time::timeout(
                    Duration::from_secs(3600),
                    cmd.output(),
                )
                .await
                .map_err(|_| "unrar timed out after 1 hour".to_string())?
                .map_err(|e| format!("Failed to execute unrar: {}", e))?;

                if !output.status.success() {
                    let stderr = String::from_utf8_lossy(&output.stderr);
                    let stdout = String::from_utf8_lossy(&output.stdout);
                    return Err(format!("RAR extraction failed: {} {}", stdout.trim(), stderr.trim()));
                }

                info!("Direct Unpack: extraction complete");

                // Clean up archive files
                Self::cleanup_archives(&unpack_temp).await;

                Ok(())
            }))
        } else {
            // No Direct Unpack — close the receiver so senders don't buffer forever.
            // The fallback `extract_archives` path runs after PAR2 repair completes.
            drop(rar_done_rx);
            None
        };

        // Files download in parallel. Peak RAM is now bounded by the global
        // ArticleCache budget (see downloader/cache.rs), so the old hard cap of
        // 10 concurrent files is no longer needed to prevent OOM — connection
        // count (NNTP pool) and the cache budget are the real limiters. Keep a
        // generous ceiling just to bound task/FD count on huge NZBs.
        let file_semaphore = Arc::new(tokio::sync::Semaphore::new(64));
        let mut file_handles = Vec::new();

        for file in &essential_files {
            let pool = self.nntp_pool.clone();
            let counter = downloaded_bytes.clone();
            let failed_counter = total_failed.clone();
            let missing_counter = perm_missing.clone();
            let file_path = temp_path.join(&file.filename);
            let segments = file.segments.clone();
            let groups = file.groups.clone();
            let jobs = self.jobs.clone();
            let jid = job_id;
            let is_rar = file.filename.to_lowercase().ends_with(".rar");
            let rar_tx = if is_rar { Some(rar_done_tx.clone()) } else { None };
            let rar_completed = completed_rar_volumes.clone();
            let pipeline_depth = self.config.nntp.pipeline_requests;
            let file_permit = file_semaphore.clone();
            let cache = self.article_cache.clone();
            let control = self.control.clone();

            let handle = tokio::spawn(async move {
                let _permit = file_permit.acquire().await
                    .map_err(|e| format!("File semaphore error: {}", e))?;
                {
                    let jobs = jobs.read().await;
                    if let Some(job) = jobs.get(&jid) {
                        if job.status == JobStatus::Cancelled { return Err("Cancelled".to_string()); }
                    }
                }

                if let Some(parent) = file_path.parent() {
                    let _ = tokio::fs::create_dir_all(parent).await;
                }

                // Streaming assembler: segments arrive sorted ascending
                // (nzb_parser sorts them) and each batch is written straight
                // to the file in order, then dropped — a file never holds more
                // than one batch in RAM (vs. the old whole-file BTreeMap that
                // used ~7 GB on big releases). Byte output is identical: failed
                // segments are skipped, the rest concatenated in order.
                let mut writer: Option<tokio::fs::File> = None;
                let mut file_failed = 0usize;

                // Effective batch: pipeline depth when pipelining, otherwise a
                // fixed window so the sequential path is memory-bounded too
                // instead of fetching every segment of the file at once.
                let batch_size = if pipeline_depth > 1 { pipeline_depth } else { 30 };

                for chunk in segments.chunks(batch_size) {
                    // Pause/cancel checkpoint at each batch boundary. Parks
                    // here (no pool connections held between batches) while
                    // the job or whole downloader is paused.
                    if Self::paused_or_cancelled(&control, &jobs, jid).await {
                        return Err("Cancelled".to_string());
                    }
                    // Reserve the RAM budget for this batch before fetching.
                    // Blocks here when the network is ahead of the disk writer,
                    // capping total in-flight decoded data across all jobs.
                    let chunk_bytes: usize = chunk.iter().map(|s| s.bytes as usize).sum();
                    let _reservation = cache.reserve(chunk_bytes).await;

                    if pipeline_depth > 1 && segments.len() > 1 {
                        let mids: Vec<String> = chunk.iter().map(|s| s.message_id.clone()).collect();
                        let results = pool.fetch_pipelined_batch(&mids, &groups, publish_date).await;
                        for (seg, (_, result)) in chunk.iter().zip(results.into_iter()) {
                            let data = match result {
                                Ok(raw_body) => {
                                    if is_dmca_content(&raw_body) {
                                        missing_counter.fetch_add(1, Ordering::Relaxed);
                                        failed_counter.fetch_add(1, Ordering::Relaxed);
                                        file_failed += 1;
                                        warn!("DMCA/takedown detected for segment {}", seg.number);
                                        None
                                    } else {
                                        match decode_yenc(&raw_body) {
                                            Ok(decoded) => {
                                                counter.fetch_add(decoded.data.len() as u64, Ordering::Relaxed);
                                                Some(decoded.data)
                                            }
                                            Err(e) => {
                                                match Self::fetch_segment(pool.clone(), seg.message_id.clone(), seg.number, counter.clone(), groups.clone(), publish_date).await {
                                                    Ok((_n, d)) => Some(d),
                                                    Err(e2) => {
                                                        if e2.starts_with("MISSING:") { missing_counter.fetch_add(1, Ordering::Relaxed); }
                                                        failed_counter.fetch_add(1, Ordering::Relaxed);
                                                        file_failed += 1;
                                                        warn!("Segment {} fallback failed: {} / {}", seg.number, e, e2);
                                                        None
                                                    }
                                                }
                                            }
                                        }
                                    }
                                }
                                Err(e) => {
                                    let err_str = e.to_string();
                                    if is_article_missing(&err_str) {
                                        match Self::fetch_segment(pool.clone(), seg.message_id.clone(), seg.number, counter.clone(), groups.clone(), publish_date).await {
                                            Ok((_n, d)) => Some(d),
                                            Err(e2) => {
                                                if e2.starts_with("MISSING:") { missing_counter.fetch_add(1, Ordering::Relaxed); }
                                                failed_counter.fetch_add(1, Ordering::Relaxed);
                                                file_failed += 1;
                                                warn!("Segment {} retry failed: {}", seg.number, e2);
                                                None
                                            }
                                        }
                                    } else {
                                        failed_counter.fetch_add(1, Ordering::Relaxed);
                                        file_failed += 1;
                                        warn!("Pipelined segment {} failed: {}", seg.number, e);
                                        None
                                    }
                                }
                            };
                            if let Some(data) = data {
                                Self::write_segment(&mut writer, &file_path, &data).await?;
                                control.throttle(data.len() as u64).await;
                            }
                        }
                    } else {
                        // Sequential window: fetch the batch concurrently, then
                        // write results in segment order (push order == sorted).
                        let mut seg_handles = Vec::with_capacity(chunk.len());
                        for segment in chunk {
                            let p = pool.clone();
                            let mid = segment.message_id.clone();
                            let sn = segment.number;
                            let ctr = counter.clone();
                            let grps = groups.clone();
                            seg_handles.push(tokio::spawn(async move {
                                Self::fetch_segment(p, mid, sn, ctr, grps, publish_date).await
                            }));
                        }
                        for handle in seg_handles {
                            let data = match handle.await {
                                Ok(Ok((_num, d))) => Some(d),
                                Ok(Err(e)) => {
                                    if e.starts_with("MISSING:") { missing_counter.fetch_add(1, Ordering::Relaxed); }
                                    failed_counter.fetch_add(1, Ordering::Relaxed);
                                    file_failed += 1;
                                    warn!("Segment failed: {}", e);
                                    None
                                }
                                Err(e) => {
                                    failed_counter.fetch_add(1, Ordering::Relaxed);
                                    file_failed += 1;
                                    warn!("Segment task panicked: {}", e);
                                    None
                                }
                            };
                            if let Some(data) = data {
                                Self::write_segment(&mut writer, &file_path, &data).await?;
                                control.throttle(data.len() as u64).await;
                            }
                        }
                    }
                    // _reservation drops here → the next batch can only start
                    // fetching once this one has been written to disk.
                }

                if file_failed > 0 {
                    warn!("File {:?} had {}/{} failed segments",
                        file_path.file_name().unwrap_or_default(), file_failed, segments.len());
                }

                let mut writer = match writer {
                    Some(w) => w,
                    None => {
                        // No segment ever succeeded — nothing written, no stub
                        // left behind. Matches the old "skip file, let PAR2
                        // handle it" behavior.
                        if !segments.is_empty() {
                            warn!("Skipping file {:?} — all segments failed", file_path.file_name().unwrap_or_default());
                        }
                        return Ok(());
                    }
                };
                writer.flush().await
                    .map_err(|e| format!("Flush error {:?}: {}", file_path, e))?;
                drop(writer);

                info!("Written file: {}", file_path.display());

                // Notify Direct Unpack that this RAR volume is ready
                if is_rar {
                    rar_completed.fetch_add(1, Ordering::Relaxed);
                    if let Some(tx) = rar_tx {
                        let _ = tx.send(file_path).await;
                    }
                }

                Ok(())
            });
            file_handles.push(handle);
        }

        // Drop our sender so the unpack task's recv() will end when all senders drop
        drop(rar_done_tx);

        // Wait for all file downloads to complete
        for handle in file_handles {
            match handle.await {
                Ok(Ok(())) => {}
                Ok(Err(e)) => {
                    if e == "Cancelled" { progress_handle.abort(); return; }
                    progress_handle.abort();
                    if e.starts_with("DISKFULL:") {
                        self.pause_disk_full(job_id, &e).await;
                        return;
                    }
                    self.fail_job(job_id, &e, &webhook_url).await;
                    return;
                }
                Err(e) => {
                    progress_handle.abort();
                    self.fail_job(job_id, &format!("File task panicked: {}", e), &webhook_url).await;
                    return;
                }
            }
        }

        let total_failed_segments = total_failed.load(Ordering::Relaxed);
        let permanently_missing = perm_missing.load(Ordering::Relaxed);
        progress_handle.abort();

        // --- PAR2: only verify/repair if there were failed segments ---
        // When all CRC32 checks passed, skip PAR2 (like SABnzbd's quick-check)
        if total_failed_segments > 0 && has_par2_files {
            info!("Job {} had {} failed segments ({} missing), running PAR2",
                job_id, total_failed_segments, permanently_missing);
            if let Err(e) = self
                .par2_repair_with_volumes(&temp_path, &par2_volumes, publish_date)
                .await
            {
                self.fail_job(job_id, &format!("PAR2 repair failed: {}", e), &webhook_url).await;
                return;
            }
            info!("Job {} PAR2 stage complete", job_id);
        } else if total_failed_segments > 0 && !has_par2_files {
            let total_segments = nzb.total_segments();
            let pct = (total_failed_segments as f64 / total_segments as f64) * 100.0;
            if pct > 10.0 {
                self.fail_job(job_id, &format!("{}/{} segments failed ({:.1}%) — no PAR2", total_failed_segments, total_segments, pct), &webhook_url).await;
                return;
            }
            warn!("Job {} has {}/{} failed segments ({:.1}%) but no PAR2 — continuing", job_id, total_failed_segments, total_segments, pct);
        } else if total_failed_segments == 0 {
            info!("Job {} all CRC32 checks passed — skipping PAR2 verify", job_id);
        }

        // --- Wait for Direct Unpack to finish (if running) ---
        if let Some(handle) = unpack_handle {
            match handle.await {
                Ok(Ok(())) => {
                    info!("Job {} Direct Unpack completed", job_id);
                }
                Ok(Err(e)) => {
                    // Direct Unpack failed — try normal extraction as fallback
                    warn!("Job {} Direct Unpack failed ({}), trying normal extraction", job_id, e);
                    if let Err(e2) = Self::extract_archives(&temp_path, nzb_password.as_deref()).await {
                        self.fail_job(job_id, &format!("RAR extraction failed: {}", e2), &webhook_url).await;
                        return;
                    }
                }
                Err(e) => {
                    warn!("Job {} Direct Unpack panicked ({}), trying normal extraction", job_id, e);
                    if let Err(e2) = Self::extract_archives(&temp_path, nzb_password.as_deref()).await {
                        self.fail_job(job_id, &format!("RAR extraction failed: {}", e2), &webhook_url).await;
                        return;
                    }
                }
            }
        } else {
            // Direct Unpack disabled or no RAR files — extract after download+PAR2 complete.
            match Self::extract_archives(&temp_path, nzb_password.as_deref()).await {
                Ok(extracted) => { if extracted { info!("Job {} archive extraction successful", job_id); } }
                Err(e) => {
                    self.fail_job(job_id, &format!("Archive extraction failed: {}", e), &webhook_url).await;
                    return;
                }
            }
        }

        // Deobfuscate any media files with random-looking names
        Self::deobfuscate_files(&temp_path, &job_name).await;

        // Move completed files from temp to destination
        if let Err(e) = Self::move_completed(&temp_path, &dest_path).await {
            self.fail_job(job_id, &format!("Failed to move completed files: {}", e), &webhook_url).await;
            return;
        }
        let _ = tokio::fs::remove_dir_all(&temp_path).await;

        // Mark completed
        let completed_at = Utc::now();
        let final_bytes = downloaded_bytes.load(Ordering::Relaxed);
        let (name, category, destination) = {
            let mut jobs = self.jobs.write().await;
            if let Some(job) = jobs.get_mut(&job_id) {
                job.status = JobStatus::Completed;
                job.completed_at = Some(completed_at);
                job.progress = 100.0;
                job.downloaded_bytes = final_bytes;
                (job.name.clone(), job.category.clone(), job.destination.clone())
            } else { return; }
        };

        let _ = self.db.update_job_status(&job_id, &JobStatus::Completed, None, None, Some(completed_at));
        let _ = self.db.update_job_progress(&job_id, 100.0, final_bytes, total_bytes, 0);
        info!("Job {} completed successfully", job_id);

        // List the files the job actually produced. The importer uses this as
        // a whitelist so rclone cross-directory leaks can't smuggle unrelated
        // files in.
        let final_dir = destination.clone().unwrap_or_else(|| dest_dir.clone());
        let mut final_files: Vec<String> = Vec::new();
        if let Ok(mut rd) = tokio::fs::read_dir(&final_dir).await {
            while let Ok(Some(entry)) = rd.next_entry().await {
                if let Ok(ft) = entry.file_type().await {
                    if ft.is_file() {
                        final_files.push(entry.file_name().to_string_lossy().into_owned());
                    }
                }
            }
        }

        self.webhook_client.send(&webhook_url, &WebhookPayload {
            id: job_id,
            status: WebhookEvent::JobCompleted.status_str(),
            name, category,
            destination: destination.clone(),
            path: destination.or_else(|| Some(dest_dir.clone())),
            error: None,
            timestamp: Utc::now(),
            files: final_files,
        }).await;
    }

    /// Batch-boundary checkpoint: parks while the whole downloader (global
    /// pause) or this job (`JobStatus::Paused`) is paused, returning only
    /// when runnable again. Returns true if the job was cancelled or dropped
    /// (caller should stop). No pool connections are held while parked.
    async fn paused_or_cancelled(
        control: &Arc<DownloadControl>,
        jobs: &JobStore,
        jid: Uuid,
    ) -> bool {
        loop {
            if control.is_paused() {
                control.wait_if_paused().await;
                continue;
            }
            let status = {
                let j = jobs.read().await;
                j.get(&jid).map(|x| x.status.clone())
            };
            match status {
                Some(JobStatus::Cancelled) | None => return true,
                Some(JobStatus::Paused) => {
                    tokio::time::sleep(Duration::from_millis(500)).await;
                }
                _ => return false,
            }
        }
    }

    /// Append a decoded segment to the file, creating it lazily on the first
    /// successful segment so a file whose every segment failed leaves no empty
    /// stub behind (PAR2 then treats it as fully missing, as before).
    async fn write_segment(
        writer: &mut Option<tokio::fs::File>,
        path: &Path,
        data: &[u8],
    ) -> Result<(), String> {
        if writer.is_none() {
            let f = tokio::fs::File::create(path)
                .await
                .map_err(|e| Self::disk_err("Create file", path, &e))?;
            *writer = Some(f);
        }
        writer
            .as_mut()
            .unwrap()
            .write_all(data)
            .await
            .map_err(|e| Self::disk_err("Write", path, &e))?;
        Ok(())
    }

    /// Tag ENOSPC/EDQUOT distinctly so the job is *paused* (partial files
    /// kept) instead of failed+wiped — a transient full disk shouldn't nuke
    /// a nearly-complete download (SABnzbd pause-on-disk-full).
    fn disk_err(op: &str, path: &Path, e: &std::io::Error) -> String {
        match e.raw_os_error() {
            Some(28) | Some(122) => format!("DISKFULL:{} {:?}: {}", op, path, e),
            _ => format!("{} error {:?}: {}", op, path, e),
        }
    }

    /// Fetch a single segment with full retry logic.
    async fn fetch_segment(
        pool: Arc<NntpPool>, msg_id: String, seg_num: u32,
        counter: Arc<AtomicU64>, groups: Vec<String>,
        publish_date: Option<DateTime<Utc>>,
    ) -> Result<(u32, Vec<u8>), String> {
        const MAX_RETRIES: u32 = 6;
        // Mirrors SABnzbd's `max_art_tries=3`. 411/423/430/451 can be transient under
        // server load (dropped connections, overload); give them a few retries before
        // declaring the article permanently missing.
        const MAX_MISSING_TRIES: u32 = 3;
        let mut last_err = String::new();
        let mut is_missing = false;
        let mut missing_attempts: u32 = 0;
        let mut best_bad_data: Option<Vec<u8>> = None;

        for attempt in 0..MAX_RETRIES {
            if attempt > 0 {
                let base_ms = 500 * (1 << attempt.min(4));
                let jitter = rand::thread_rng().gen_range(0..500);
                tokio::time::sleep(Duration::from_millis(base_ms + jitter)).await;
            }

            let raw_body = match pool.fetch_article(&msg_id, &groups, publish_date).await {
                Ok(b) => b,
                Err(e) => {
                    let err_str = e.to_string();
                    if is_article_missing(&err_str) {
                        missing_attempts += 1;
                        last_err = format!(
                            "Article missing for segment {} (missing attempt {}/{}): {}",
                            seg_num, missing_attempts, MAX_MISSING_TRIES, err_str,
                        );
                        if missing_attempts >= MAX_MISSING_TRIES {
                            is_missing = true;
                            break;
                        }
                        continue;
                    }
                    last_err = format!("NNTP error for segment {} (attempt {}): {}", seg_num, attempt + 1, e);
                    continue;
                }
            };

            if is_dmca_content(&raw_body) {
                is_missing = true;
                last_err = format!("DMCA/takedown detected for segment {}", seg_num);
                break;
            }

            match decode_yenc(&raw_body) {
                Ok(result) => {
                    if result.crc_valid {
                        counter.fetch_add(result.data.len() as u64, Ordering::Relaxed);
                        return Ok((seg_num, result.data));
                    }
                    if best_bad_data.is_none() || result.data.len() > best_bad_data.as_ref().unwrap().len() {
                        best_bad_data = Some(result.data);
                    }
                    last_err = format!("CRC32 mismatch for segment {} (attempt {})", seg_num, attempt + 1);
                    continue;
                }
                Err(e) => {
                    let err_str = e.to_string();
                    if err_str.contains("DMCA") || err_str.contains("takedown") {
                        is_missing = true;
                        last_err = format!("DMCA for segment {}: {}", seg_num, err_str);
                        break;
                    }
                    last_err = format!("yEnc decode error segment {} (attempt {}): {}", seg_num, attempt + 1, e);
                    continue;
                }
            }
        }

        if let Some(bad_data) = best_bad_data {
            warn!("Segment {} using bad-CRC data ({} bytes)", seg_num, bad_data.len());
            counter.fetch_add(bad_data.len() as u64, Ordering::Relaxed);
            return Ok((seg_num, bad_data));
        }

        if is_missing { Err(format!("MISSING:{}", last_err)) } else { Err(last_err) }
    }

    async fn find_first_rar(dir: &Path) -> Option<PathBuf> {
        let mut read_dir = tokio::fs::read_dir(dir).await.ok()?;
        let mut first_plain: Option<PathBuf> = None;
        let mut first_part01: Option<PathBuf> = None;

        while let Ok(Some(entry)) = read_dir.next_entry().await {
            let name = entry.file_name().to_string_lossy().to_string();
            let lower = name.to_lowercase();
            if lower.ends_with(".rar") {
                if !lower.contains(".part") {
                    return Some(entry.path());
                } else if lower.contains(".part01.rar") || lower.contains(".part001.rar") {
                    first_part01 = Some(entry.path());
                } else if first_plain.is_none() {
                    first_plain = Some(entry.path());
                }
            }
        }
        first_part01.or(first_plain)
    }

    async fn find_first_zip(dir: &Path) -> Option<PathBuf> {
        let mut read_dir = tokio::fs::read_dir(dir).await.ok()?;
        while let Ok(Some(entry)) = read_dir.next_entry().await {
            if entry.file_name().to_string_lossy().to_lowercase().ends_with(".zip") {
                return Some(entry.path());
            }
        }
        None
    }

    async fn cleanup_archives(dir: &Path) {
        let Ok(mut read_dir) = tokio::fs::read_dir(dir).await else { return };
        while let Ok(Some(entry)) = read_dir.next_entry().await {
            let lower = entry.file_name().to_string_lossy().to_lowercase();
            let remove = lower.ends_with(".rar")
                || lower.ends_with(".zip")
                || lower.ends_with(".par2")
                || lower.ends_with(".nfo")
                || lower.ends_with(".sfv")
                || lower.ends_with(".nzb")
                || (lower.len() > 4
                    && lower.chars().rev().take(2).all(|c| c.is_ascii_digit())
                    && lower.chars().rev().nth(2) == Some('r')
                    && lower.chars().rev().nth(3) == Some('.'));
            if remove { let _ = tokio::fs::remove_file(entry.path()).await; }
        }
    }

    async fn move_completed(temp_path: &Path, dest_path: &Path) -> Result<(), String> {
        let mut read_dir = tokio::fs::read_dir(temp_path).await
            .map_err(|e| format!("Cannot read temp dir: {}", e))?;
        while let Ok(Some(entry)) = read_dir.next_entry().await {
            let src = entry.path();
            if src.is_dir() { continue; }
            let file_name = match src.file_name() { Some(n) => n.to_owned(), None => continue };
            let dst = dest_path.join(&file_name);
            if let Some(parent) = dst.parent() { let _ = tokio::fs::create_dir_all(parent).await; }
            // Try fast in-fs rename first. When temp + dest live on
            // different filesystems (e.g. RWO working dir + RWX final
            // dir on Kubernetes) rename fails with EXDEV — fall back
            // to copy + delete so the move still succeeds.
            match tokio::fs::rename(&src, &dst).await {
                Ok(()) => {}
                // EXDEV on Linux is 18 — kept as a literal so we don't
                // pull in libc just for one constant.
                Err(e) if e.raw_os_error() == Some(18) => {
                    tokio::fs::copy(&src, &dst).await
                        .map_err(|e| format!("Copy {} -> {}: {}", src.display(), dst.display(), e))?;
                    tokio::fs::remove_file(&src).await
                        .map_err(|e| format!("Remove {} after cross-fs copy: {}", src.display(), e))?;
                }
                Err(e) => {
                    return Err(format!("Rename {} -> {}: {}", src.display(), dst.display(), e));
                }
            }
        }
        Ok(())
    }

    /// Locate the base `.par2` file (preferring the non-`.vol` one).
    async fn find_base_par2(dir: &Path) -> Option<PathBuf> {
        let mut best: Option<PathBuf> = None;
        let mut any: Option<PathBuf> = None;
        if let Ok(mut rd) = tokio::fs::read_dir(dir).await {
            while let Ok(Some(entry)) = rd.next_entry().await {
                let lower = entry.file_name().to_string_lossy().to_lowercase();
                if lower.ends_with(".par2") {
                    if !lower.contains(".vol") {
                        best = Some(entry.path());
                        break;
                    }
                    any.get_or_insert_with(|| entry.path());
                }
            }
        }
        best.or(any)
    }

    /// Run par2repair once and classify what it reported.
    async fn par2_run(dir: &Path) -> Result<Par2Outcome, String> {
        let par2_file = Self::find_base_par2(dir).await.ok_or("No .par2 file found")?;
        info!("Running par2repair with: {}", par2_file.display());
        let output = tokio::process::Command::new("par2repair")
            .arg(&par2_file)
            .current_dir(dir)
            .output()
            .await
            .map_err(|e| format!("Failed to execute par2repair: {}", e))?;

        let stdout = String::from_utf8_lossy(&output.stdout);
        let stderr = String::from_utf8_lossy(&output.stderr);
        let success = output.status.success();
        let outcome = classify_par2_output(&stdout, success);
        if outcome == Par2Outcome::Failed {
            error!(
                "par2repair failed (exit {:?}): {}\n{}",
                output.status.code(),
                stdout.trim(),
                stderr.trim()
            );
        }
        Ok(outcome)
    }

    /// Verify/repair with par2, fetching only as many recovery volumes as the
    /// tool says are missing — smallest-block-count volumes first — instead of
    /// blindly downloading every `.vol` file. Mirrors SABnzbd's postproc
    /// re-add loop (`postproc.py:452-456`). `par2_volumes` are NZB files not
    /// yet on disk.
    async fn par2_repair_with_volumes(
        &self,
        temp_path: &Path,
        par2_volumes: &[&crate::models::nzb::NzbFile],
        publish_date: Option<DateTime<Utc>>,
    ) -> Result<(), String> {
        // Volumes still available to fetch, fewest recovery blocks first so we
        // pull the least recovery data needed to cover the deficit.
        let mut remaining: Vec<&crate::models::nzb::NzbFile> = par2_volumes.to_vec();
        remaining.sort_by_key(|f| recovery_blocks_in_volume(&f.filename).unwrap_or(u32::MAX));

        const MAX_ROUNDS: usize = 8;
        for round in 0..MAX_ROUNDS {
            match Self::par2_run(temp_path).await? {
                Par2Outcome::NotNeeded => {
                    if round == 0 {
                        info!("PAR2 verification passed");
                    }
                    return Ok(());
                }
                Par2Outcome::Repaired => {
                    info!("PAR2 repair successful");
                    return Ok(());
                }
                Par2Outcome::Failed => {
                    return Err("par2 reported an unrecoverable error".to_string());
                }
                Par2Outcome::NeedMoreBlocks(needed) => {
                    if remaining.is_empty() {
                        return Err(format!(
                            "needs {} more recovery blocks but no PAR2 volumes remain",
                            needed
                        ));
                    }
                    let mut acquired = 0u32;
                    let mut fetched_any = false;
                    while acquired < needed && !remaining.is_empty() {
                        let vol = remaining.remove(0);
                        let blocks = recovery_blocks_in_volume(&vol.filename).unwrap_or(0);
                        if self.download_nzb_file(vol, temp_path, publish_date).await {
                            acquired += blocks;
                            fetched_any = true;
                            info!(
                                "Fetched PAR2 volume {} (+{} blocks, {}/{} needed)",
                                vol.filename, blocks, acquired, needed
                            );
                        } else {
                            warn!("Failed to fetch PAR2 volume {}", vol.filename);
                        }
                    }
                    if !fetched_any {
                        return Err(format!(
                            "needs {} more recovery blocks but no volume could be fetched",
                            needed
                        ));
                    }
                }
            }
        }
        Err("PAR2 repair did not converge after maximum rounds".to_string())
    }

    /// Download a single NZB file (used for on-demand PAR2 volumes) into
    /// `dir`, writing only CRC-valid segments in order. Returns true if the
    /// file was written. Reserves cache budget like the main download path.
    async fn download_nzb_file(
        &self,
        file: &crate::models::nzb::NzbFile,
        dir: &Path,
        publish_date: Option<DateTime<Utc>>,
    ) -> bool {
        let bytes: usize = file.segments.iter().map(|s| s.bytes as usize).sum();
        let _reservation = self.article_cache.reserve(bytes).await;

        let mut data: Vec<(u32, Vec<u8>)> = Vec::new();
        for seg in &file.segments {
            if let Ok(raw) = self
                .nntp_pool
                .fetch_article(&seg.message_id, &file.groups, publish_date)
                .await
            {
                if let Ok(result) = decode_yenc(&raw) {
                    if result.crc_valid {
                        data.push((seg.number, result.data));
                    }
                }
            }
        }
        if data.is_empty() {
            return false;
        }
        data.sort_by_key(|(n, _)| *n);
        let dest_file = dir.join(&file.filename);
        match tokio::fs::File::create(&dest_file).await {
            Ok(mut f) => {
                for (_, d) in &data {
                    if f.write_all(d).await.is_err() {
                        return false;
                    }
                }
                f.flush().await.is_ok()
            }
            Err(_) => false,
        }
    }

    async fn extract_archives(dest_path: &Path, password: Option<&str>) -> Result<bool, String> {
        if let Some(rar_file) = Self::find_first_rar(dest_path).await {
            info!("Extracting RAR archive: {}", rar_file.display());
            let mut cmd = tokio::process::Command::new("unrar");
            cmd.args(["x", "-y", "-o+"]);
            if let Some(pw) = password { cmd.arg(format!("-p{}", pw)); } else { cmd.arg("-p-"); }
            cmd.arg(&rar_file);
            cmd.arg(format!("{}/", dest_path.display()));
            let output = cmd.output().await.map_err(|e| format!("Failed to execute unrar: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                return Err(format!("RAR extraction failed: {} {}", stdout.trim(), stderr.trim()));
            }

            info!("RAR extraction complete, cleaning up archive files");
            Self::cleanup_archives(dest_path).await;
            return Ok(true);
        }

        if let Some(zip_file) = Self::find_first_zip(dest_path).await {
            info!("Extracting ZIP archive: {}", zip_file.display());
            let mut cmd = tokio::process::Command::new("7z");
            cmd.args(["x", "-y", "-bd"]);
            cmd.arg(format!("-o{}", dest_path.display()));
            if let Some(pw) = password { cmd.arg(format!("-p{}", pw)); }
            cmd.arg(&zip_file);
            let output = cmd.output().await.map_err(|e| format!("Failed to execute 7z: {}", e))?;

            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let stdout = String::from_utf8_lossy(&output.stdout);
                return Err(format!("ZIP extraction failed: {} {}", stdout.trim(), stderr.trim()));
            }

            info!("ZIP extraction complete, cleaning up archive files");
            Self::cleanup_archives(dest_path).await;
            return Ok(true);
        }

        Ok(false)
    }

    /// Returns true if the filename stem looks obfuscated (random characters, no real words).
    /// Common patterns: all alphanumeric with no dots or separators, 10+ chars, no recognizable words.
    pub fn is_obfuscated(filename: &str) -> bool {
        // Only consider media file extensions
        const MEDIA_EXTENSIONS: &[&str] = &[
            "mkv", "mp4", "avi", "mov", "wmv", "flv", "m4v", "ts", "m2ts",
            "mp3", "flac", "aac", "ogg", "m4a", "wav",
        ];

        let path = std::path::Path::new(filename);
        let ext = match path.extension().and_then(|e| e.to_str()) {
            Some(e) => e.to_lowercase(),
            None => return false,
        };

        if !MEDIA_EXTENSIONS.contains(&ext.as_str()) {
            return false;
        }

        let stem = match path.file_stem().and_then(|s| s.to_str()) {
            Some(s) => s,
            None => return false,
        };

        // Too short to be obfuscated
        if stem.len() < 8 {
            return false;
        }

        // If it contains spaces, dots, underscores or dashes it's probably a real name
        if stem.contains(' ') || stem.contains('.') || stem.contains('_') || stem.contains('-') {
            return false;
        }

        // Check character distribution: obfuscated names are often mixed case alphanumeric
        // with no separator characters at all
        let alpha_count = stem.chars().filter(|c| c.is_alphabetic()).count();
        let digit_count = stem.chars().filter(|c| c.is_ascii_digit()).count();
        let total = stem.len();

        // Must be fully alphanumeric
        if alpha_count + digit_count != total {
            return false;
        }

        // If there are digits mixed in among letters in a random-looking way (not just a year etc.)
        // and the name is long enough, treat as obfuscated
        let has_digits = digit_count > 0;
        let has_upper = stem.chars().any(|c| c.is_uppercase());
        let has_lower = stem.chars().any(|c| c.is_lowercase());

        // Mixed case + digits + no separators + length >= 10 → very likely obfuscated
        if total >= 10 && has_digits && has_upper && has_lower {
            return true;
        }

        // All-lowercase or all-uppercase + length >= 15 + no separators → obfuscated
        if total >= 15 && !has_digits && (has_upper != has_lower) {
            return true;
        }

        false
    }

    /// Scan `dir` for media files with obfuscated names and rename them using `job_name`.
    /// If multiple obfuscated files are found, append an index suffix.
    pub async fn deobfuscate_files(dir: &Path, job_name: &str) {
        let Ok(mut read_dir) = tokio::fs::read_dir(dir).await else { return };

        let mut obfuscated: Vec<PathBuf> = Vec::new();
        while let Ok(Some(entry)) = read_dir.next_entry().await {
            if entry.path().is_file() {
                let name = entry.file_name().to_string_lossy().to_string();
                if Self::is_obfuscated(&name) {
                    obfuscated.push(entry.path());
                }
            }
        }

        if obfuscated.is_empty() {
            return;
        }

        info!("Deobfuscation: found {} obfuscated file(s), renaming using job name '{}'", obfuscated.len(), job_name);

        // Sanitize job_name for use as a filename
        let safe_name: String = job_name.chars().map(|c| match c {
            '/' | '\\' | ':' | '*' | '?' | '<' | '>' | '|' | '"' => '_',
            _ => c,
        }).collect();

        for (i, path) in obfuscated.iter().enumerate() {
            let ext = path.extension().and_then(|e| e.to_str()).unwrap_or("").to_lowercase();
            let new_name = if obfuscated.len() == 1 {
                format!("{}.{}", safe_name, ext)
            } else {
                format!("{}.part{:02}.{}", safe_name, i + 1, ext)
            };
            let new_path = path.parent().unwrap_or(dir).join(&new_name);
            match tokio::fs::rename(path, &new_path).await {
                Ok(()) => info!("Deobfuscated: {} -> {}", path.file_name().unwrap_or_default().to_string_lossy(), new_name),
                Err(e) => warn!("Deobfuscation rename failed for {}: {}", path.display(), e),
            }
        }
    }

    /// Disk full: park the job as Paused, keep all partial files, and clear
    /// `started_at` so a later resume re-queues it (re-downloads with the
    /// streaming assembler). Deliberately does NOT wipe temp/dest like
    /// `fail_job` would — a transient full disk must not destroy progress.
    async fn pause_disk_full(&self, job_id: Uuid, error_msg: &str) {
        let msg = error_msg.trim_start_matches("DISKFULL:").trim();
        warn!("Job {} paused — disk full: {}", job_id, msg);
        let display = format!("Paused: disk full ({})", msg);
        {
            let mut jobs = self.jobs.write().await;
            if let Some(job) = jobs.get_mut(&job_id) {
                job.status = JobStatus::Paused;
                job.error = Some(display.clone());
                job.started_at = None;
                job.speed_bps = 0;
            } else {
                return;
            }
        }
        let _ = self
            .db
            .update_job_status(&job_id, &JobStatus::Paused, Some(&display), None, None);
    }

    async fn fail_job(&self, job_id: Uuid, error_msg: &str, webhook_url: &str) {
        error!("Job {} failed: {}", job_id, error_msg);
        let completed_at = Utc::now();
        let (name, category, destination) = {
            let mut jobs = self.jobs.write().await;
            if let Some(job) = jobs.get_mut(&job_id) {
                job.status = JobStatus::Failed;
                job.error = Some(error_msg.to_string());
                job.completed_at = Some(completed_at);
                (job.name.clone(), job.category.clone(), job.destination.clone())
            } else { return; }
        };
        let _ = self.db.update_job_status(&job_id, &JobStatus::Failed, Some(error_msg), None, Some(completed_at));
        self.webhook_client.send(webhook_url, &WebhookPayload {
            id: job_id,
            status: WebhookEvent::JobFailed.status_str(),
            name: name.clone(), category,
            destination: destination.clone(), path: destination,
            error: Some(error_msg.to_string()),
            timestamp: Utc::now(),
            files: Vec::new(),
        }).await;

        let download_dir = self.config.download.directory.join(&name);
        if download_dir.exists() {
            match tokio::fs::remove_dir_all(&download_dir).await {
                Ok(_) => info!("Cleaned up failed download directory: {}", download_dir.display()),
                Err(e) => warn!("Failed to clean up directory {}: {}", download_dir.display(), e),
            }
        }
        // Mid-failure (e.g. ENOSPC during write) leaves partial files in the
        // per-job temp dir. The success path deletes it after the move; on
        // failure the move never runs so we have to clean up here too,
        // otherwise these dirs accumulate until the disk is full.
        let temp_dir = self.config.download.temp_directory.join(job_id.to_string());
        if temp_dir.exists() {
            match tokio::fs::remove_dir_all(&temp_dir).await {
                Ok(_) => info!("Cleaned up failed temp directory: {}", temp_dir.display()),
                Err(e) => warn!("Failed to clean up temp dir {}: {}", temp_dir.display(), e),
            }
        }
    }
}
