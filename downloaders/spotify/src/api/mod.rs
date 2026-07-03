pub mod files;
pub mod health;
pub mod jobs;

use crate::db::Database;
use crate::queue::priority_queue::PriorityQueue;
use axum::routing::{get, post};
use axum::Router;
use librespot_core::session::Session;
use std::path::PathBuf;
use std::sync::Arc;
use tokio::sync::RwLock;

#[derive(Clone)]
pub struct AppState {
    pub db: Arc<Database>,
    pub queue: Arc<PriorityQueue>,
    pub output_dir: Arc<PathBuf>,
    pub session: Arc<RwLock<Option<Session>>>,
}

pub fn router(state: AppState, enable_webui: bool) -> Router {
    let mut app = Router::new()
        .route("/api/health", get(health::health))
        .route("/api/jobs", post(jobs::create_job))
        .route("/api/jobs", get(jobs::list_jobs))
        .route("/api/jobs/{id}", get(jobs::get_job).delete(jobs::delete_job))
        .route("/api/files/{track_id}", get(files::serve_file))
        .with_state(state);

    if enable_webui {
        app = app.route("/", get(jobs::index));
    }

    app
}
