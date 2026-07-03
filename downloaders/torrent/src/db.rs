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
                id                  TEXT PRIMARY KEY,
                name                TEXT NOT NULL,
                status              TEXT NOT NULL DEFAULT 'queued',
                priority            INTEGER NOT NULL DEFAULT 5,
                category            TEXT,
                destination         TEXT,
                webhook_url         TEXT,
                magnet_uri          TEXT,
                torrent_content     TEXT,
                info_hash           TEXT,
                progress            REAL NOT NULL DEFAULT 0.0,
                error               TEXT,
                created_at          TEXT NOT NULL,
                started_at          TEXT,
                completed_at        TEXT,
                total_bytes         INTEGER NOT NULL DEFAULT 0,
                downloaded_bytes    INTEGER NOT NULL DEFAULT 0,
                uploaded_bytes      INTEGER NOT NULL DEFAULT 0,
                download_speed      INTEGER NOT NULL DEFAULT 0,
                upload_speed        INTEGER NOT NULL DEFAULT 0,
                peers_connected     INTEGER NOT NULL DEFAULT 0,
                seeds_connected     INTEGER NOT NULL DEFAULT 0
            );",
        )?;
        Ok(Self {
            conn: Mutex::new(conn),
        })
    }

    pub fn insert_job(&self, job: &Job) {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "INSERT INTO jobs (id, name, status, priority, category, destination, webhook_url,
                              magnet_uri, torrent_content, info_hash, progress, error,
                              created_at, started_at, completed_at,
                              total_bytes, downloaded_bytes, uploaded_bytes,
                              download_speed, upload_speed, peers_connected, seeds_connected)
             VALUES (?1, ?2, ?3, ?4, ?5, ?6, ?7, ?8, ?9, ?10, ?11, ?12, ?13, ?14, ?15,
                     ?16, ?17, ?18, ?19, ?20, ?21, ?22)",
            params![
                job.id.to_string(),
                job.name,
                job.status.as_str(),
                job.priority,
                job.category,
                job.destination,
                job.webhook_url,
                job.magnet_uri,
                job.torrent_content,
                job.info_hash,
                job.progress,
                job.error,
                job.created_at.to_rfc3339(),
                job.started_at.map(|t| t.to_rfc3339()),
                job.completed_at.map(|t| t.to_rfc3339()),
                job.total_bytes,
                job.downloaded_bytes,
                job.uploaded_bytes,
                job.download_speed,
                job.upload_speed,
                job.peers_connected,
                job.seeds_connected,
            ],
        )
        .expect("Failed to insert job");
    }

    pub fn update_job(&self, job: &Job) {
        let conn = self.conn.lock().unwrap();
        conn.execute(
            "UPDATE jobs SET status = ?1, progress = ?2, error = ?3,
                            started_at = ?4, completed_at = ?5,
                            total_bytes = ?6, downloaded_bytes = ?7, uploaded_bytes = ?8,
                            download_speed = ?9, upload_speed = ?10,
                            peers_connected = ?11, seeds_connected = ?12,
                            info_hash = ?13
             WHERE id = ?14",
            params![
                job.status.as_str(),
                job.progress,
                job.error,
                job.started_at.map(|t| t.to_rfc3339()),
                job.completed_at.map(|t| t.to_rfc3339()),
                job.total_bytes,
                job.downloaded_bytes,
                job.uploaded_bytes,
                job.download_speed,
                job.upload_speed,
                job.peers_connected,
                job.seeds_connected,
                job.info_hash,
                job.id.to_string(),
            ],
        )
        .expect("Failed to update job");
    }

    pub fn get_job(&self, id: Uuid) -> Option<Job> {
        let conn = self.conn.lock().unwrap();
        conn.query_row(
            "SELECT id, name, status, priority, category, destination, webhook_url,
                    magnet_uri, torrent_content, info_hash, progress, error,
                    created_at, started_at, completed_at,
                    total_bytes, downloaded_bytes, uploaded_bytes,
                    download_speed, upload_speed, peers_connected, seeds_connected
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
                "SELECT id, name, status, priority, category, destination, webhook_url,
                        magnet_uri, torrent_content, info_hash, progress, error,
                        created_at, started_at, completed_at,
                        total_bytes, downloaded_bytes, uploaded_bytes,
                        download_speed, upload_speed, peers_connected, seeds_connected
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
            "UPDATE jobs SET status = 'queued', started_at = NULL, progress = 0, downloaded_bytes = 0 WHERE status = 'downloading'",
            [],
        )
        .ok();

        let mut stmt = conn
            .prepare(
                "SELECT id, name, status, priority, category, destination, webhook_url,
                        magnet_uri, torrent_content, info_hash, progress, error,
                        created_at, started_at, completed_at,
                        total_bytes, downloaded_bytes, uploaded_bytes,
                        download_speed, upload_speed, peers_connected, seeds_connected
                 FROM jobs WHERE status IN ('queued', 'downloading')
                 ORDER BY priority DESC, created_at ASC",
            )
            .expect("Failed to prepare query");

        stmt.query_map([], row_to_job)
            .expect("Failed to query jobs")
            .filter_map(|r| r.ok())
            .collect()
    }
}

fn row_to_job(row: &rusqlite::Row) -> rusqlite::Result<Job> {
    let id_str: String = row.get(0)?;
    let status_str: String = row.get(2)?;
    let created_str: String = row.get(12)?;
    let started_str: Option<String> = row.get(13)?;
    let completed_str: Option<String> = row.get(14)?;

    Ok(Job {
        id: Uuid::parse_str(&id_str).unwrap_or_else(|_| Uuid::new_v4()),
        name: row.get(1)?,
        status: JobStatus::from_str(&status_str),
        priority: row.get(3)?,
        category: row.get(4)?,
        destination: row.get(5)?,
        webhook_url: row.get(6)?,
        magnet_uri: row.get(7)?,
        torrent_content: row.get(8)?,
        info_hash: row.get(9)?,
        progress: row.get(10)?,
        error: row.get(11)?,
        created_at: DateTime::parse_from_rfc3339(&created_str)
            .map(|t| t.with_timezone(&Utc))
            .unwrap_or_else(|_| Utc::now()),
        started_at: started_str.and_then(|s| {
            DateTime::parse_from_rfc3339(&s)
                .map(|t| t.with_timezone(&Utc))
                .ok()
        }),
        completed_at: completed_str.and_then(|s| {
            DateTime::parse_from_rfc3339(&s)
                .map(|t| t.with_timezone(&Utc))
                .ok()
        }),
        total_bytes: row.get::<_, i64>(15)? as u64,
        downloaded_bytes: row.get::<_, i64>(16)? as u64,
        uploaded_bytes: row.get::<_, i64>(17)? as u64,
        download_speed: row.get::<_, i64>(18)? as u64,
        upload_speed: row.get::<_, i64>(19)? as u64,
        peers_connected: row.get::<_, i32>(20)? as u32,
        seeds_connected: row.get::<_, i32>(21)? as u32,
    })
}
