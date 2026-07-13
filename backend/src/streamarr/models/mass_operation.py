import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, types
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


class MassOperationRunStatus(_CaseInsensitiveStrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"


class MassOperationRule(Base):
    __tablename__ = "mass_operation_rule"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()

    # Same filter DSL as SmartCollectionRule.filters — selects target items.
    target_filter: Mapped[dict] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    # Action descriptor:
    # {"type": "set_label", "value": ["4K Available"]}
    # {"type": "set_genre", "value": [...], "mode": "add" | "replace"}
    action: Mapped[dict] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )

    # Optional cron — if NULL the rule is manual-only.
    schedule_cron: Mapped[str | None] = mapped_column()
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    is_system: Mapped[bool] = mapped_column(default=False, index=True)

    last_run_at: Mapped[datetime | None] = mapped_column()
    next_run_at: Mapped[datetime | None] = mapped_column(index=True)
    last_run_status: Mapped[MassOperationRunStatus | None] = mapped_column()
    last_run_error: Mapped[str | None] = mapped_column()

    runs = relationship(
        "MassOperationRun", back_populates="rule", cascade="all, delete-orphan"
    )


class MassOperationRun(Base):
    __tablename__ = "mass_operation_run"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    rule_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("mass_operation_rule.guid", ondelete="CASCADE"),
        index=True,
    )

    started_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    completed_at: Mapped[datetime | None] = mapped_column()
    status: Mapped[MassOperationRunStatus] = mapped_column(
        default=MassOperationRunStatus.PENDING, index=True
    )

    dry_run: Mapped[bool] = mapped_column(default=False)
    items_matched: Mapped[int] = mapped_column(default=0)
    items_updated: Mapped[int] = mapped_column(default=0)
    items_skipped: Mapped[int] = mapped_column(default=0)

    duration_ms: Mapped[int | None] = mapped_column()
    error: Mapped[str | None] = mapped_column()

    rule = relationship("MassOperationRule", back_populates="runs")
