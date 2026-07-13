import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import func, text, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base

if TYPE_CHECKING:
    from streamarr.models.party import WatchParty, WatchPartyMember


class User(Base):
    __tablename__ = "user"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    email: Mapped[str] = mapped_column(index=True, unique=True)
    first_name: Mapped[str] = mapped_column(index=True)
    last_name: Mapped[str] = mapped_column(index=True)
    is_active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)
    email_verified: Mapped[bool] = mapped_column(default=False)

    # Access/refresh tokens issued before this instant are rejected. Bumped on
    # logout and password reset so those actions revoke outstanding sessions
    # immediately, not just when the short access token naturally expires.
    token_valid_after: Mapped[datetime | None] = mapped_column()

    # OIDC-spezifische Felder
    oidc_sub: Mapped[str | None] = mapped_column(
        index=True, unique=True
    )  # Subject identifier from OIDC provider
    oidc_provider: Mapped[str | None] = mapped_column(
        index=True
    )  # Provider name (e.g., 'keycloak', 'google')
    preferred_username: Mapped[str | None] = mapped_column(index=True)
    picture: Mapped[str | None] = mapped_column()  # Profile picture URL
    locale: Mapped[str | None] = mapped_column()

    # Local auth (optional, when local users are supported alongside OIDC).
    hashed_password: Mapped[str | None] = mapped_column()

    # Additional OIDC claims
    groups: Mapped[str | None] = mapped_column()  # JSON string of groups/roles
    last_login: Mapped[datetime | None] = mapped_column()

    # Language preferences
    ui_language: Mapped[str | None] = mapped_column(
        default="en-US"
    )  # UI language (e.g., 'en-US', 'de-DE')
    audio_languages: Mapped[list[str] | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True, default=list
    )  # Ordered list of preferred audio languages (e.g., ['en', 'de', 'ja'])
    subtitle_language: Mapped[str | None] = mapped_column(
        default=None
    )  # Preferred subtitle language (None = disabled)

    # Parental control: hide / block media whose ``min_age`` exceeds this value.
    # NULL = no age gate; applies to movies/shows only (other types are unrated).
    parental_max_age: Mapped[int | None] = mapped_column(default=None)

    # Playback preferences (skip modes: "button", "auto", "disabled")
    playback_preferences: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Quality preferences for automatic downloads
    # Example: {"preferred_resolution": "1080p", "preferred_codec": "h265", "min_score": 70}
    # Use JSONB for PostgreSQL, JSON for other databases (like SQLite for testing)
    quality_preferences: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Gaming preferences for Lightrays/GOW streaming sessions
    # Example: {"keyboard_layout": "de", "mouse_speed": 1.0}
    gaming_preferences: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Display preferences keyed by client and view id.
    # Example: {"web:home": {"view_type": "poster", "sort_by": "name"}}
    display_preferences: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Permission overrides (None = inherit from group or global defaults)
    allowed_libraries: Mapped[list[str] | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )
    max_concurrent_streams: Mapped[int | None] = mapped_column(nullable=True)
    max_game_streams: Mapped[int | None] = mapped_column(nullable=True)
    max_video_quality: Mapped[str | None] = mapped_column(
        nullable=True
    )  # 'sd', 'hd', 'fhd', 'uhd'
    max_audio_quality: Mapped[str | None] = mapped_column(
        nullable=True
    )  # 'lossy', 'lossless'
    max_concurrent_transcodings: Mapped[int | None] = mapped_column(nullable=True)
    offline_download_limit: Mapped[int | None] = mapped_column(nullable=True)
    offline_download_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    prefetch_limit: Mapped[int | None] = mapped_column(nullable=True)
    prefetch_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    on_demand_fetch_limit: Mapped[int | None] = mapped_column(nullable=True)
    on_demand_fetch_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    indexer_api_requests_limit: Mapped[int | None] = mapped_column(nullable=True)
    indexer_api_requests_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    indexer_downloads_limit: Mapped[int | None] = mapped_column(nullable=True)
    indexer_downloads_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    playback_limit: Mapped[int | None] = mapped_column(nullable=True)
    playback_period_minutes: Mapped[int | None] = mapped_column(nullable=True)
    favorites_permanent: Mapped[bool | None] = mapped_column(nullable=True)
    remote_access_enabled: Mapped[bool | None] = mapped_column(nullable=True)
    access_schedules: Mapped[list[dict] | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), nullable=True
    )

    # Relationships
    owned_lists = relationship(
        "List", back_populates="owner", cascade="all, delete-orphan"
    )
    created_invites = relationship(
        "Invite",
        foreign_keys="Invite.created_by_user_id",
        back_populates="created_by",
        cascade="all, delete-orphan",
    )
    used_invites = relationship(
        "Invite", foreign_keys="Invite.used_by_user_id", back_populates="used_by"
    )
    subscriptions = relationship(
        "UserSubscription", back_populates="user", cascade="all, delete-orphan"
    )
    sessions = relationship(
        "UserSession", back_populates="user", cascade="all, delete-orphan"
    )
    viewing_history = relationship(
        "ViewingHistory", back_populates="user", cascade="all, delete-orphan"
    )
    notifications = relationship(
        "Notification", back_populates="user", cascade="all, delete-orphan"
    )
    devices = relationship(
        "Device", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys = relationship(
        "ApiKey",
        foreign_keys="ApiKey.user_guid",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # Note: UserGroupLink was removed during unified architecture migration
    # group_links: Mapped[list["UserGroupLink"]] = relationship(
    #     back_populates="user", cascade="all, delete-orphan"
    # )
    created_banners = relationship(
        "Banner", back_populates="created_by", cascade="all, delete-orphan"
    )
    dismissed_banners = relationship(
        "UserBannerDismissed", back_populates="user", cascade="all, delete-orphan"
    )
    owned_watch_parties: Mapped[list["WatchParty"]] = relationship(
        back_populates="owner", cascade="all, delete-orphan"
    )
    watch_party_memberships: Mapped[list["WatchPartyMember"]] = relationship(
        back_populates="user", cascade="all, delete-orphan"
    )
    sent_friend_requests = relationship(
        "Friendship",
        foreign_keys="Friendship.requester_id",
        back_populates="requester",
        cascade="all, delete-orphan",
    )
    received_friend_requests = relationship(
        "Friendship",
        foreign_keys="Friendship.addressee_id",
        back_populates="addressee",
        cascade="all, delete-orphan",
    )
