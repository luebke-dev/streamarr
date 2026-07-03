use crate::api::AppState;
use crate::error::AppError;
use crate::models::job::{CreateJobRequest, Job, JobResponse, JobStatus, QueueEntry};
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;
use base64::Engine;
use chrono::Utc;
use serde::{Deserialize, Serialize};
use uuid::Uuid;

pub async fn create_job(
    State(state): State<AppState>,
    Json(request): Json<CreateJobRequest>,
) -> Result<(StatusCode, Json<JobResponse>), AppError> {
    let nzb_content = if let Some(ref content) = request.nzb_content {
        let decoded = base64::engine::general_purpose::STANDARD
            .decode(content)
            .map_err(|e| AppError::InvalidNzb(format!("Invalid base64: {}", e)))?;
        String::from_utf8(decoded)
            .map_err(|e| AppError::InvalidNzb(format!("Invalid UTF-8 in NZB: {}", e)))?
    } else if let Some(ref url) = request.nzb_url {
        state
            .http_client
            .get(url)
            .send()
            .await
            .map_err(|e| AppError::InvalidNzb(format!("Failed to fetch NZB URL: {}", e)))?
            .text()
            .await
            .map_err(|e| AppError::InvalidNzb(format!("Failed to read NZB response: {}", e)))?
    } else {
        return Err(AppError::InvalidNzb(
            "Either nzb_url or nzb_content must be provided".to_string(),
        ));
    };

    let job = Job::new(request, nzb_content);
    let response = JobResponse::from(&job);
    let entry = QueueEntry {
        job_id: job.id,
        priority: job.priority,
        created_at: job.created_at,
    };

    // Persist to DB
    state
        .db
        .insert_job(&job)
        .map_err(|e| AppError::Download(format!("DB error: {}", e)))?;

    // Store in memory cache and enqueue
    {
        let mut jobs = state.jobs.write().await;
        jobs.insert(job.id, job);
    }
    state.queue.push(entry);

    Ok((StatusCode::CREATED, Json(response)))
}

pub async fn list_jobs(State(state): State<AppState>) -> Json<Vec<JobResponse>> {
    // Read from DB for complete history (includes completed/failed from previous runs)
    match state.db.get_all_jobs() {
        Ok(db_jobs) => {
            // Merge with in-memory state for live progress of active jobs
            let mem_jobs = state.jobs.read().await;
            let mut responses: Vec<JobResponse> = db_jobs
                .iter()
                .map(|db_job| {
                    if let Some(mem_job) = mem_jobs.get(&db_job.id) {
                        JobResponse::from(mem_job)
                    } else {
                        JobResponse::from(db_job)
                    }
                })
                .collect();
            responses.sort_by(|a, b| b.created_at.cmp(&a.created_at));
            Json(responses)
        }
        Err(_) => {
            // Fallback to memory
            let jobs = state.jobs.read().await;
            let mut responses: Vec<JobResponse> = jobs.values().map(JobResponse::from).collect();
            responses.sort_by(|a, b| b.created_at.cmp(&a.created_at));
            Json(responses)
        }
    }
}

pub async fn get_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    // Try memory first (has live progress)
    let jobs = state.jobs.read().await;
    if let Some(job) = jobs.get(&id) {
        return Ok(Json(JobResponse::from(job)));
    }
    drop(jobs);

    // Fallback to DB
    state
        .db
        .get_job(&id)
        .map_err(|e| AppError::Download(format!("DB error: {}", e)))?
        .map(|job| Json(JobResponse::from(&job)))
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))
}

/// Pause a job. A running job parks at the next batch boundary (connections
/// kept); a still-queued job is removed from the queue so the worker skips it.
pub async fn pause_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    let mut jobs = state.jobs.write().await;
    let job = jobs
        .get_mut(&id)
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))?;
    match job.status {
        JobStatus::Downloading => {
            job.status = JobStatus::Paused;
            let _ =
                state
                    .db
                    .update_job_status(&id, &JobStatus::Paused, None, job.started_at, None);
        }
        JobStatus::Queued => {
            job.status = JobStatus::Paused;
            job.started_at = None;
            let _ = state
                .db
                .update_job_status(&id, &JobStatus::Paused, None, None, None);
            state.queue.remove(&id);
        }
        _ => {}
    }
    Ok(Json(JobResponse::from(&*job)))
}

