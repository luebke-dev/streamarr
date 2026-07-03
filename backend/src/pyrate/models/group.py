import uuid
from datetime import datetime

from sqlalchemy import JSON, ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Group(Base):
    """User groups with inherited permissions"""

    __tablename__ = "group"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    # Group details
    name: Mapped[str] = mapped_column(index=True, unique=True)
    description: Mapped[str | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(default=True)

    # Library Access Permissions
    allowed_libraries: Mapped[list[str]] = mapped_column(
        JSON, default=list
    )  # ['movies', 'series', 'games', 'books', 'music']

    # Streaming Permissions
    max_concurrent_streams: Mapped[int] = mapped_column(
        default=1
    )  # Anzahl gleichzeitiger Streams
    max_game_streams: Mapped[int] = mapped_column(
        default=0
    )  # Anzahl gleichzeitiger Game-Streams

    # Download Permissions (rate limiting)
    offline_download_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max offline downloads (None = unlimited)
    offline_download_period_minutes: Mapped[int] = mapped_column(
        default=1440
    )  # Time period in minutes (default: 1440 = per day)

    # Series/Show Automation (rate limiting)
    prefetch_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max automatic prefetches (None = unlimited)
    prefetch_period_minutes: Mapped[int] = mapped_column(
        default=1440
    )  # Time period in minutes (default: 1440 = per day)

    on_demand_fetch_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max on-demand fetches (None = unlimited)
    on_demand_fetch_period_minutes: Mapped[int] = mapped_column(
        default=1440
    )  # Time period in minutes (default: 1440 = per day)

    # Quality Permissions
    max_video_quality: Mapped[str | None] = mapped_column(
        default="uhd"
    )  # Maximum video quality: 'sd', 'hd', 'fhd', 'uhd' (None = no video access)
    max_audio_quality: Mapped[str | None] = mapped_column(
        default="lossless"
    )  # Maximum audio quality: 'lossy', 'lossless' (None = no audio access)

    # Indexer Permissions (flexible time periods)
    indexer_api_requests_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max requests (None = unlimited)
    indexer_api_requests_period_minutes: Mapped[int] = mapped_column(
        default=60
    )  # Time period in minutes (default: 60 = per hour)

    indexer_downloads_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max downloads (None = unlimited)
    indexer_downloads_period_minutes: Mapped[int] = mapped_column(
        default=1440
    )  # Time period in minutes (default: 1440 = per day)

    # Playback Permissions (rate limiting)
    playback_limit: Mapped[int | None] = mapped_column(
        default=None
    )  # Max playbacks/streams (None = unlimited)
    playback_period_minutes: Mapped[int] = mapped_column(
        default=1440
    )  # Time period in minutes (default: 1440 = per day)

    # Transcoding Permissions
    max_concurrent_transcodings: Mapped[int] = mapped_column(
        default=1
    )  # Maximum number of concurrent transcoding sessions (0 = no transcoding allowed)

    # Favorites Permissions
    favorites_permanent: Mapped[bool] = mapped_column(
        default=False
    )  # If true, users in this group cannot remove favorites

    # Relationships
    user_links = relationship(
        "UserGroupLink", back_populates="group", cascade="all, delete-orphan"
    )


class UserGroupLink(Base):
    """Many-to-many relationship between users and groups"""

    __tablename__ = "user_group_link"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Foreign keys
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.guid", ondelete="CASCADE"), index=True
    )
    group_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("group.guid", ondelete="CASCADE"), index=True
    )

    # Relationships
    # Note: User.group_links was removed during unified architecture migration
    # user = relationship("User", back_populates="group_links")
    group = relationship("Group", back_populates="user_links")
