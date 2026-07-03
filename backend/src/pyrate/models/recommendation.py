"""Recommendation system models.

Holds working material for the RecommendationService. The actual
recommendation output lives in per-user System Lists (see
pyrate.models.list) — this table is only read by the builder.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import ForeignKey, Enum as SAEnum, PrimaryKeyConstraint, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from pyrate.models.media import MediaType

from . import Base


class UserProfileVector(Base):
    """Per-(user, media_type) feature vector used by the recommendation builder."""

    __tablename__ = "user_profile_vector"
    __table_args__ = (
        PrimaryKeyConstraint("user_guid", "media_type", name="pk_user_profile_vector"),
    )

    user_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        index=True,
    )
    media_type: Mapped[MediaType] = mapped_column(
        SAEnum(
            MediaType,
            values_callable=lambda cls: [e.value for e in cls],
            native_enum=False,
            name="mediatype",
        ),
        index=True,
    )

    genre_weights: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    top_cast_guids: Mapped[list | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=list
    )
    language_weights: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=dict
    )
    friend_guids: Mapped[list | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=list
    )

    updated_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
