import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class _CaseInsensitiveStrEnum(StrEnum):
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            upper = value.upper()
            for member in cls:
                if member.value == upper:
                    return member
        return None


class SmartCollectionMediaType(_CaseInsensitiveStrEnum):
    MOVIE = "MOVIE"
    SHOW = "SHOW"


class SmartCollectionSyncMode(_CaseInsensitiveStrEnum):
    APPEND = "APPEND"
    SYNC = "SYNC"


class SmartCollectionRunStatus(_CaseInsensitiveStrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class SmartCollectionRule(Base):
    __tablename__ = "smart_collection_rule"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # The List this rule populates. Nullable until first successful run creates it.
    list_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("list.guid", ondelete="SET NULL"),
        unique=True,
    )

    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()

    media_type: Mapped[SmartCollectionMediaType] = mapped_column(index=True)

    # Registry key for the builder (e.g. "tmdb_chart", "trakt_list").
    builder_type: Mapped[str] = mapped_column(index=True)
    # Builder-specific parameters (e.g. {"chart": "popular", "language": "de"}).
    builder_config: Mapped[dict] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    # Filter DSL applied to fetched refs (min_rating, year_min, genre_in, ...).
    filters: Mapped[dict] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )

    sync_mode: Mapped[SmartCollectionSyncMode] = mapped_column(
        default=SmartCollectionSyncMode.SYNC
    )
    item_limit: Mapped[int | None] = mapped_column()

    schedule_cron: Mapped[str] = mapped_column()  # e.g. "0 6 * * *"
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    # System-seeded rule (Kometa defaults). Users can disable but not delete.
    is_system: Mapped[bool] = mapped_column(default=False, index=True)

    last_run_at: Mapped[datetime | None] = mapped_column()
    next_run_at: Mapped[datetime | None] = mapped_column(index=True)
    last_run_status: Mapped[SmartCollectionRunStatus | None] = mapped_column()
    last_run_error: Mapped[str | None] = mapped_column()

    runs = relationship(
        "SmartCollectionRun", back_populates="rule", cascade="all, delete-orphan"
    )

    __table_args__ = (
        Index("ix_smart_collection_rule_enabled_next", "enabled", "next_run_at"),
    )


class SmartCollectionRun(Base):
    __tablename__ = "smart_collection_run"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    rule_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("smart_collection_rule.guid", ondelete="CASCADE"),
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[SmartCollectionRunStatus] = mapped_column(
        default=SmartCollectionRunStatus.PENDING, index=True
    )

    items_fetched: Mapped[int] = mapped_column(default=0)
    items_filtered: Mapped[int] = mapped_column(default=0)
    items_resolved: Mapped[int] = mapped_column(default=0)
    items_added: Mapped[int] = mapped_column(default=0)
    items_removed: Mapped[int] = mapped_column(default=0)
    items_unresolved: Mapped[int] = mapped_column(default=0)

    duration_ms: Mapped[int | None] = mapped_column()
    error: Mapped[str | None] = mapped_column()

    rule = relationship("SmartCollectionRule", back_populates="runs")
