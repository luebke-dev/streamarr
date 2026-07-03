"""Schemas for media markers (intro/outro/credits/song/ad)."""

import uuid
from datetime import datetime

from pydantic import BaseModel

from pyrate.schemas.base import BaseSchema


class MediaMarkerCreate(BaseModel):
    marker_type: str  # "intro", "outro", "credits", "song", "ad"
    start_seconds: float
    end_seconds: float
    source: str = "manual"
    confidence: float | None = None
    label: str | None = None  # Optional label, e.g. song title


class MediaMarkerUpdate(BaseModel):
    start_seconds: float | None = None
    end_seconds: float | None = None
    label: str | None = None


class MediaMarkerRead(BaseSchema):
    guid: uuid.UUID
    media_item_guid: uuid.UUID
    marker_type: str
    source: str
    start_seconds: float
    end_seconds: float
    confidence: float | None
    label: str | None = None
    created_at: datetime
    updated_at: datetime


class PlayerMarker(BaseModel):
    """Single marker for the player."""
    marker_type: str
    start: float
    end: float
    label: str | None = None


class MediaMarkersForPlayer(BaseModel):
    """Marker data for the player — list-based to support arbitrary types."""

    # Legacy fields for backwards compatibility with existing player code
    intro_start: float | None = None
    intro_end: float | None = None
    outro_start: float | None = None
    outro_end: float | None = None
    credits_start: float | None = None
    credits_end: float | None = None

    # Full marker list for new player features
    markers: list[PlayerMarker] = []
