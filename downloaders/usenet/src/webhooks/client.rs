use crate::config::WebhookConfig;
use crate::db::Database;
use chrono::{DateTime, Utc};
use serde::Serialize;
use std::sync::Arc;
use std::time::Duration;
use tracing::{error, info, warn};
use uuid::Uuid;

/// Cap on redelivery attempts before we stop actively retrying an outbox entry.
/// The row is kept (never silently dropped) and logged so it can be inspected.
const MAX_OUTBOX_ATTEMPTS: i64 = 24;

#[derive(Debug, Serialize)]
pub struct WebhookPayload {
    /// Job UUID — sent as "id" for backend compatibility
    pub id: Uuid,
    /// Terminal status: "completed" or "failed"
    pub status: &'static str,
    pub name: String,
    pub category: Option<String>,
    pub destination: Option<String>,
    pub path: Option<String>,
    pub error: Option<String>,
    pub timestamp: DateTime<Utc>,
    /// Basenames of the files that ended up in the destination directory
    /// after extraction. The importer uses this as a whitelist so a stale
    /// rclone listing that leaks in files from neighbouring directories
    /// cannot cause a cross-release import.
    #[serde(default)]
    pub files: Vec<String>,
}

#[derive(Debug, Clone, Copy)]
pub enum WebhookEvent {
    JobCompleted,
    JobFailed,
}

impl WebhookEvent {
    pub fn status_str(self) -> &'static str {
        match self {
            WebhookEvent::JobCompleted => "completed",
            WebhookEvent::JobFailed => "failed",
        }
    }
}

pub struct WebhookClient {
    http_client: reqwest::Client,
    config: WebhookConfig,
    db: Arc<Database>,
}

impl WebhookClient {
    pub fn new(config: WebhookConfig, db: Arc<Database>) -> Self {
        let http_client = reqwest::Client::builder()
            .timeout(Duration::from_secs(config.timeout_secs))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            http_client,
            config,
            db,
        }
    }

    /// Perform a single POST of an already-serialized JSON body. Returns true on
    /// a 2xx response, false on any transport error or non-success status.
    async fn post_once(&self, url: &str, body: &str, job_id: &str) -> bool {
        let mut req = self
            .http_client
            .post(url)
            .header(reqwest::header::CONTENT_TYPE, "application/json")
            .body(body.to_string());
        if !self.config.secret.is_empty() {
            req = req.header("X-Webhook-Secret", &self.config.secret);
        }
        match req.send().await {
            Ok(response) => {
                if response.status().is_success() {
                    true
                } else {
                    warn!(
                        "Webhook returned {} for job {} to {}",
                        response.status(),
                        job_id,
                        url
                    );
                    false
                }
            }
            Err(e) => {
                warn!("Webhook request failed for job {} to {}: {}", job_id, url, e);
                false
            }
        }
    }

    /// Send a terminal webhook notification. Retries with exponential backoff;
    /// if all live attempts fail the event is persisted to the outbox so it can
    /// be redelivered after backend downtime rather than being lost.
    pub async fn send(&self, url: &str, payload: &WebhookPayload) {
        let body = match serde_json::to_string(payload) {
            Ok(b) => b,
            Err(e) => {
                error!("Failed to serialize webhook payload for job {}: {}", payload.id, e);
                return;
            }
        };
        let job_id = payload.id.to_string();

        for attempt in 0..=self.config.max_retries {
            if self.post_once(url, &body, &job_id).await {
                info!("Webhook sent successfully to {} for job {}", url, job_id);
                return;
            }
            if attempt < self.config.max_retries {
                let delay = Duration::from_secs(1 << attempt); // 1s, 2s, 4s
                tokio::time::sleep(delay).await;
            }
        }

        error!(
            "Webhook exhausted all retries for job {} to {}; persisting to outbox",
            job_id, url
        );
        self.db
            .insert_pending_webhook(url, payload.status, &body, &job_id);
    }

    /// Attempt to redeliver every persisted webhook event. On success the entry
    /// is removed; on failure its attempt counter is bumped and it is retried on
    /// the next cycle. Entries past the attempt cap are kept and logged.
    pub async fn redeliver_pending(&self) {
        let pending = self.db.get_pending_webhooks();
        if pending.is_empty() {
            return;
        }
        info!("Redelivering {} pending webhook(s) from outbox", pending.len());

        for pw in pending {
            if pw.attempts >= MAX_OUTBOX_ATTEMPTS {
                warn!(
                    "Pending webhook {} for job {} exceeded {} attempts; keeping for inspection",
                    pw.id, pw.job_id, MAX_OUTBOX_ATTEMPTS
                );
                continue;
            }
            if self.post_once(&pw.url, &pw.payload, &pw.job_id).await {
                self.db.delete_pending_webhook(&pw.id);
                info!(
                    "Redelivered pending webhook {} ({}) for job {}",
                    pw.id, pw.event_type, pw.job_id
                );
            } else {
                self.db.increment_webhook_attempts(&pw.id);
                warn!(
                    "Redelivery failed for pending webhook {} (job {}); attempts now {}",
                    pw.id,
                    pw.job_id,
                    pw.attempts + 1
                );
            }
        }
    }

    pub fn default_url(&self) -> &str {
        &self.config.url
    }
}
