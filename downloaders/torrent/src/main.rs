mod api;
mod config;
mod db;
mod error;
mod models;
mod queue;
mod torrent;
mod webhooks;

use crate::api::AppState;
use crate::config::Config;
use crate::db::Database;
use crate::queue::priority_queue::PriorityQueue;
use crate::torrent::engine::TorrentEngine;
use crate::torrent::worker::DownloadWorker;
use crate::webhooks::client::WebhookClient;
use std::sync::Arc;
use tracing::info;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "torrent_downloader=info,tower_http=info".into()),
        )
        .init();

    let config = Config::from_env().map_err(|e| {
        eprintln!("Configuration error: {}", e);
        e
    })?;
    info!("Configuration loaded from environment");

    // Ensure directories exist
    std::fs::create_dir_all(&config.download.directory)?;

    // Initialize SQLite
    let db = Arc::new(
        Database::open(&config.download.db_path)
            .map_err(|e| format!("Failed to open database: {}", e))?,
    );
    info!("Database opened at {}", config.download.db_path.display());

    // Initialize torrent engine
    let engine = Arc::new(
        TorrentEngine::new(config.download.directory.clone(), &config.torrent).await?,
    );
    info!("Torrent engine initialized (DHT: {})", config.torrent.enable_dht);

    let queue = Arc::new(PriorityQueue::new());
    let webhook_client = Arc::new(WebhookClient::new(config.webhooks.clone()));

    // Start download worker
    let worker = Arc::new(DownloadWorker::new(
        config.clone(),
        queue.clone(),
        db.clone(),
        engine,
        webhook_client,
    ));
    let worker_handle = worker.clone();
    tokio::spawn(async move {
        worker_handle.run().await;
    });

    let state = AppState {
        db,
        queue,
        config: config.clone(),
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
