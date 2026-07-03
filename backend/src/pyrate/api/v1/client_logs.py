"""Client log ingestion endpoint."""

from __future__ import annotations

import logging
from typing import Literal

from fastapi import APIRouter, status
from pydantic import BaseModel, Field

from pyrate.api.dependencies import CurrentUser

router = APIRouter()
logger = logging.getLogger("pyrate.client")

ClientLogLevel = Literal["debug", "info", "warning", "error", "critical"]


class ClientLogRequest(BaseModel):
    level: ClientLogLevel = "info"
    message: str = Field(..., min_length=1, max_length=4096)
    source: str | None = Field(None, max_length=128)
    url: str | None = Field(None, max_length=2048)
    user_agent: str | None = Field(None, max_length=512)
    context: dict | None = None


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
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

