pub mod health;
pub mod jobs;

use crate::db::Database;
use crate::downloader::control::DownloadControl;
use crate::downloader::worker::JobStore;
use crate::queue::priority_queue::PriorityQueue;
use axum::routing::{delete, get, post};
use axum::Router;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub jobs: JobStore,
    pub queue: Arc<PriorityQueue>,
    pub db: Arc<Database>,
    pub control: Arc<DownloadControl>,
    pub http_client: reqwest::Client,
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/api/health", get(health::health))
        .route("/api/jobs", post(jobs::create_job))
        .route("/api/jobs", get(jobs::list_jobs))
        .route("/api/jobs/{id}", get(jobs::get_job))
        .route("/api/jobs/{id}", delete(jobs::cancel_job))
        .route("/api/jobs/{id}/pause", post(jobs::pause_job))
        .route("/api/jobs/{id}/resume", post(jobs::resume_job))
        .route("/api/control", get(jobs::get_control))
        .route("/api/control/pause", post(jobs::pause_all))
        .route("/api/control/resume", post(jobs::resume_all))
        .route("/api/control/speedlimit", post(jobs::set_speed_limit))
        .with_state(state)
}
