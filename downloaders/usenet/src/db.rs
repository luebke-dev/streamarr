use crate::models::job::{Job, JobStatus};
use chrono::{DateTime, Utc};
use rusqlite::{params, Connection};
use std::path::Path;
use std::sync::Mutex;
use uuid::Uuid;

pub struct Database {
    conn: Mutex<Connection>,
}

impl Database {
    pub fn open(path: &Path) -> Result<Self, rusqlite::Error> {
        if let Some(parent) = path.parent() {
            std::fs::create_dir_all(parent).ok();
        }

        let conn = Connection::open(path)?;
        conn.execute_batch("PRAGMA journal_mode=WAL; PRAGMA busy_timeout=5000;")?;

        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                status TEXT NOT NULL,
                priority INTEGER NOT NULL,
                category TEXT,
                destination TEXT,
                webhook_url TEXT,
                nzb_content TEXT NOT NULL,
                progress REAL NOT NULL DEFAULT 0,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                total_bytes INTEGER NOT NULL DEFAULT 0,
                downloaded_bytes INTEGER NOT NULL DEFAULT 0
            );",
        )?;

        // Idempotent migrations for columns added after the initial schema.
        // SQLite has no "ADD COLUMN IF NOT EXISTS", so check pragma first.
        let has_speed = conn
            .prepare("SELECT 1 FROM pragma_table_info('jobs') WHERE name = 'speed_bps'")?
            .query_map([], |_| Ok(()))?
            .next()
            .is_some();
        if !has_speed {
            conn.execute(
                "ALTER TABLE jobs ADD COLUMN speed_bps INTEGER NOT NULL DEFAULT 0",
                [],
            )?;
        }

        // Outbox for terminal webhook events that could not be delivered live.
        // Guarantees completion/failure notifications survive backend downtime.
        conn.execute_batch(
            "CREATE TABLE IF NOT EXISTS pending_webhooks (
                id          TEXT PRIMARY KEY,
                url         TEXT NOT NULL,
                event_type  TEXT NOT NULL,
                payload     TEXT NOT NULL,
                job_id      TEXT NOT NULL,
                created_at  TEXT NOT NULL,
                attempts    INTEGER NOT NULL DEFAULT 0
            );",
        )?;

        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn insert_job(&self, job: &Job) -> Result<(), rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO jobs (id, name, status, priority, category, destination, webhook_url,
             nzb_content, progress, error, created_at, started_at, completed_at, total_bytes, downloaded_bytes, speed_bps)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15, ?16)",
            params![
                job.id.to_string(),
                job.name,
                status_to_str(&job.status),
                job.priority,
                job.category,
                job.destination,
                job.webhook_url,
                job.nzb_content,
                job.progress,
                job.error,
                job.created_at.to_rfc3339(),
                job.started_at.map(|t| t.to_rfc3339()),
                job.completed_at.map(|t| t.to_rfc3339()),
                job.total_bytes as i64,
                job.downloaded_bytes as i64,
                job.speed_bps as i64,
            ],
        )?;
        Ok(())
    }

    pub fn update_job_status(
        &self,
        id: &Uuid,
        status: &JobStatus,
        error: Option<&str>,
        started_at: Option<DateTime<Utc>>,
        completed_at: Option<DateTime<Utc>>,
    ) -> Result<(), rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE jobs SET status = ?1, error = ?2, started_at = ?3, completed_at = ?4 WHERE id = ?5",
            params![
                status_to_str(status),
                error,
                started_at.map(|t| t.to_rfc3339()),
                completed_at.map(|t| t.to_rfc3339()),
                id.to_string(),
            ],
        )?;
        Ok(())
    }

    pub fn update_job_progress(
        &self,
        id: &Uuid,
        progress: f64,
        downloaded_bytes: u64,
        total_bytes: u64,
        speed_bps: u64,
    ) -> Result<(), rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE jobs SET progress = ?1, downloaded_bytes = ?2, total_bytes = ?3, speed_bps = ?4 WHERE id = ?5",
            params![
                progress,
                downloaded_bytes as i64,
                total_bytes as i64,
                speed_bps as i64,
                id.to_string(),
            ],
        )?;
        Ok(())
    }

    pub fn get_all_jobs(&self) -> Result<Vec<Job>, rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT id, name, status, priority, category, destination, webhook_url,
             nzb_content, progress, error, created_at, started_at, completed_at,
             total_bytes, downloaded_bytes, speed_bps FROM jobs ORDER BY created_at DESC",
        )?;

        let jobs = stmt
            .query_map([], |row| row_to_job(row))?
            .collect::<Result<Vec<_>, _>>()?;

        Ok(jobs)
    }

    pub fn get_job(&self, id: &Uuid) -> Result<Option<Job>, rusqlite::Error> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn.prepare(
            "SELECT id, name, status, priority, category, destination, webhook_url,
             nzb_content, progress, error, created_at, started_at, completed_at,
             total_bytes, downloaded_bytes, speed_bps FROM jobs WHERE id = ?1",
        )?;

        let mut rows = stmt.query_map(params![id.to_string()], |row| row_to_job(row))?;
        match rows.next() {
            Some(Ok(job)) => Ok(Some(job)),
            Some(Err(e)) => Err(e),
            None => Ok(None),
        }
    }

    /// Load jobs that need to be re-queued after restart.
    /// Resets `downloading` jobs back to `queued`.
    pub fn load_pending_jobs(&self) -> Result<Vec<Job>, rusqlite::Error> {
        let conn = self.conn.lock().unwrap();

        // Reset downloading -> queued
        conn.execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL, progress = 0, downloaded_bytes = 0 WHERE status = 'downloading'",
            [],
        )?;

        let mut stmt = conn.prepare(
            "SELECT id, name, status, priority, category, destination, webhook_url,
             nzb_content, progress, error, created_at, started_at, completed_at,
             total_bytes, downloaded_bytes, speed_bps FROM jobs WHERE status = 'queued' ORDER BY priority DESC, created_at ASC",
        )?;

        let jobs = stmt
            .query_map([], |row| row_to_job(row))?
            .collect::<Result<Vec<_>, _>>()?;

        Ok(jobs)
    }

    // ---- Webhook outbox ----------------------------------------------------

    /// Persist a terminal webhook event that could not be delivered live so it
    /// can be redelivered later. Errors are logged, never silently dropped.
    pub fn insert_pending_webhook(&self, url: &str, event_type: &str, payload: &str, job_id: &str) {
        let conn = self.conn.lock().unwrap();
        if let Err(e) = conn.execute(
            "INSERT INTO pending_webhooks (id, url, event_type, payload, job_id, created_at, attempts)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, 0)",
            params![
                Uuid::new_v4().to_string(),
                url,
                event_type,
                payload,
                job_id,
                Utc::now().to_rfc3339(),
            ],
        ) {
            tracing::error!("Failed to persist pending webhook for job {}: {}", job_id, e);
        }
    }

    pub fn get_pending_webhooks(&self) -> Vec<PendingWebhook> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = match conn.prepare(
            "SELECT id, url, event_type, payload, job_id, attempts
             FROM pending_webhooks ORDER BY created_at ASC",
        ) {
            Ok(s) => s,
            Err(e) => {
                tracing::error!("Failed to prepare pending_webhooks query: {}", e);
                return Vec::new();
            }
        };

        let rows = match stmt.query_map([], |row| {
            Ok(PendingWebhook {
                id: row.get(0)?,
                url: row.get(1)?,
                event_type: row.get(2)?,
                payload: row.get(3)?,
                job_id: row.get(4)?,
                attempts: row.get(5)?,
            })
        }) {
            Ok(rows) => rows,
            Err(e) => {
                tracing::error!("Failed to query pending_webhooks: {}", e);
                return Vec::new();
            }
        };
        rows.filter_map(|r| r.ok()).collect()
    }

    pub fn delete_pending_webhook(&self, id: &str) {
        let conn = self.conn.lock().unwrap();
        if let Err(e) = conn.execute("DELETE FROM pending_webhooks WHERE id = ?1", params![id]) {
            tracing::error!("Failed to delete pending webhook {}: {}", id, e);
        }
    }

    pub fn increment_webhook_attempts(&self, id: &str) {
        let conn = self.conn.lock().unwrap();
        if let Err(e) = conn.execute(
            "UPDATE pending_webhooks SET attempts = attempts + 1 WHERE id = ?1",
            params![id],
        ) {
            tracing::error!("Failed to increment attempts for pending webhook {}: {}", id, e);
        }
    }
}

