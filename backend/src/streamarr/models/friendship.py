import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, UniqueConstraint, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class FriendshipStatus(StrEnum):
    pending = "pending"
    accepted = "accepted"
    blocked = "blocked"


class Friendship(Base):
    """Freundschaftsverbindung zwischen zwei Benutzern"""

    __tablename__ = "friendship"
    __table_args__ = (
        UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
    )

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )

    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Wer hat die Anfrage gestellt
    requester_id: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # An wen wurde die Anfrage gestellt
    addressee_id: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    status: Mapped[FriendshipStatus] = mapped_column(default=FriendshipStatus.pending)

    # Relationships
    requester = relationship(
        "User", foreign_keys=[requester_id], back_populates="sent_friend_requests"
    )
    addressee = relationship(
        "User", foreign_keys=[addressee_id], back_populates="received_friend_requests"
    )
