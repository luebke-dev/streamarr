import re
import uuid
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, field_validator

from pyrate.schemas.base import BaseSchema


class UserBase(BaseSchema):
    first_name: str
    last_name: str
    email: EmailStr
    is_active: bool = True
    is_superuser: bool = False


class UserCreate(UserBase):
    password: str | None = None

    @field_validator("password")
    @classmethod
    def validate_password(cls, v):
        if v is None:
            return v

        from ..config import settings

        if len(v) < settings.oidc.min_password_length:
            raise ValueError(
                f"Password must be at least {settings.oidc.min_password_length} characters long"
            )

        if settings.oidc.require_password_complexity:
            if not re.match(r"^(?=.*[a-z])(?=.*[A-Z])(?=.*\d)", v):
                raise ValueError(
                    "Password must contain at least one lowercase letter, one uppercase letter, and one digit"
                )

        return v


class UserUpdate(BaseSchema):
    first_name: str | None = None
    last_name: str | None = None
    email: EmailStr | None = None
    preferred_username: str | None = None
    is_active: bool | None = None
    is_superuser: bool | None = None
    ui_language: str | None = None
    audio_languages: list[str] | None = None
    subtitle_language: str | None = None


class UserRead(UserBase):
    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    oidc_sub: str | None = None
    oidc_provider: str | None = None
    preferred_username: str | None = None
    picture: str | None = None
    locale: str | None = None
    groups: str | None = None
    last_login: datetime | None = None
    ui_language: str | None = None
    audio_languages: list[str] | None = None
    subtitle_language: str | None = None


class UserLanguageSettings(BaseSchema):
    """Schema for user language preferences"""

    ui_language: str | None = None  # e.g., 'en-US', 'de-DE'
    audio_language: str | None = None  # Legacy single-language preference
    audio_languages: list[str] = ["en"]  # Ordered list of preferred audio languages
    subtitle_language: str | None = None  # None = disabled


class UserCodecSettings(BaseSchema):
    """Schema for user codec compatibility preferences used in release scoring."""

    supported_video_codecs: list[str] = []  # e.g., ['h264', 'h265', 'av1']
    supported_audio_codecs: list[str] = []  # e.g., ['aac', 'ac3', 'eac3']
    codec_match_bonus: int = 0  # Score bonus when codec is supported
    codec_mismatch_penalty: int = 0  # Score penalty when codec is NOT supported


class UserPlaybackPreferences(BaseSchema):
    """Schema for user playback preferences (skip behavior)."""

    skip_intro_mode: Literal["button", "auto", "disabled"] = "button"
    skip_outro_mode: Literal["button", "auto", "disabled"] = "button"
    skip_credits_mode: Literal["button", "auto", "disabled"] = "button"


class UserParentalControl(BaseSchema):
    """Schema for parental-control preference on a user.

    ``parental_max_age = None`` disables the gate. Any non-null integer hides
    and blocks media with ``min_age`` strictly above it (NULL-rated media is
    always visible).
    """

    parental_max_age: int | None = Field(None, ge=0, le=21)


class UserGamingPreferences(BaseSchema):
    """Schema for per-user Lightrays/GOW streaming settings.

    `keyboard_layout` is an XKB layout string (e.g. "de", "us", "gb") passed
    into the container as `XKB_DEFAULT_LAYOUT`. `mouse_speed` is a float
    multiplier (1.0 = default) that Wolf/GOW applies as a pointer-acceleration
    factor when the session is launched.
    """

    keyboard_layout: str = "us"
    mouse_speed: float = Field(1.0, ge=0.1, le=5.0)


class UserDisplayPreferences(BaseSchema):
    """Schema for per-client display preferences."""

    preference_id: str = Field("default", min_length=1, max_length=120)
    client: str = Field("web", min_length=1, max_length=80)
    view_type: str = Field("poster", min_length=1, max_length=80)
    sort_by: str | None = Field("name", max_length=120)
    sort_order: Literal["ascending", "descending"] = "ascending"
    index_by: str | None = Field(None, max_length=120)
    remember_indexing: bool = False
    show_backdrops: bool = True
    show_sidebar: bool = True
    enable_theme_songs: bool = False
    enable_theme_videos: bool = False
    chromecast_version: str | None = Field(None, max_length=80)
    custom: dict[str, Any] = Field(default_factory=dict)


class UserAccessSchedule(BaseModel):
    """Allowed access window for a day of week."""

    day_of_week: Literal[
        "monday",
        "tuesday",
        "wednesday",
        "thursday",
        "friday",
        "saturday",
        "sunday",
    ]
    start_hour: int = Field(0, ge=0, le=23)
    end_hour: int = Field(24, ge=1, le=24)


class UserPermissionOverride(BaseModel):
    """Schema for setting per-user permission overrides (admin only). None = inherit."""

    allowed_libraries: list[str] | None = None
    max_concurrent_streams: int | None = Field(None, ge=0)
    max_game_streams: int | None = Field(None, ge=0)
    max_video_quality: Literal["sd", "hd", "fhd", "uhd"] | None = None
    max_audio_quality: Literal["lossy", "lossless"] | None = None
    max_concurrent_transcodings: int | None = Field(None, ge=0)
    offline_download_limit: int | None = None
    offline_download_period_minutes: int | None = None
    prefetch_limit: int | None = None
    prefetch_period_minutes: int | None = None
    on_demand_fetch_limit: int | None = None
    on_demand_fetch_period_minutes: int | None = None
    indexer_api_requests_limit: int | None = None
    indexer_api_requests_period_minutes: int | None = None
    indexer_downloads_limit: int | None = None
    indexer_downloads_period_minutes: int | None = None
    playback_limit: int | None = None
    playback_period_minutes: int | None = None
    favorites_permanent: bool | None = None
    remote_access_enabled: bool | None = None
    access_schedules: list[UserAccessSchedule] | None = None


class UserLibraryAccessRead(BaseModel):
    """Concrete library access decision for a user."""

    library_guid: uuid.UUID
    library_name: str
    library_type: str
    permission_key: str
    enabled: bool
    allowed: bool


class UserLibraryAccessResponse(BaseModel):
    """Per-library access map for a user."""

    user_id: uuid.UUID
    items: list[UserLibraryAccessRead]
    total: int


class LocalLoginRequest(BaseModel):
    """Schema for local login."""

    email: EmailStr
    password: str
    device_id: str | None = None
    device_info: dict | None = None
