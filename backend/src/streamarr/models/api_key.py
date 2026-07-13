"""API key model for non-interactive clients."""

from datetime import UTC, datetime
import uuid

from sqlalchemy import ForeignKey, String, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class ApiKey(Base):
    """Hashed API key issued to a user."""

    __tablename__ = "api_key"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    key_prefix: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    key_hash: Mapped[str] = mapped_column(String(64), unique=True, index=True, nullable=False)
    user_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    created_by_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="SET NULL"),
        nullable=True,
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    last_used_at: Mapped[datetime | None] = mapped_column(nullable=True)
    revoked_at: Mapped[datetime | None] = mapped_column(nullable=True)

    user = relationship("User", foreign_keys=[user_guid], back_populates="api_keys")
    created_by = relationship("User", foreign_keys=[created_by_guid])

