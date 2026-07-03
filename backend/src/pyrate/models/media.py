"""Unified media models for all content types."""

import uuid
from datetime import UTC, datetime
from enum import Enum, StrEnum

from sqlalchemy import BigInteger, Column, ForeignKey, Index, Table, inspect, types
from sqlalchemy import Enum as SQLEnum
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .genre import Genre
from .platform import Platform

# Association table for many-to-many relationship between MediaItem and Genre
media_genre_table = Table(
    "media_genre",
    Base.metadata,
    Column(
        "media_item_guid",
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "genre_id",
        types.Integer,
        ForeignKey("genre.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", types.DateTime(timezone=True), default=lambda: datetime.now(UTC)),
)


# Association table for many-to-many relationship between MediaItem and Platform
media_platform_table = Table(
    "media_platform",
    Base.metadata,
    Column(
        "media_item_guid",
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column(
        "platform_id",
        types.Integer,
        ForeignKey("platform.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("created_at", types.DateTime(timezone=True), default=lambda: datetime.now(UTC)),
)


def _get_media_type_enum():
    """
    Dynamically generate MediaType enum from registered library plugins.

    This collects all media item types from all plugins, including
    hierarchical sub-types (e.g. SEASONS, EPISODES from the shows plugin).
    """
    from pyrate.libraries import get_all_media_item_types

    # Get all media item types from registered plugins
    media_types = get_all_media_item_types()

    # If no plugins registered yet (during import), use defaults
    if not media_types:
        media_types = [
            "MOVIES",
            "SHOWS",
            "SEASONS",
            "EPISODES",
            "GAMES",
            "MUSIC",
            "ARTISTS",
            "ALBUMS",
            "SONGS",
            "BOOKS",
            "AUDIOBOOKS",
            "AUDIOBOOK_CHAPTERS",
        ]

    # Create enum dynamically - both key and value should be uppercase
    enum_dict = {mt.upper(): mt.upper() for mt in media_types}
    return Enum("MediaType", enum_dict, type=str)


# Generate MediaType enum from plugins
MediaType = _get_media_type_enum()


class AvailabilityStatus(StrEnum):
    """Availability status for media."""

    UNKNOWN = "unknown"
    AVAILABLE = "available"
    DOWNLOADABLE = "downloadable"


class MediaItem(Base):
    """
    Unified table for all media items (movies, shows, episodes, games, albums, books).

    This replaces separate Movie, Show, Episode, Game, Album, Track, Book tables.
    """

    __tablename__ = "media_item"

    def __init__(self, **kwargs):
        """Accept legacy constructor fields without reintroducing old columns."""
        for key, value in kwargs.items():
            if not hasattr(type(self), key):
                raise TypeError(
                    f"{key!r} is an invalid keyword argument for MediaItem"
                )
            setattr(self, key, value)
        if "genres" not in kwargs:
            self.genres = []
        if "platforms" not in kwargs:
            self.platforms = []

    @property
    def library_guid(self) -> uuid.UUID | None:
        """Deprecated compatibility shim; media type now determines library."""
        return getattr(self, "_legacy_library_guid", None)

    @library_guid.setter
    def library_guid(self, value: uuid.UUID | None) -> None:
        self._legacy_library_guid = value

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Media type determines what kind of content this is
    media_type: Mapped[MediaType] = mapped_column(
        SQLEnum(MediaType), nullable=False, index=True
    )

    # Common metadata fields
    title: Mapped[str] = mapped_column(index=True, nullable=False)
    original_title: Mapped[str | None] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()
    tagline: Mapped[str | None] = mapped_column()

    # Release/Air dates
    release_date: Mapped[datetime | None] = mapped_column()

    # Visual assets
    poster_path: Mapped[str | None] = mapped_column()
    backdrop_path: Mapped[str | None] = mapped_column()

    # Status tracking
    availability_status: Mapped[AvailabilityStatus] = mapped_column(
        SQLEnum(AvailabilityStatus), default=AvailabilityStatus.UNKNOWN, index=True
    )

    # Age rating: raw cert string (e.g. "FSK 16", "PG-13") + normalized minimum
    # viewer age in years. `min_age` is what the parental-control filter reads.
    content_rating: Mapped[str | None] = mapped_column()
    min_age: Mapped[int | None] = mapped_column(index=True)

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    last_searched_at: Mapped[datetime | None] = mapped_column()
    last_metadata_updated_at: Mapped[datetime | None] = mapped_column()

    # Monitoring (favorites auto-download / upgrades). An item is "monitored"
    # when it (or a favorited ancestor) should be auto-acquired and kept.
    # ``monitored_source``: "favorite" (set by the favorite hook) | "manual".
    # ``monitored_reconciled_at``: last time the backfill/reconcile fanned out.
    monitored: Mapped[bool] = mapped_column(default=False, index=True)
    monitored_source: Mapped[str | None] = mapped_column()
    monitored_reconciled_at: Mapped[datetime | None] = mapped_column()

    # Hierarchical relationships (for shows/seasons/episodes, albums/tracks)
    parent_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=True,
    )

    # Order/numbering (season number, episode number, track number, etc.)
    sequence_number: Mapped[int | None] = mapped_column(index=True)

    # Type-specific data stored as JSON (for extensibility)
    # E.g., for games: platforms, for music: artist info, for shows: series type
    extra_data: Mapped[str | None] = mapped_column()  # JSON string

    # Relationships
    parent = relationship("MediaItem", remote_side=[guid], foreign_keys=[parent_guid])
    files = relationship(
        "MediaFile", back_populates="media_item", cascade="all, delete-orphan"
    )
    releases = relationship(
        "MediaRelease", back_populates="media_item", cascade="all, delete-orphan"
    )
    external_ids = relationship(
        "MediaExternalId", back_populates="media_item", cascade="all, delete-orphan"
    )
    favorites = relationship(
        "Favorite", back_populates="media_item", cascade="all, delete-orphan"
    )
    viewing_history = relationship(
        "ViewingHistory", back_populates="media_item", cascade="all, delete-orphan"
    )
    markers = relationship(
        "MediaMarker", back_populates="media_item", cascade="all, delete-orphan"
    )
    translations = relationship(
        "MediaItemTranslation", back_populates="media_item", cascade="all, delete-orphan"
    )
    genres = relationship(
        Genre, secondary=media_genre_table, backref="media_items", lazy="noload"
    )
    platforms = relationship(
        Platform, secondary=media_platform_table, backref="media_items", lazy="noload"
    )
    cast = relationship(
        "MediaCast",
        back_populates="media_item",
        cascade="all, delete-orphan",
        order_by="MediaCast.cast_order",
    )

    @property
    def duration(self) -> float | None:
        """Best-known duration from loaded media files."""
        if "files" in inspect(self).unloaded:
            return None
        durations = [
            media_file.duration
            for media_file in self.files
            if media_file.duration is not None
        ]
        return max(durations) if durations else None

    __table_args__ = (
        Index("ix_media_item_parent_sequence", "parent_guid", "sequence_number"),
    )


class MediaExternalId(Base):
    """Unified table for external IDs (TMDB, IGDB, Spotify, etc.)."""

    __tablename__ = "media_external_id"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    provider: Mapped[str] = mapped_column(
        index=True, nullable=False
    )  # "tmdb", "igdb", "spotify", etc.
    external_id: Mapped[str] = mapped_column(index=True, nullable=False)

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    media_item = relationship("MediaItem", back_populates="external_ids")

    __table_args__ = (
        Index("ix_media_external_id_provider_external", "provider", "external_id"),
    )


class MediaFile(Base):
    """
    Unified table for all media files.

    Replaces MovieFile, EpisodeFile, GameFile, AlbumFile, etc.
    """

    __tablename__ = "media_file"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Reference to media item
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # File location
    file_path: Mapped[str] = mapped_column(index=True, nullable=False)
    file_name: Mapped[str | None] = mapped_column()
    file_size: Mapped[int | None] = mapped_column(BigInteger)

    # Media properties
    duration: Mapped[float | None] = mapped_column()  # For video/audio
    width: Mapped[int | None] = mapped_column()  # For video
    height: Mapped[int | None] = mapped_column()  # For video
    codec: Mapped[str | None] = mapped_column()
    bitrate: Mapped[int | None] = mapped_column()

    # Stream information (stored as JSON)
    probe_data: Mapped[str | None] = mapped_column()  # JSON with all streams

    # Audio fingerprint for intro detection (fpcalc -raw output)
    chromaprint_raw: Mapped[str | None] = mapped_column(nullable=True)

    # Quality/format info
    quality: Mapped[str | None] = mapped_column(index=True)
    format: Mapped[str | None] = mapped_column()

    # Quality-profile tracking: which release this file came from and its
    # parsed ladder rank + additive score, so upgrade decisions can compare
    # the current file against a candidate without re-deriving from probe data.
    source_release_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("media_release.guid", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
    quality_rank: Mapped[int | None] = mapped_column()
    quality_score: Mapped[float | None] = mapped_column()

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )
    imported_at: Mapped[datetime | None] = mapped_column()

    # Relationships
    media_item = relationship("MediaItem", back_populates="files")


class MediaRelease(Base):
    """
    Unified table for all releases.

    Replaces MovieRelease, EpisodeRelease, GameRelease, AlbumRelease, etc.
    """

    __tablename__ = "media_release"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    # Reference to media item
    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Release information
    title: Mapped[str] = mapped_column(index=True, nullable=False)
    size: Mapped[int | None] = mapped_column(BigInteger)
    quality: Mapped[str | None] = mapped_column(index=True)

    # Structured release metadata (resolution, codec, source, languages, etc.)
    # Extracted from release title by library plugins
    # Use JSONB for PostgreSQL, JSON for other databases (like SQLite for testing)
    release_metadata: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Scoring for release selection
    score: Mapped[int] = mapped_column(default=0, index=True)

    # Blacklist reason — NULL means the release is usable,
    # any non-null value means it was blacklisted with that reason.
    blacklisted_reason: Mapped[str | None] = mapped_column(
        nullable=True, default=None, index=True
    )

    # Source information
    indexer_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("indexer.guid", ondelete="SET NULL"),
        index=True,
    )

    # Download links
    links = relationship(
        "MediaReleaseLink", back_populates="release", cascade="all, delete-orphan"
    )

    # Timestamps
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    publish_date: Mapped[datetime | None] = mapped_column()

    # Relationships
    media_item = relationship("MediaItem", back_populates="releases")
    indexer = relationship("Indexer", foreign_keys=[indexer_guid])


class MediaReleaseLink(Base):
    """
    Unified table for release download links.

    Replaces MovieReleaseLink, EpisodeReleaseLink, GameReleaseLink, AlbumReleaseLink.
    """

    __tablename__ = "media_release_link"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )

    media_release_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_release.guid", ondelete="CASCADE"),
        index=True,
        nullable=False,
    )

    # Download link information
    link: Mapped[str] = mapped_column(nullable=False)
    link_type: Mapped[str] = mapped_column(index=True)  # "nzb", "torrent", "magnet"

    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    blacklisted_reason: Mapped[str | None] = mapped_column(default=None)

    # Relationships
    release = relationship("MediaRelease", back_populates="links")
    downloads = relationship("Download", back_populates="media_release_link")
