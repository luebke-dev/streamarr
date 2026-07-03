mod api;
mod config;
mod db;
mod downloader;
mod error;
mod models;
mod queue;
mod webhooks;

use crate::api::AppState;
use crate::config::Config;
use crate::db::Database;
use crate::downloader::control::DownloadControl;
use crate::downloader::worker::{DownloadWorker, JobStore};
use crate::models::job::QueueEntry;
use crate::queue::priority_queue::PriorityQueue;
use crate::webhooks::client::WebhookClient;
use std::collections::HashMap;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::info;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    rustls::crypto::ring::default_provider()
        .install_default()
        .expect("Failed to install rustls crypto provider");

    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "usenet_downloader=info,tower_http=info".into()),
        )
        .init();

    let config = Config::from_env().map_err(|e| {
        eprintln!("Configuration error: {}", e);
        e
    })?;
    info!("Configuration loaded from environment");

    // Open database
    let db = Arc::new(
        Database::open(&config.database_path)
            .map_err(|e| format!("Failed to open database: {}", e))?,
    );
    info!("Database opened at {}", config.database_path.display());

    let jobs: JobStore = Arc::new(RwLock::new(HashMap::new()));
    let queue = Arc::new(PriorityQueue::new());
    let webhook_client = Arc::new(WebhookClient::new(config.webhooks.clone(), db.clone()));
    let control = Arc::new(DownloadControl::new(config.download.speed_limit_kbps));

    // Webhook outbox redelivery: attempt undelivered terminal events on startup
    // and every 60s thereafter so completions survive backend downtime.
    let redeliver_client = webhook_client.clone();
    tokio::spawn(async move {
        loop {
            redeliver_client.redeliver_pending().await;
            tokio::time::sleep(std::time::Duration::from_secs(60)).await;
        }
    });

    // Restore pending jobs from DB
    let pending_jobs = db
        .load_pending_jobs()
        .map_err(|e| format!("Failed to load pending jobs: {}", e))?;

    if !pending_jobs.is_empty() {
        info!("Restoring {} pending jobs from database", pending_jobs.len());
        let mut job_map = jobs.write().await;
        for job in pending_jobs {
            let entry = QueueEntry {
                job_id: job.id,
                priority: job.priority,
                created_at: job.created_at,
            };
            job_map.insert(job.id, job);
            queue.push(entry);
        }
    }

    let worker = Arc::new(DownloadWorker::new(
        config.clone(),
        queue.clone(),
        jobs.clone(),
        db.clone(),
        webhook_client,
        control.clone(),
    ));
    let worker_handle = worker.clone();
    tokio::spawn(async move {
        worker_handle.run().await;
    });

    let state = AppState {
        jobs,
        queue,
        db,
        control,
        http_client: reqwest::Client::new(),
    };

    let app = api::router(state)
        .layer(tower_http::trace::TraceLayer::new_for_http());

    let addr = format!("{}:{}", config.server.host, config.server.port);
    info!("Starting server on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
