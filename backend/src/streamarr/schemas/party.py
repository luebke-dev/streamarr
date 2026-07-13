"""Schemas for watch party API."""

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


# Request schemas
class WatchPartyCreate(BaseModel):
    """Schema for creating a new watch party."""

    name: str | None = None
    allow_control: bool = False
    media_id: uuid.UUID | None = None
    media_type: Literal["movie", "episode"] | None = None


class WatchPartyJoin(BaseModel):
    """Schema for joining a watch party via code."""

    party_code: str = Field(min_length=6, max_length=6)


class WatchPartyUpdate(BaseModel):
    """Schema for updating watch party settings."""

    name: str | None = None
    allow_control: bool | None = None
    media_id: uuid.UUID | None = None
    media_type: Literal["movie", "episode"] | None = None


class PlaybackSync(BaseModel):
    """Schema for synchronizing playback state."""

    current_time: float = Field(ge=0)
    is_playing: bool
    playback_rate: float = Field(default=1.0, ge=0.25, le=2.0)


# Response schemas
class WatchPartyMemberResponse(BaseModel):
    """Schema for watch party member information."""

    guid: uuid.UUID
    user_id: uuid.UUID
    username: str  # From User model
    is_host: bool
    is_connected: bool
    last_position: float | None
    last_heartbeat: datetime
    joined_at: datetime


class WatchPartyResponse(BaseModel):
    """Schema for watch party information."""

    guid: uuid.UUID
    party_code: str
    name: str | None
    owner_id: uuid.UUID
    media_id: uuid.UUID | None
    media_type: str | None
    media_title: str | None
    current_time: float
    adjusted_current_time: float | None = None
    is_playing: bool
    playback_rate: float
    last_sync_at: datetime
    is_active: bool
    allow_control: bool
    created_at: datetime
    expires_at: datetime
    members: list[WatchPartyMemberResponse] = []


class WatchPartyListResponse(BaseModel):
    """Schema for listing watch parties."""

    guid: uuid.UUID
    party_code: str
    name: str | None
    owner_name: str | None = None
    media_title: str | None
    member_count: int
    is_active: bool
    is_owner: bool
    created_at: datetime


class WatchPartyAdminResponse(BaseModel):
    """Schema for admin listing of watch parties."""

    guid: uuid.UUID
    party_code: str
    name: str | None
    owner_name: str
    media_title: str | None
    member_count: int
    connected_count: int
    is_active: bool
    allow_control: bool
    created_at: datetime
    expires_at: datetime
