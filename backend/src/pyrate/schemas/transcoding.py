"""Schemas for transcoding sessions."""

from datetime import UTC, datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TranscodingSessionCreate(BaseModel):
    """Schema for creating a new transcoding session."""

    session_id: str
    user_guid: UUID | None = None
    user_name: str | None = None
    content_type: str  # "movie", "episode", "music"
    content_id: UUID
    content_title: str | None = None
    container_id: str | None = None
    job_name: str | None = None  # Kubernetes job name
    job_namespace: str | None = None  # Kubernetes namespace
    runtime_type: str = "docker"  # "docker" or "kubernetes"
    video_codec: str | None = "h264"
    audio_codec: str | None = "aac"
    video_bitrate: str | None = None
    audio_bitrate: str | None = "128k"
    resolution: str | None = None
    start_position: float | None = None
    input_path: str | None = None


class TranscodingSession(BaseModel):
    """Schema for a transcoding session stored in Redis."""

    session_id: str
    user_guid: str | None = None
    user_name: str | None = None
    content_type: str  # "movie", "episode", "music"
    content_id: str
    content_title: str | None = None
    container_id: str | None = None
    job_name: str | None = None  # Kubernetes job name
    job_namespace: str | None = None  # Kubernetes namespace
    runtime_type: str = "docker"  # "docker" or "kubernetes"
    video_codec: str | None = "h264"
    audio_codec: str | None = "aac"
    video_bitrate: str | None = None
    audio_bitrate: str | None = "128k"
    resolution: str | None = None
    start_position: float | None = None
    input_path: str | None = None
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    last_accessed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    is_active: bool = True
    status: str = "active"  # active, restarting, failed
    retry_count: int = 0
    last_retry_at: datetime | None = None

    def to_redis_dict(self) -> dict:
        """Convert to dict for Redis storage."""
        return {
            "session_id": self.session_id,
            "user_guid": str(self.user_guid) if self.user_guid else None,
            "user_name": self.user_name,
            "content_type": self.content_type,
            "content_id": str(self.content_id),
            "content_title": self.content_title,
            "container_id": self.container_id,
            "job_name": self.job_name,
            "job_namespace": self.job_namespace,
            "runtime_type": self.runtime_type,
            "video_codec": self.video_codec,
            "audio_codec": self.audio_codec,
            "video_bitrate": self.video_bitrate,
            "audio_bitrate": self.audio_bitrate,
            "resolution": self.resolution,
            "start_position": self.start_position,
            "input_path": self.input_path,
            "started_at": self.started_at.isoformat(),
            "last_accessed_at": self.last_accessed_at.isoformat(),
            "is_active": self.is_active,
            "status": self.status,
            "retry_count": self.retry_count,
            "last_retry_at": self.last_retry_at.isoformat()
            if self.last_retry_at
            else None,
        }

    @classmethod
    def from_redis_dict(cls, data: dict) -> "TranscodingSession":
        """Create from Redis dict."""
        return cls(
            session_id=data["session_id"],
            user_guid=data.get("user_guid"),
            user_name=data.get("user_name"),
            content_type=data["content_type"],
            content_id=data["content_id"],
            content_title=data.get("content_title"),
            container_id=data.get("container_id"),
            job_name=data.get("job_name"),
            job_namespace=data.get("job_namespace"),
            runtime_type=data.get("runtime_type", "docker"),
            video_codec=data.get("video_codec", "h264"),
            audio_codec=data.get("audio_codec", "aac"),
            video_bitrate=data.get("video_bitrate"),
            audio_bitrate=data.get("audio_bitrate", "128k"),
            resolution=data.get("resolution"),
            start_position=data.get("start_position"),
            input_path=data.get("input_path"),
            started_at=datetime.fromisoformat(data["started_at"])
            if data.get("started_at")
            else datetime.now(UTC),
            last_accessed_at=datetime.fromisoformat(data["last_accessed_at"])
            if data.get("last_accessed_at")
            else datetime.now(UTC),
            is_active=data.get("is_active", True),
            status=data.get("status", "active"),
            retry_count=data.get("retry_count", 0),
            last_retry_at=datetime.fromisoformat(data["last_retry_at"])
            if data.get("last_retry_at")
            else None,
        )


class TranscodingSessionRead(BaseModel):
    """Schema for reading a transcoding session (API response)."""

    session_id: str
    user_guid: str | None = None
    user_name: str | None = None
    content_type: str
    content_id: str
    content_title: str | None = None
    container_id: str | None = None
    job_name: str | None = None
    job_namespace: str | None = None
    runtime_type: str = "docker"
    video_codec: str | None = None
    audio_codec: str | None = None
    video_bitrate: str | None = None
    audio_bitrate: str | None = None
    resolution: str | None = None
    start_position: float | None = None
    started_at: datetime
    last_accessed_at: datetime
    is_active: bool
    status: str | None = None  # active, restarting, failed
    container_status: str | None = None  # running, exited, not_found
    transcode_progress: float | None = None  # 0.0-1.0 progress
    transcoded_segments: int | None = None
    total_segments: int | None = None
    duration_seconds: float | None = None

    @classmethod
    def from_session(cls, session: TranscodingSession) -> "TranscodingSessionRead":
        """Create from TranscodingSession."""
        now = datetime.now(UTC)
        duration = (
            (now - session.started_at).total_seconds() if session.started_at else None
        )

        return cls(
            session_id=session.session_id,
            user_guid=session.user_guid,
            user_name=session.user_name,
            content_type=session.content_type,
            content_id=session.content_id,
            content_title=session.content_title,
            container_id=session.container_id,
            job_name=session.job_name,
            job_namespace=session.job_namespace,
            runtime_type=session.runtime_type,
            video_codec=session.video_codec,
            audio_codec=session.audio_codec,
            video_bitrate=session.video_bitrate,
            audio_bitrate=session.audio_bitrate,
            resolution=session.resolution,
            start_position=session.start_position,
            started_at=session.started_at,
            last_accessed_at=session.last_accessed_at,
            is_active=session.is_active,
            status=getattr(session, "status", None),
            duration_seconds=duration,
        )


class TranscodingSessionsResponse(BaseModel):
    """Response schema for listing transcoding sessions."""

    sessions: list[TranscodingSessionRead]
    total: int
    active_count: int
