import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, UniqueConstraint, text, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class _CaseInsensitiveStrEnum(StrEnum):
    """StrEnum that accepts values case-insensitively."""

    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            upper = value.upper()
            for member in cls:
                if member.value == upper:
                    return member
        return None


class ListType(_CaseInsensitiveStrEnum):
    SYSTEM = "SYSTEM"
    USER = "USER"
    FAVORITES = "FAVORITES"


class ListVisibility(_CaseInsensitiveStrEnum):
    PRIVATE = "PRIVATE"
    PUBLIC = "PUBLIC"


class ListItemType(_CaseInsensitiveStrEnum):
    MOVIE = "MOVIE"
    SHOW = "SHOW"
    GAME = "GAME"
    EPISODE = "EPISODE"
    MUSIC = "MUSIC"
    BOOK = "BOOK"
    AUDIOBOOK = "AUDIOBOOK"


class UserListInteractionType(StrEnum):
    LIKE = "like"
    FOLLOW = "follow"
    BOOKMARK = "bookmark"


class List(Base):
    __tablename__ = "list"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime | None] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime | None] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    # Basic list properties
    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()

    # Localised overrides – JSON objects keyed by locale, e.g. {"de-DE": "Favoriten"}
    name_translations: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=None
    )
    description_translations: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=None
    )

    # List type and ownership
    list_type: Mapped[ListType] = mapped_column(index=True)
    owner_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        index=True,
    )

    # Visibility and settings
    visibility: Mapped[ListVisibility] = mapped_column(
        default=ListVisibility.PRIVATE, index=True
    )
    is_active: Mapped[bool] = mapped_column(default=True, index=True)

    # Soft delete — list is hidden from users but kept for 30 days
    deleted_at: Mapped[datetime | None] = mapped_column(default=None, index=True)

    # System list specific fields
    auto_update: Mapped[bool] = mapped_column(default=False)
    # Stable identifier for system-generated lists (e.g. "trending_movies",
    # "trending_shows"). The trending importer uses ON CONFLICT (update_source)
    # to upsert these rows, which requires a unique constraint to exist.
    # Defined as a partial unique index in __table_args__ below so multiple
    # NULLs (regular user lists) are still allowed.
    update_source: Mapped[str | None] = mapped_column(index=True)
    last_auto_update: Mapped[datetime | None] = mapped_column()

    # Optional anchor item for per-anchor recommendation lists ("Because you
    # watched X"). Nullable; FKs to media_item.guid with ON DELETE CASCADE so
    # the list dies with the anchor.
    context_item_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        index=True,
    )

    # Metadata
    tags: Mapped[str | None] = mapped_column()  # JSON string for tags
    poster_path: Mapped[str | None] = mapped_column()

    # Statistics (can be computed but stored for performance)
    item_count: Mapped[int] = mapped_column(default=0)
    like_count: Mapped[int] = mapped_column(default=0)
    follow_count: Mapped[int] = mapped_column(default=0)

    # Relationships
    owner = relationship("User", back_populates="owned_lists")
    items = relationship(
        "ListItem", back_populates="list", cascade="all, delete-orphan"
    )
    user_interactions = relationship(
        "UserListInteraction", back_populates="list", cascade="all, delete-orphan"
    )

    __table_args__ = (
        # Two scoped uniques on update_source — see migration d5e6f7a8b9c0.
        # Singleton system lists (owner_guid NULL) like trending_*: unique
        # globally on update_source. Per-user system lists (owner_guid set)
        # like rec:for_you:*: unique per (owner, update_source) so every
        # user can have their own rec list with the same source label.
        Index(
            "uq_list_global_update_source",
            "update_source",
            unique=True,
            postgresql_where=text(
                "owner_guid IS NULL AND update_source IS NOT NULL"
            ),
        ),
        Index(
            "uq_list_user_update_source",
            "owner_guid",
            "update_source",
            unique=True,
            postgresql_where=text(
                "owner_guid IS NOT NULL AND update_source IS NOT NULL"
            ),
        ),
        Index(
            "uq_list_favorites_owner",
            "owner_guid",
            unique=True,
            sqlite_where=text("list_type = 'FAVORITES'"),
            postgresql_where=text("list_type = 'FAVORITES'"),
        ),
    )


class ListItem(Base):
    __tablename__ = "list_item"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime | None] = mapped_column(default=lambda: datetime.now(UTC))

    # List relationship
    list_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("list.guid", ondelete="CASCADE"),
        index=True,
    )

    # Item properties
    item_type: Mapped[ListItemType] = mapped_column(index=True)
    item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, index=True
    )  # References movie.guid, show.guid, etc.

    # Optional metadata
    order_index: Mapped[int | None] = mapped_column()  # For ordered lists
    added_by_guid: Mapped[uuid.UUID | None] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="SET NULL"),
        index=True,
    )
    notes: Mapped[str | None] = mapped_column()  # User notes about this item

    # Relationships
    list = relationship("List", back_populates="items")
    added_by = relationship("User")

    __table_args__ = (
        UniqueConstraint(
            "list_guid",
            "item_guid",
            "item_type",
            name="uq_list_item_list_item_type",
        ),
    )


class UserListInteraction(Base):
    __tablename__ = "user_list_interaction"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    created_at: Mapped[datetime | None] = mapped_column(default=lambda: datetime.now(UTC))

    # User and list
    user_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("user.guid", ondelete="CASCADE"),
        index=True,
    )
    list_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("list.guid", ondelete="CASCADE"),
        index=True,
    )

    # Interaction type
    interaction_type: Mapped[UserListInteractionType] = mapped_column(index=True)

    # Relationships
    user = relationship("User")
    list = relationship("List", back_populates="user_interactions")

    # Unique constraint to prevent duplicate interactions
    __table_args__ = (
        UniqueConstraint(
            "user_guid",
            "list_guid",
            "interaction_type",
            name="uq_user_list_interaction",
        ),
    )
