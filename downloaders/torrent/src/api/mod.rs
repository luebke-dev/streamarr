pub mod health;
pub mod jobs;

use crate::config::Config;
use crate::db::Database;
use crate::queue::priority_queue::PriorityQueue;
use axum::routing::{delete, get, post};
use axum::Router;
use std::sync::Arc;

#[derive(Clone)]
pub struct AppState {
    pub db: Arc<Database>,
    pub queue: Arc<PriorityQueue>,
    pub config: Config,
    pub http_client: reqwest::Client,
}

pub fn router(state: AppState) -> Router {
    Router::new()
        .route("/api/health", get(health::health))
        .route("/api/jobs", post(jobs::create_job))
        .route("/api/jobs", get(jobs::list_jobs))
        .route("/api/jobs/{id}", get(jobs::get_job))
        .route("/api/jobs/{id}", delete(jobs::cancel_job))
        .with_state(state)
}
