use crate::api::AppState;
use crate::error::AppError;
use axum::body::Body;
use axum::extract::{Path, State};
use axum::http::{header, StatusCode};

/// Spotify track IDs are 22 chars of base62 (a-z, A-Z, 0-9). We enforce this
/// shape so a caller cannot smuggle path-traversal segments through the URL
/// path param to read files outside `output_dir`.
fn is_valid_track_id(s: &str) -> bool {
    !s.is_empty()
        && s.len() <= 64
        && s.chars().all(|c| c.is_ascii_alphanumeric())
}

pub async fn serve_file(
    State(state): State<AppState>,
    Path(track_id): Path<String>,
) -> Result<(StatusCode, [(header::HeaderName, String); 2], Body), AppError> {
    let raw = track_id.strip_suffix(".ogg").unwrap_or(&track_id);
    if !is_valid_track_id(raw) {
        return Err(AppError::JobNotFound("File not found".to_string()));
    }
    let filename = format!("{raw}.ogg");
    let file_path = state.output_dir.join(&filename);
    if !file_path.exists() {
        return Err(AppError::JobNotFound("File not found".to_string()));
    }
    let body = Body::from(
        std::fs::read(&file_path).map_err(|e| AppError::Internal(e.to_string()))?,
    );
    Ok((
        StatusCode::OK,
        [
            (header::CONTENT_TYPE, "audio/ogg".to_string()),
            (
                header::CONTENT_DISPOSITION,
                format!("attachment; filename=\"{filename}\""),
            ),
        ],
        body,
    ))
}
