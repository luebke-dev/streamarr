"""Schemas for play tokens."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class PlayTokenCreate(BaseModel):
    """Schema for creating a new play token."""

    user_guid: UUID
    content_type: str  # "movie", "episode", "music"
    content_id: UUID
    file_path: str | None = None


class PlayToken(BaseModel):
    """Schema for a play token stored in Redis."""

    token: str
    user_guid: str
    content_type: str  # "movie", "episode", "music"
    content_id: str
    file_path: str | None = None
    # Session tracking
    session_id: str | None = None  # Transcoding session if started
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_redis_dict(self) -> dict:
        """Convert to dict for Redis storage."""
        return {
            "token": self.token,
            "user_guid": self.user_guid,
            "content_type": self.content_type,
            "content_id": self.content_id,
            "file_path": self.file_path,
            "session_id": self.session_id,
            "created_at": self.created_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
        }

    @classmethod
    def from_redis_dict(cls, data: dict) -> "PlayToken":
        """Create from Redis dict."""
        return cls(
            token=data["token"],
            user_guid=data["user_guid"],
            content_type=data["content_type"],
            content_id=data["content_id"],
            file_path=data.get("file_path"),
            session_id=data.get("session_id"),
            created_at=datetime.fromisoformat(data["created_at"])
            if data.get("created_at")
            else datetime.now(UTC),
            last_accessed_at=datetime.fromisoformat(data["last_accessed_at"])
            if data.get("last_accessed_at")
            else datetime.now(UTC),
        )


class PlayTokenRead(BaseModel):
    """Schema for reading a play token (API response)."""

    token: str
    content_type: str
    content_id: str
    session_id: str | None = None
    created_at: datetime
    last_accessed_at: datetime
    # Playback metadata (not stored in token, returned separately)
    duration: float | None = None
    start_position: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    is_low_quality: bool = False
    availability: str = "streamable"  # "streamable", "downloadable"
    audio_track: int | None = None
    subtitle_stream_index: int | None = None
    media_source_id: str | None = None
    profile_id: str | None = None
    device_guid: str | None = None
    playback_method: str | None = None
    direct_stream: bool = False

    @classmethod
    def from_token(cls, token: PlayToken, **kwargs) -> "PlayTokenRead":
        """Create from PlayToken with additional metadata."""
        # Remove session_id from kwargs if present to avoid duplicate
        session_id = kwargs.pop("session_id", None) or token.session_id
        return cls(
            token=token.token,
            content_type=token.content_type,
            content_id=token.content_id,
            session_id=session_id,
            created_at=token.created_at,
            last_accessed_at=token.last_accessed_at,
            **kwargs,
        )
