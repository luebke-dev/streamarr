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
                track_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'queued',
                priority INTEGER NOT NULL DEFAULT 5,
                category TEXT,
                destination TEXT,
                webhook_url TEXT,
                progress REAL NOT NULL DEFAULT 0,
                path TEXT,
                error TEXT,
                created_at TEXT NOT NULL,
                started_at TEXT,
                completed_at TEXT,
                file_size INTEGER
            );",
        )?;

        // Migrate old tables that used 'done' status
        conn.execute(
            "UPDATE jobs SET status = 'completed' WHERE status = 'done'",
            [],
        )
        .ok();

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

    pub fn insert_job(&self, job: &Job) {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO jobs (id, track_id, status, priority, category, destination, webhook_url,
             progress, path, error, created_at, started_at, completed_at, file_size)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14)",
            params![
                job.id.to_string(),
                job.track_id,
                job.status.as_str(),
                job.priority,
                job.category,
                job.destination,
                job.webhook_url,
                job.progress,
                job.path,
                job.error,
                job.created_at.to_rfc3339(),
                job.started_at.map(|t| t.to_rfc3339()),
                job.completed_at.map(|t| t.to_rfc3339()),
                job.file_size,
            ],
        )
        .expect("Failed to insert job");
    }

    pub fn update_job(&self, job: &Job) {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE jobs SET status = ?1, progress = ?2, path = ?3, error = ?4,
                            started_at = ?5, completed_at = ?6, file_size = ?7
             WHERE id = ?8",
            params![
                job.status.as_str(),
                job.progress,
                job.path,
                job.error,
                job.started_at.map(|t| t.to_rfc3339()),
                job.completed_at.map(|t| t.to_rfc3339()),
                job.file_size,
                job.id.to_string(),
            ],
        )
        .expect("Failed to update job");
    }

    pub fn get_job(&self, id: Uuid) -> Option<Job> {
        let conn = self.conn.lock().unwrap();
        conn.query_row(
            "SELECT id, track_id, status, priority, category, destination, webhook_url,
                    progress, path, error, created_at, started_at, completed_at, file_size
             FROM jobs WHERE id = ?1",
            params![id.to_string()],
            row_to_job,
        )
        .ok()
    }

    pub fn get_all_jobs(&self) -> Vec<Job> {
        let conn = self.conn.lock().unwrap();
        let mut stmt = conn
            .prepare(
                "SELECT id, track_id, status, priority, category, destination, webhook_url,
                        progress, path, error, created_at, started_at, completed_at, file_size
                 FROM jobs ORDER BY created_at DESC",
            )
            .expect("Failed to prepare query");

        stmt.query_map([], row_to_job)
            .expect("Failed to query jobs")
            .filter_map(|r| r.ok())
            .collect()
    }

    pub fn delete_job(&self, id: Uuid) -> bool {
        let conn = self.conn.lock().unwrap();
        let rows = conn
            .execute("DELETE FROM jobs WHERE id = ?1", params![id.to_string()])
            .unwrap_or(0);
        rows > 0
    }

    pub fn load_pending_jobs(&self) -> Vec<Job> {
        let conn = self.conn.lock().unwrap();

        // Reset downloading -> queued
        conn.execute(
            "UPDATE jobs SET status = 'queued', started_at = NULL, progress = 0 WHERE status = 'downloading'",
            [],
        )
        .ok();

        let mut stmt = conn
            .prepare(
                "SELECT id, track_id, status, priority, category, destination, webhook_url,
                        progress, path, error, created_at, started_at, completed_at, file_size
                 FROM jobs WHERE status = 'queued' ORDER BY priority DESC, created_at ASC",
            )
            .expect("Failed to prepare query");

        stmt.query_map([], row_to_job)
            .expect("Failed to query jobs")
            .filter_map(|r| r.ok())
            .collect()
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

fn row_to_job(row: &rusqlite::Row) -> rusqlite::Result<Job> {
    let id_str: String = row.get(0)?;
    let status_str: String = row.get(2)?;
    let created_at_str: String = row.get(10)?;
    let started_at_str: Option<String> = row.get(11)?;
    let completed_at_str: Option<String> = row.get(12)?;

    Ok(Job {
        id: Uuid::parse_str(&id_str).unwrap_or_default(),
        track_id: row.get(1)?,
        status: JobStatus::from_str(&status_str),
        priority: row.get::<_, u8>(3)?,
        category: row.get(4)?,
        destination: row.get(5)?,
        webhook_url: row.get(6)?,
        progress: row.get(7)?,
        path: row.get(8)?,
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
        file_size: row.get(13)?,
    })
}
