use crate::config::WebhookConfig;
use chrono::{DateTime, Utc};
use serde::Serialize;
use std::time::Duration;
use tracing::{error, info, warn};
use uuid::Uuid;

#[derive(Debug, Serialize)]
pub struct WebhookPayload {
    pub event: WebhookEvent,
    pub job_id: Uuid,
    pub name: String,
    pub category: Option<String>,
    pub destination: Option<String>,
    pub path: Option<String>,
    pub error: Option<String>,
    pub timestamp: DateTime<Utc>,
}

#[derive(Debug, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WebhookEvent {
    JobCompleted,
    JobFailed,
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
                            url, payload.job_id
                        );
                        return;
                    }
                    warn!(
                        "Webhook returned {} for job {} (attempt {}/{})",
                        response.status(),
                        payload.job_id,
                        attempt + 1,
                        self.config.max_retries + 1
                    );
                }
                Err(e) => {
                    warn!(
                        "Webhook failed for job {} (attempt {}/{}): {}",
                        payload.job_id,
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
            payload.job_id, url
        );
    }

    pub fn default_url(&self) -> &str {
        &self.config.url
    }
}
