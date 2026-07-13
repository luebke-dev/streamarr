"""Client log ingestion endpoint."""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator

from streamarr.api.dependencies import CurrentUser
from streamarr.api.rate_limit import rate_limit

router = APIRouter()
logger = logging.getLogger("streamarr.client")

ClientLogLevel = Literal["debug", "info", "warning", "error", "critical"]

# Bounds on the free-form ``context`` object so an authenticated client cannot
# push arbitrarily large/deep payloads into the backend logging pipeline.
_MAX_CONTEXT_BYTES = 8192
_MAX_CONTEXT_NODES = 100
_MAX_CONTEXT_DEPTH = 6


def _count_nodes(obj: Any, depth: int) -> int:
    if depth > _MAX_CONTEXT_DEPTH:
        raise ValueError("context is nested too deeply")
    count = 0
    if isinstance(obj, dict):
        count += len(obj)
        for value in obj.values():
            count += _count_nodes(value, depth + 1)
    elif isinstance(obj, list):
        count += len(obj)
        for value in obj:
            count += _count_nodes(value, depth + 1)
    return count


class ClientLogRequest(BaseModel):
    level: ClientLogLevel = "info"
    message: str = Field(..., min_length=1, max_length=4096)
    source: str | None = Field(None, max_length=128)
    url: str | None = Field(None, max_length=2048)
    user_agent: str | None = Field(None, max_length=512)
    context: dict | None = None

    @field_validator("context")
    @classmethod
    def _bound_context(cls, value: dict | None) -> dict | None:
        if value is None:
            return value
        if _count_nodes(value, 1) > _MAX_CONTEXT_NODES:
            raise ValueError("context has too many entries")
        try:
            serialized = json.dumps(value, default=str)
        except (TypeError, ValueError) as exc:
            raise ValueError("context must be JSON-serializable") from exc
        if len(serialized.encode("utf-8")) > _MAX_CONTEXT_BYTES:
            raise ValueError("context payload is too large")
        return value


@router.post(
    "",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[
        Depends(
            rate_limit(max_calls=120, window_seconds=60, scope="client_logs")
        )
    ],
)
async def ingest_client_log(payload: ClientLogRequest, current_user: CurrentUser):
    """Write a client-side log message to backend logging."""
    log_method = getattr(logger, payload.level)
    log_method(
        payload.message,
        extra={
            "client_source": payload.source,
            "client_url": payload.url,
            "client_user_agent": payload.user_agent,
            "client_context": payload.context or {},
            "user_guid": str(current_user.guid),
        },
    )
