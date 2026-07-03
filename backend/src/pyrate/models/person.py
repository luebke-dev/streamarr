"""Person and media cast models for actor/crew tracking."""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base

if TYPE_CHECKING:
    from pyrate.models.media import MediaItem


class Person(Base):
    """Person model representing actors, directors, crew members, etc."""

    __tablename__ = "person"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # External IDs
    tmdb_id: Mapped[int | None] = mapped_column(unique=True, index=True)

    # Person details
    name: Mapped[str] = mapped_column(index=True, nullable=False)
    profile_path: Mapped[str | None] = mapped_column()
    known_for_department: Mapped[str | None] = mapped_column()

    # Extended biography fields
    biography: Mapped[str | None] = mapped_column(Text)
    birthday: Mapped[date | None] = mapped_column()
    deathday: Mapped[date | None] = mapped_column()
    place_of_birth: Mapped[str | None] = mapped_column()
    homepage: Mapped[str | None] = mapped_column()

    # Metadata import tracking
    metadata_imported: Mapped[bool] = mapped_column(default=False)
    metadata_imported_at: Mapped[datetime | None] = mapped_column()

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Relationships
    cast_entries: Mapped[list["MediaCast"]] = relationship(
        "MediaCast", back_populates="person", cascade="all, delete-orphan"
    )


class MediaCast(Base):
    """Association model linking persons to media items with role information."""

    __tablename__ = "media_cast"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # References
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )
    person_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("person.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Role information
    character: Mapped[str | None] = mapped_column()  # Character name (for actors)
    department: Mapped[str | None] = mapped_column()  # e.g. "Acting", "Directing"
    job: Mapped[str | None] = mapped_column()  # e.g. "Director", "Producer"
    cast_order: Mapped[int | None] = mapped_column()  # Display order

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    # Relationships
    media_item: Mapped["MediaItem"] = relationship("MediaItem", back_populates="cast")
    person: Mapped["Person"] = relationship("Person", back_populates="cast_entries")
