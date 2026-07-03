import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class DownloadStatus:
    """String constants for Download.status.

    Mixed case reflects external downloader (radarr/sonarr-style) vocabulary
    plus internal lowercase states. Kept verbatim so existing DB rows match.
    """

    PENDING = "pending"
    QUEUED = "queued"
    DOWNLOADING = "Downloading"
    COMPLETED = "Completed"
    IMPORTED = "Imported"
    FAILED = "Failed"

    TERMINAL = ("Imported", "Failed")
    ACTIVE_EXCLUSIONS = ("Failed", "Imported", "Completed")


class Download(Base):
    __tablename__ = "download"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),  # use what you have on your server
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    title: Mapped[str] = mapped_column(index=True)
    type: Mapped[str] = mapped_column(index=True)
    downloader_id: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("downloader.guid", ondelete="CASCADE"),
        index=True,
    )
    status: Mapped[str] = mapped_column(index=True)
    external_id: Mapped[str | None] = mapped_column(index=True, nullable=True)
    progress: Mapped[float | None] = mapped_column(nullable=True)
    # Live download speed in bytes/sec, polled from the downloader.
    speed_bps: Mapped[int | None] = mapped_column(types.BigInteger, nullable=True)

    # User who started the download (nullable for automated downloads)
    user_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # Relationship to the downloader that handled this download
    downloader = relationship(
        "Downloader",
        foreign_keys=[downloader_id],
    )

    # Relationship to the user who started the download
    started_by = relationship(
        "User",
        foreign_keys=[user_guid],
    )

    # Error reason for failed downloads
    error_reason: Mapped[str | None] = mapped_column(nullable=True)

    # Unified media release link (replaces movie/episode/game/album specific links)
    media_release_link_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("media_release_link.guid", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )

    # Relationship to unified media release link
    media_release_link = relationship(
        "MediaReleaseLink",
        back_populates="downloads",
        foreign_keys=[media_release_link_guid],
    )

    # Upgrade tracking: when ``is_upgrade`` is true this download replaces an
    # existing file (``replaces_media_file_guid``). The completion handler
    # swaps the old file for the new one only after a successful import.
    is_upgrade: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), index=True
    )
    replaces_media_file_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("media_file.guid", ondelete="SET NULL"),
        index=True,
        nullable=True,
    )
