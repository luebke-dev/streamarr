use crate::api::AppState;
use crate::error::AppError;
use crate::models::job::{CreateJobRequest, Job, JobResponse, JobStatus, QueueEntry};
use crate::torrent::parser;
use axum::extract::{Path, State};
use axum::http::StatusCode;
use axum::Json;
use base64::Engine;
use uuid::Uuid;

pub async fn create_job(
    State(state): State<AppState>,
    Json(request): Json<CreateJobRequest>,
) -> Result<(StatusCode, Json<JobResponse>), AppError> {
    // Resolve torrent source: magnet_uri, torrent_url, or torrent_content
    let (name, info_hash, magnet_uri, torrent_content) =
        if let Some(ref magnet) = request.magnet_uri {
            let parsed = parser::parse_magnet(magnet)?;
            let name = request
                .name
                .clone()
                .or(parsed.display_name.clone())
                .unwrap_or_else(|| parsed.info_hash.clone());
            (name, Some(parsed.info_hash), Some(magnet.clone()), None)
        } else if let Some(ref url) = request.torrent_url {
            let bytes = state
                .http_client
                .get(url)
                .send()
                .await
                .map_err(|e| {
                    AppError::InvalidTorrent(format!("Failed to fetch torrent URL: {}", e))
                })?
                .bytes()
                .await
                .map_err(|e| {
                    AppError::InvalidTorrent(format!("Failed to read torrent response: {}", e))
                })?;
            let parsed = parser::parse_torrent_file(&bytes)?;
            let name = request.name.clone().unwrap_or(parsed.name);
            let encoded = base64::engine::general_purpose::STANDARD.encode(&bytes);
            (name, Some(parsed.info_hash), None, Some(encoded))
        } else if let Some(ref content) = request.torrent_content {
            let bytes = base64::engine::general_purpose::STANDARD
                .decode(content)
                .map_err(|e| AppError::InvalidTorrent(format!("Invalid base64: {}", e)))?;
            let parsed = parser::parse_torrent_file(&bytes)?;
            let name = request.name.clone().unwrap_or(parsed.name);
            (name, Some(parsed.info_hash), None, Some(content.clone()))
        } else {
            return Err(AppError::InvalidTorrent(
                "Either magnet_uri, torrent_url, or torrent_content must be provided".to_string(),
            ));
        };

    let mut job = Job::new(&request, name, info_hash);
    job.magnet_uri = magnet_uri;
    job.torrent_content = torrent_content;

    let response = JobResponse::from(&job);
    let entry = QueueEntry {
        job_id: job.id,
        priority: job.priority,
        created_at: job.created_at,
    };

    state.db.insert_job(&job);
    state.queue.push(entry);

    Ok((StatusCode::CREATED, Json(response)))
}

pub async fn list_jobs(State(state): State<AppState>) -> Json<Vec<JobResponse>> {
    let jobs = state.db.get_all_jobs();
    Json(jobs.iter().map(JobResponse::from).collect())
}

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

pub async fn cancel_job(
    State(state): State<AppState>,
    Path(id): Path<Uuid>,
) -> Result<Json<JobResponse>, AppError> {
    // Remove from queue if still queued
    state.queue.remove(&id);

    let mut job = state
        .db
        .get_job(id)
        .ok_or_else(|| AppError::JobNotFound(id.to_string()))?;

    match job.status {
        JobStatus::Queued | JobStatus::Downloading | JobStatus::Seeding => {
            job.status = JobStatus::Cancelled;
            state.db.update_job(&job);
        }
        _ => {}
    }

    Ok(Json(JobResponse::from(&job)))
}
