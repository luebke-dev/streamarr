use axum::http::StatusCode;
use axum::response::{IntoResponse, Response};

#[derive(Debug, thiserror::Error)]
pub enum AppError {
    #[error("Job not found: {0}")]
    JobNotFound(String),

    #[error("Invalid NZB: {0}")]
    InvalidNzb(String),

    #[error("NNTP error: {0}")]
    Nntp(String),

    #[error("Download error: {0}")]
    Download(String),

    #[error("Webhook error: {0}")]
    Webhook(String),

    #[error("IO error: {0}")]
    Io(#[from] std::io::Error),

    #[error("Config error: {0}")]
    Config(String),
}

impl IntoResponse for AppError {
    fn into_response(self) -> Response {
        let (status, message) = match &self {
            AppError::JobNotFound(_) => (StatusCode::NOT_FOUND, self.to_string()),
            AppError::InvalidNzb(_) => (StatusCode::BAD_REQUEST, self.to_string()),
            _ => (StatusCode::INTERNAL_SERVER_ERROR, self.to_string()),
        };

        let body = serde_json::json!({ "error": message });
        (status, axum::Json(body)).into_response()
    }
}
