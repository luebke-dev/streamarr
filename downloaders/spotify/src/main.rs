mod api;
mod config;
mod db;
mod error;
mod models;
mod queue;
mod spotify;
mod webhooks;

use crate::api::AppState;
use crate::config::Config;
use crate::db::Database;
use crate::queue::priority_queue::PriorityQueue;
use crate::webhooks::client::WebhookClient;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;
use tracing::info;

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    tracing_subscriber::fmt()
        .with_env_filter(
            tracing_subscriber::EnvFilter::try_from_default_env()
                .unwrap_or_else(|_| "spotify_downloader=info,librespot=warn".into()),
        )
        .init();

    let config = Config::from_env().map_err(|e| {
        eprintln!("Configuration error: {}", e);
        e
    })?;
    info!("Configuration loaded from environment");

    std::fs::create_dir_all(&config.spotify.config_dir)?;
    std::fs::create_dir_all(&config.download_dir)?;

    let db = Arc::new(
        Database::open(&config.database_path)
            .map_err(|e| format!("Failed to open database: {}", e))?,
    );
    info!("Database opened at {}", config.database_path.display());

    let session = spotify::authenticate(&config.spotify).await;
    let session_lock: Arc<RwLock<Option<librespot_core::session::Session>>> =
        Arc::new(RwLock::new(Some(session)));

    let queue = Arc::new(PriorityQueue::new());
    let webhook_client = Arc::new(WebhookClient::new(config.webhooks.clone(), db.clone()));
    let output_dir = Arc::new(PathBuf::from(&config.download_dir));

    // Webhook outbox redelivery: attempt undelivered terminal events on startup
    // and every 60s thereafter so completions survive backend downtime.
    let redeliver_client = webhook_client.clone();
    tokio::spawn(async move {
        loop {
            redeliver_client.redeliver_pending().await;
            tokio::time::sleep(std::time::Duration::from_secs(60)).await;
        }
    });

    let worker = spotify::DownloadWorker::new(
        session_lock.clone(),
        config.spotify.clone(),
        config.download_dir.clone(),
        config.spotify.bitrate,
        db.clone(),
        queue.clone(),
        webhook_client,
    );
    tokio::spawn(async move {
        worker.run().await;
    });

    let state = AppState {
        db,
        queue,
        output_dir,
        session: session_lock,
    };

    let app = api::router(state, config.enable_webui)
        .layer(tower_http::trace::TraceLayer::new_for_http());

    if config.enable_webui {
        info!("Web UI enabled");
    }

    let addr = format!("{}:{}", config.server.host, config.server.port);
    info!("Starting server on {}", addr);

    let listener = tokio::net::TcpListener::bind(&addr).await?;
    axum::serve(listener, app).await?;

    Ok(())
}
