import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Invite(Base):
    """Invite-code model."""

    __tablename__ = "invite"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())

    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    created_by_user_id: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, ForeignKey("user.guid", ondelete="CASCADE"), nullable=False
    )

    token: Mapped[str] = mapped_column(unique=True, index=True)

    expires_at: Mapped[datetime] = mapped_column()

    is_active: Mapped[bool] = mapped_column(default=True)

    is_used: Mapped[bool] = mapped_column(default=False)

    used_at: Mapped[datetime | None] = mapped_column()

    used_by_user_id: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid, ForeignKey("user.guid", ondelete="SET NULL"), nullable=True
    )

    description: Mapped[str | None] = mapped_column()

    max_uses: Mapped[int] = mapped_column(default=1)

    current_uses: Mapped[int] = mapped_column(default=0)

    # Relationships
    created_by = relationship(
        "User", foreign_keys=[created_by_user_id], back_populates="created_invites"
    )
    used_by = relationship(
        "User", foreign_keys=[used_by_user_id], back_populates="used_invites"
    )
