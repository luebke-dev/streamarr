"""Activity log model for admin observability."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Index, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class ActivityLog(Base):
    """Durable admin-visible activity event."""

    __tablename__ = "activity_log"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime] = mapped_column(
        types.DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        index=True,
    )
    actor_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    event_type: Mapped[str] = mapped_column(types.String(100), nullable=False, index=True)
    severity: Mapped[str] = mapped_column(types.String(20), nullable=False, default="info")
    message: Mapped[str] = mapped_column(types.String(1000), nullable=False)
    entity_type: Mapped[str | None] = mapped_column(types.String(100), nullable=True, index=True)
    entity_guid: Mapped[uuid.UUID | None] = mapped_column(types.Uuid, nullable=True, index=True)
    extra_data: Mapped[str | None] = mapped_column(types.Text(), nullable=True)

    actor = relationship("User")

    __table_args__ = (
        Index("ix_activity_log_entity", "entity_type", "entity_guid"),
    )
