use crate::config::WebhookConfig;
use chrono::{DateTime, Utc};
use serde::Serialize;
use std::time::Duration;
use tracing::{error, info, warn};
use uuid::Uuid;

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
}

impl WebhookClient {
    pub fn new(config: WebhookConfig) -> Self {
        let http_client = reqwest::Client::builder()
            .timeout(Duration::from_secs(config.timeout_secs))
            .build()
            .expect("Failed to create HTTP client");

        Self {
            http_client,
            config,
        }
    }

    /// Send a webhook notification. Retries with exponential backoff.
    pub async fn send(&self, url: &str, payload: &WebhookPayload) {
        for attempt in 0..=self.config.max_retries {
            let mut req = self.http_client.post(url).json(payload);
            if !self.config.secret.is_empty() {
                req = req.header("X-Webhook-Secret", &self.config.secret);
            }
            match req.send().await {
                Ok(response) => {
                    if response.status().is_success() {
                        info!(
                            "Webhook sent successfully to {} for job {}",
                            url, payload.id
                        );
                        return;
                    }
                    warn!(
                        "Webhook returned {} for job {} (attempt {}/{})",
                        response.status(),
                        payload.id,
                        attempt + 1,
                        self.config.max_retries + 1
                    );
                }
                Err(e) => {
                    warn!(
                        "Webhook failed for job {} (attempt {}/{}): {}",
                        payload.id,
                        attempt + 1,
                        self.config.max_retries + 1,
                        e
                    );
                }
            }

            if attempt < self.config.max_retries {
                let delay = Duration::from_secs(1 << attempt); // 1s, 2s, 4s
                tokio::time::sleep(delay).await;
            }
        }

        error!(
            "Webhook exhausted all retries for job {} to {}",
            payload.id, url
        );
    }

    pub fn default_url(&self) -> &str {
        &self.config.url
    }
}
