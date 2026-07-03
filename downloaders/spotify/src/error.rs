use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("Job not found: {0}")]
    JobNotFound(String),

    #[error("Not authenticated")]
    NotAuthenticated,

    #[error("Invalid track: {0}")]
    InvalidTrack(String),

    #[error("Internal error: {0}")]
    Internal(String),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, message) = match &self {
            AppError::JobNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::NotAuthenticated => (StatusCode::SERVICE_UNAVAILABLE, self.to_string()),
            AppError::InvalidTrack(_) => (StatusCode::BAD_REQUEST, self.to_string()),
            AppError::Internal(_) => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };

        let body = serde_json::json!({ "error": message });
        (status, axum::Json(body)).into_response()
    }
}
