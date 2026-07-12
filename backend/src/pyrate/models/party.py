"""Models for watch parties (synchronized viewing sessions)."""

import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base

if TYPE_CHECKING:
    from pyrate.models.user import User


# Fixed, unambiguous uppercase alphabet (no I/O/0/1) drawn from directly with
# ``secrets.choice`` so every character contributes full entropy. Uppercasing a
# base64 token instead would case-fold letters and collapse the keyspace.
_SESSION_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
_SESSION_CODE_LENGTH = 8


def generate_session_code() -> str:
    """Generate a random uppercase session code with adequate entropy."""
    return "".join(
        secrets.choice(_SESSION_CODE_ALPHABET) for _ in range(_SESSION_CODE_LENGTH)
    )


class WatchParty(Base):
    """
    Watch party session for synchronized viewing.

    Allows multiple users to watch the same content together in real-time,
    with synchronized playback controls. These are short-lived, on-demand sessions.
    """

    __tablename__ = "watch_party"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Party identification
    party_code: Mapped[str] = mapped_column(
        index=True, unique=True, default=generate_session_code
    )

    # Party metadata
    name: Mapped[str | None] = mapped_column()  # Optional party name

    # Owner/Host
    owner_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.guid"), index=True)

    # Media information (optional - can be set later)
    media_id: Mapped[uuid.UUID | None] = mapped_column(types.Uuid, index=True)
    media_type: Mapped[str | None] = mapped_column(
        index=True
    )  # 'movie', 'episode', etc.
    media_title: Mapped[str | None] = mapped_column()  # Cached for display

    # Playback state
    current_time: Mapped[float] = mapped_column(
        default=0.0
    )  # Current position in seconds
    is_playing: Mapped[bool] = mapped_column(default=False)
    playback_rate: Mapped[float] = mapped_column(default=1.0)
    last_sync_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Session status
    is_active: Mapped[bool] = mapped_column(default=True, index=True)
    ended_at: Mapped[datetime | None] = mapped_column()

    # Settings
    allow_control: Mapped[bool] = mapped_column(
        default=False
    )  # Allow non-hosts to control playback

    # Expiration
    expires_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC) + timedelta(hours=24)
    )

    # Relationships
    owner: Mapped["User"] = relationship(
        back_populates="owned_watch_parties", foreign_keys=[owner_id]
    )
    members: Mapped[list["WatchPartyMember"]] = relationship(
        back_populates="party", cascade="all, delete-orphan"
    )


class WatchPartyMember(Base):
    """
    Member of a watch party session.

    Tracks who is participating in a watch party and their status.
    """

    __tablename__ = "watch_party_member"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Foreign keys
    party_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("watch_party.guid"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.guid"), index=True)

    # Member status
    is_host: Mapped[bool] = mapped_column(default=False)
    is_connected: Mapped[bool] = mapped_column(default=True, index=True)

    # Playback tracking (for debugging/sync issues)
    last_position: Mapped[float | None] = mapped_column()  # Last reported position
    last_heartbeat: Mapped[datetime] = mapped_column(server_default=func.now())

    # Metadata
    joined_at: Mapped[datetime] = mapped_column(server_default=func.now())
    left_at: Mapped[datetime | None] = mapped_column()

    # Relationships
    party: Mapped["WatchParty"] = relationship(back_populates="members")
    user: Mapped["User"] = relationship(back_populates="watch_party_memberships")
