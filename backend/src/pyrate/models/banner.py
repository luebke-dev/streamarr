"""Banner models for system-wide announcements."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Banner(Base):
    """System-wide banner announcements."""

    __tablename__ = "banners"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    title: Mapped[str] = mapped_column(index=True)
    message: Mapped[str]
    banner_type: Mapped[str] = mapped_column(
        default="info", index=True
    )  # info, warning, error, success
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    dismissible: Mapped[bool] = mapped_column(
        default=True, index=True
    )  # Can users dismiss this banner?
    start_date: Mapped[datetime | None] = mapped_column(default=None, index=True)
    end_date: Mapped[datetime | None] = mapped_column(default=None, index=True)
    created_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), index=True
    )
    created_by_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, ForeignKey("user.guid"), index=True
    )
    updated_at: Mapped[datetime | None] = mapped_column(default=None)

    # Relationships
    created_by = relationship(
        "User", back_populates="created_banners", foreign_keys=[created_by_guid]
    )
    dismissed_by = relationship(
        "UserBannerDismissed", back_populates="banner", cascade="all, delete-orphan"
    )


class UserBannerDismissed(Base):
    """Track which banners have been dismissed by which users."""

    __tablename__ = "user_banner_dismissed"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    user_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, ForeignKey("user.guid"), index=True
    )
    banner_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, ForeignKey("banners.guid", ondelete="CASCADE"), index=True
    )
    dismissed_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), index=True
    )

    # Relationships
    user = relationship(
        "User", back_populates="dismissed_banners", foreign_keys=[user_guid]
    )
    banner = relationship(
        "Banner", back_populates="dismissed_by", foreign_keys=[banner_guid]
    )
