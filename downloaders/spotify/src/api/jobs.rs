use crate::api::AppState;
use crate::error::AppError;
use crate::models::job::{CreateJobRequest, Job, JobResponse, JobStatus, QueueEntry};
use crate::spotify;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::response::Html;
use axum::Json;
use chrono::Utc;
use uuid::Uuid;

/// POST /api/jobs
pub async fn create_job(
    State(state): State<AppState>,
    Json(req): Json<CreateJobRequest>,
) -> Result<(StatusCode, Json<JobResponse>), AppError> {
    if state.session.read().await.is_none() {
        return Err(AppError::NotAuthenticated);
    }

    let (_uri_str, track_id) =
        spotify::normalize_track_id(&req.track_id).map_err(AppError::InvalidTrack)?;

    let now = Utc::now();
    let job_id = Uuid::new_v4();

    // Check cache
    let output_path = state.output_dir.join(format!("{track_id}.ogg"));
    if output_path.exists() {
        let file_size = std::fs::metadata(&output_path).ok().map(|m| m.len() as i64);
        let job = Job {
            id: job_id,
            track_id,
            status: JobStatus::Completed,
            priority: req.priority.unwrap_or(5).clamp(1, 10),
            category: req.category,
            destination: req.destination,
            webhook_url: req.webhook_url,
            progress: 100.0,
            path: Some(output_path.to_string_lossy().into_owned()),
            error: None,
            created_at: now,
            started_at: Some(now),
            completed_at: Some(now),
            file_size,
        };
        state.db.insert_job(&job);
        return Ok((StatusCode::OK, Json(JobResponse::from(&job))));
    }

    let job = Job {
        id: job_id,
        track_id,
        status: JobStatus::Queued,
        priority: req.priority.unwrap_or(5).clamp(1, 10),
        category: req.category,
        destination: req.destination,
        webhook_url: req.webhook_url,
        progress: 0.0,
        path: None,
        error: None,
        created_at: now,
        started_at: None,
        completed_at: None,
        file_size: None,
    };

    state.db.insert_job(&job);
    state.queue.push(QueueEntry {
        job_id: job.id,
        priority: job.priority,
        created_at: job.created_at,
    });

    Ok((StatusCode::ACCEPTED, Json(JobResponse::from(&job))))
}

/// GET /api/jobs
pub async fn list_jobs(State(state): State<AppState>) -> Json<Vec<JobResponse>> {
    let jobs = state.db.get_all_jobs();
    Json(jobs.iter().map(JobResponse::from).collect())
}

/// GET /api/jobs/{id}
pub async fn get_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    let job = state
        .db
        .get_job(id)
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))?;
    Ok(Json(JobResponse::from(&job)))
}

/// DELETE /api/jobs/{id}
pub async fn delete_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<StatusCode, AppError> {
    state.queue.remove(&id);

    if let Some(mut job) = state.db.get_job(id) {
        match job.status {
            JobStatus::Queued | JobStatus::Downloading => {
                job.status = JobStatus::Cancelled;
                state.db.update_job(&job);
            }
            _ => {}
        }
    }

    if state.db.delete_job(id) {
        Ok(StatusCode::NO_CONTENT)
    } else {
        Err(AppError::JobNotFound(id.to_string()))
    }
}

/// GET /
pub async fn index() -> Html<&'static str> {
    Html(include_str!("../index.html"))
}
