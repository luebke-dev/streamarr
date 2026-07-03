use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::cmp::Ordering;
use uuid::Uuid;

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum JobStatus {
    Queued,
    Downloading,
    Paused,
    Completed,
    Failed,
    Cancelled,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Job {
    pub id: Uuid,
    pub name: String,
    pub status: JobStatus,
    pub priority: u8,
    pub category: Option<String>,
    pub destination: Option<String>,
    pub webhook_url: Option<String>,
    pub nzb_content: String,
    pub progress: f64,
    pub error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub total_bytes: u64,
    pub downloaded_bytes: u64,
    /// Current download speed in bytes/sec (live; 0 when not downloading).
    #[serde(default)]
    pub speed_bps: u64,
}

impl Job {
    pub fn new(request: CreateJobRequest, nzb_content: String) -> Self {
        Self {
            id: Uuid::new_v4(),
            name: request.name,
            status: JobStatus::Queued,
            priority: request.priority.unwrap_or(5).clamp(1, 10),
            category: request.category,
            destination: request.destination,
            webhook_url: request.webhook_url,
            nzb_content,
            progress: 0.0,
            error: None,
            created_at: Utc::now(),
            started_at: None,
            completed_at: None,
            total_bytes: 0,
            downloaded_bytes: 0,
            speed_bps: 0,
        }
    }
}

/// For BinaryHeap ordering: higher priority first, then older jobs first
impl Eq for QueueEntry {}
impl PartialEq for QueueEntry {
    fn eq(&self, other: &Self) -> bool {
        self.priority == other.priority && self.created_at == other.created_at
    }
}

impl Ord for QueueEntry {
    fn cmp(&self, other: &Self) -> Ordering {
        self.priority
            .cmp(&other.priority)
            .then_with(|| other.created_at.cmp(&self.created_at)) // older first
    }
}

impl PartialOrd for QueueEntry {
    fn partial_cmp(&self, other: &Self) -> Option<Ordering> {
        Some(self.cmp(other))
    }
}

#[derive(Debug, Clone)]
pub struct QueueEntry {
    pub job_id: Uuid,
    pub priority: u8,
    pub created_at: DateTime<Utc>,
}

#[derive(Debug, Deserialize)]
pub struct CreateJobRequest {
    pub name: String,
    pub nzb_url: Option<String>,
    pub nzb_content: Option<String>,
    pub priority: Option<u8>,
    pub category: Option<String>,
    pub destination: Option<String>,
    pub webhook_url: Option<String>,
}

#[derive(Debug, Serialize)]
pub struct JobResponse {
    pub id: Uuid,
    pub name: String,
    pub status: JobStatus,
    pub priority: u8,
    pub category: Option<String>,
    pub destination: Option<String>,
    pub progress: f64,
    pub error: Option<String>,
    pub created_at: DateTime<Utc>,
    pub started_at: Option<DateTime<Utc>>,
    pub completed_at: Option<DateTime<Utc>>,
    pub total_bytes: u64,
    pub downloaded_bytes: u64,
    pub speed_bps: u64,
}

impl From<&Job> for JobResponse {
    fn from(job: &Job) -> Self {
        Self {
            id: job.id,
            name: job.name.clone(),
            status: job.status.clone(),
            priority: job.priority,
            category: job.category.clone(),
            destination: job.destination.clone(),
            progress: job.progress,
            error: job.error.clone(),
            created_at: job.created_at,
            started_at: job.started_at,
            completed_at: job.completed_at,
            total_bytes: job.total_bytes,
            downloaded_bytes: job.downloaded_bytes,
            speed_bps: job.speed_bps,
        }
    }
}