/// A persisted, not-yet-delivered terminal webhook event.
#[derive(Debug, Clone)]
pub struct PendingWebhook {
    pub id: String,
    pub url: String,
    pub event_type: String,
    pub payload: String,
    pub job_id: String,
    pub attempts: i64,
}

fn row_to_job(row: &rusqlite::Row) -> Result<Job, rusqlite::Error> {
    let id_str: String = row.get(0)?;
    let status_str: String = row.get(2)?;
    let created_at_str: String = row.get(10)?;
    let started_at_str: Option<String> = row.get(11)?;
    let completed_at_str: Option<String> = row.get(12)?;
    let total_bytes: i64 = row.get(13)?;
    let downloaded_bytes: i64 = row.get(14)?;
    let speed_bps: i64 = row.get(15)?;

    Ok(Job {
        id: Uuid::parse_str(&id_str).unwrap_or_default(),
        name: row.get(1)?,
        status: str_to_status(&status_str),
        priority: row.get::<_, u8>(3)?,
        category: row.get(4)?,
        destination: row.get(5)?,
        webhook_url: row.get(6)?,
        nzb_content: row.get(7)?,
        progress: row.get(8)?,
        error: row.get(9)?,
        created_at: DateTime::parse_from_rfc3339(&created_at_str)
            .map(|t| t.with_timezone(&Utc))
            .unwrap_or_default(),
        started_at: started_at_str
            .and_then(|s| DateTime::parse_from_rfc3339(&s).ok())
            .map(|t| t.with_timezone(&Utc)),
        completed_at: completed_at_str
            .and_then(|s| DateTime::parse_from_rfc3339(&s).ok())
            .map(|t| t.with_timezone(&Utc)),
        total_bytes: total_bytes as u64,
        downloaded_bytes: downloaded_bytes as u64,
        speed_bps: speed_bps as u64,
    })
}

fn status_to_str(status: &JobStatus) -> &'static str {
    match status {
        JobStatus::Queued => "queued",
        JobStatus::Downloading => "downloading",
        JobStatus::Paused => "paused",
        JobStatus::Completed => "completed",
        JobStatus::Failed => "failed",
        JobStatus::Cancelled => "cancelled",
    }
}

fn str_to_status(s: &str) -> JobStatus {
    match s {
        "queued" => JobStatus::Queued,
        "downloading" => JobStatus::Downloading,
        "paused" => JobStatus::Paused,
        "completed" => JobStatus::Completed,
        "failed" => JobStatus::Failed,
        "cancelled" => JobStatus::Cancelled,
        _ => JobStatus::Failed,
    }
}
