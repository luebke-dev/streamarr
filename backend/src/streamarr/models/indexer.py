import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, func, text, types
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Indexer(Base):
    __tablename__ = "indexer"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),  # use what you have on your server
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    label: Mapped[str] = mapped_column(index=True)
    host: Mapped[str] = mapped_column(index=True)
    api_key: Mapped[str] = mapped_column(index=True)
    ssl: Mapped[bool] = mapped_column(default=False)
    type: Mapped[str] = mapped_column(index=True)
    verify_ssl: Mapped[bool] = mapped_column(default=True)

    # RSS sync / availability. ``enabled`` gates the indexer for all use;
    # ``rss_enabled`` opts it into the periodic latest-feed poll (off by
    # default — operator opt-in); ``priority`` orders fan-out (lower first).
    enabled: Mapped[bool] = mapped_column(
        default=True, server_default=text("true"), index=True
    )
    supports_rss: Mapped[bool] = mapped_column(
        default=True, server_default=text("true")
    )
    rss_enabled: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), index=True
    )
    priority: Mapped[int] = mapped_column(default=25, server_default=text("25"))
    last_rss_sync_at: Mapped[datetime | None] = mapped_column(nullable=True)

    categories = relationship(
        "IndexerCategory", back_populates="indexer", cascade="all, delete-orphan"
    )

    __table_args__ = (Index("ix_indexer_rss", "enabled", "rss_enabled"),)


class IndexerCategory(Base):
    __tablename__ = "indexer_category"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),  # use what you have on your server
    )
    label: Mapped[str] = mapped_column(index=True)
    indexer_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("indexer.guid", ondelete="CASCADE"),
    )
    category_type: Mapped[str] = mapped_column(
        index=True
    )  # e.g., 'movie', 'show', 'game'
    newznab_category_id: Mapped[int | None] = mapped_column(
        nullable=True, index=True
    )  # e.g. 2000, 5000
    language: Mapped[list[str] | None] = mapped_column(types.JSON, nullable=True)
    resolution: Mapped[list[str] | None] = mapped_column(types.JSON, nullable=True)
    platform: Mapped[str | None] = mapped_column(nullable=True)
    indexer = relationship(
        "Indexer",
        back_populates="categories",
    )