/// Resume a paused job. If its download tasks are still parked in this process
/// (started_at set + in memory) it just un-pauses; otherwise it is re-queued.
pub async fn resume_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    {
        let mut jobs = state.jobs.write().await;
        if let Some(job) = jobs.get_mut(&id) {
            if job.status == JobStatus::Paused {
                if job.started_at.is_some() {
                    job.status = JobStatus::Downloading;
                    let _ = state.db.update_job_status(
                        &id,
                        &JobStatus::Downloading,
                        None,
                        job.started_at,
                        None,
                    );
                } else {
                    job.status = JobStatus::Queued;
                    job.error = None;
                    let _ =
                        state
                            .db
                            .update_job_status(&id, &JobStatus::Queued, None, None, None);
                    state.queue.push(QueueEntry {
                        job_id: id,
                        priority: job.priority,
                        created_at: job.created_at,
                    });
                }
            }
            return Ok(Json(JobResponse::from(&*job)));
        }
    }

    // Not in memory (e.g. paused before a restart): reload from DB + requeue.
    let mut job = state
        .db
        .get_job(&id)
        .map_err(|e| AppError::Download(format!("DB error: {}", e)))?
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))?;
    if job.status == JobStatus::Paused {
        job.status = JobStatus::Queued;
        job.started_at = None;
        job.error = None;
        let _ = state
            .db
            .update_job_status(&id, &JobStatus::Queued, None, None, None);
        let entry = QueueEntry {
            job_id: job.id,
            priority: job.priority,
            created_at: job.created_at,
        };
        let resp = JobResponse::from(&job);
        state.jobs.write().await.insert(job.id, job);
        state.queue.push(entry);
        return Ok(Json(resp));
    }
    Ok(Json(JobResponse::from(&job)))
}

#[derive(Serialize)]
pub struct ControlResponse {
    pub paused: bool,
    pub speed_limit_kbps: u64,
}

pub async fn get_control(State(state): State<AppState>) -> Json<ControlResponse> {
    Json(ControlResponse {
        paused: state.control.is_paused(),
        speed_limit_kbps: state.control.speed_limit_kbps(),
    })
}

pub async fn pause_all(State(state): State<AppState>) -> Json<ControlResponse> {
    state.control.set_paused(true);
    Json(ControlResponse {
        paused: true,
        speed_limit_kbps: state.control.speed_limit_kbps(),
    })
}

pub async fn resume_all(State(state): State<AppState>) -> Json<ControlResponse> {
    state.control.set_paused(false);
    Json(ControlResponse {
        paused: false,
        speed_limit_kbps: state.control.speed_limit_kbps(),
    })
}

#[derive(Deserialize)]
pub struct SpeedLimitRequest {
    pub kbps: u64,
}

pub async fn set_speed_limit(
    State(state): State<AppState>,
    Json(req): Json<SpeedLimitRequest>,
) -> Json<ControlResponse> {
    state.control.set_speed_limit_kbps(req.kbps);
    Json(ControlResponse {
        paused: state.control.is_paused(),
        speed_limit_kbps: state.control.speed_limit_kbps(),
    })
}

pub async fn cancel_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    state.queue.remove(&id);

    let mut jobs = state.jobs.write().await;
    let job = jobs
        .get_mut(&id)
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))?;

    match job.status {
        JobStatus::Queued | JobStatus::Downloading | JobStatus::Paused => {
            job.status = JobStatus::Cancelled;
            let _ = state.db.update_job_status(
                &id,
                &JobStatus::Cancelled,
                None,
                job.started_at,
                Some(Utc::now()),
            );
            Ok(Json(JobResponse::from(&*job)))
        }
        _ => Ok(Json(JobResponse::from(&*job))),
    }
}
