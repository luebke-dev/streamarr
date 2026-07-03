use crate::api::AppState;
use axum::extract::State;
use axum::http::StatusCode;
use axum::response::IntoResponse;
use axum::Json;
use serde_json::json;

pub async fn health(State(state): State<AppState>) -> impl IntoResponse {
    let session_status = match state.session.read().await.as_ref() {
        Some(s) if !s.is_invalid() => "connected",
        Some(_) => "invalid",
        None => "absent",
    };

    let code = if session_status == "connected" {
        StatusCode::OK
    } else {
        StatusCode::SERVICE_UNAVAILABLE
    };

    (code, Json(json!({ "status": "ok", "spotify": session_status })))
}
