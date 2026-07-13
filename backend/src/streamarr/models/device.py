"""Device model for tracking user devices"""

import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Device(Base):
    """Track user devices for session management and analytics"""

    __tablename__ = "device"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Foreign key to user
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )

    # Device identification
    device_id: Mapped[str] = mapped_column(index=True)  # Frontend-generated UUID

    # Device information
    name: Mapped[str | None] = mapped_column()  # User-defined device name
    browser: Mapped[str | None] = mapped_column()
    platform: Mapped[str | None] = mapped_column()
    user_agent: Mapped[str | None] = mapped_column()
    language: Mapped[str | None] = mapped_column()

    # Additional device info as JSON
    device_info: Mapped[dict | None] = mapped_column(JSON)

    # Activity tracking
    last_activity: Mapped[datetime] = mapped_column(server_default=func.now())
    last_ip_address: Mapped[str | None] = mapped_column()

    # Status
    is_active: Mapped[bool] = mapped_column(default=True)
    is_trusted: Mapped[bool] = mapped_column(default=False)

    # Current playback status (updated via WebSocket)
    is_playing: Mapped[bool] = mapped_column(default=False)
    current_media_type: Mapped[str | None] = (
        mapped_column()
    )  # 'movie', 'episode', 'music', etc.
    current_media_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid, nullable=True
    )
    current_media_title: Mapped[str | None] = (
        mapped_column()
    )  # Cached title for display
    current_playback_position: Mapped[int] = mapped_column(
        default=0
    )  # Position in seconds
    current_playback_duration: Mapped[int] = mapped_column(
        default=0
    )  # Duration in seconds
    playback_updated_at: Mapped[datetime | None] = mapped_column(nullable=True)

    # Relationships
    user = relationship("User", back_populates="devices")
