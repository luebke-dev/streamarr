from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from pyrate.schemas.base import BaseSchema


class UserBriefResponse(BaseSchema):
    """Brief user info for nested responses"""

    guid: UUID
    first_name: str | None = None
    last_name: str | None = None
    email: str | None = None
    preferred_username: str | None = None

class InviteBase(BaseModel):
    """Base Invite Schema"""

    description: str | None = None
    max_uses: int = Field(default=1, ge=1)


class InviteCreate(InviteBase):
    """Schema for creating an invite."""

    expiry_hours: int | None = Field(default=None, ge=1, le=168)  # max 1 week
    expires_at: datetime | None = None  # optional explicit expiry timestamp


class InviteUpdate(BaseModel):
    """Schema for updating an invite."""

    description: str | None = None
    is_active: bool | None = None
    expires_at: datetime | None = None
    max_uses: int | None = None


class InviteResponse(InviteBase):
    """Schema for invite responses."""

    guid: UUID
    created_at: datetime
    updated_at: datetime | None
    created_by_user_id: UUID
    token: str
    expires_at: datetime
    is_active: bool
    is_used: bool
    used_at: datetime | None
    used_by_user_id: UUID | None
    current_uses: int

    model_config = ConfigDict(from_attributes=True)


class InviteListResponse(BaseSchema):
    """Schema for invite list responses."""

    guid: UUID
    created_at: datetime
    updated_at: datetime | None
    description: str | None
    expires_at: datetime
    is_active: bool
    is_used: bool
    used_at: datetime | None
    used_by_user_id: UUID | None
    max_uses: int
    current_uses: int
    token: str  # Needed for copy invite link functionality
    created_by: UserBriefResponse | None = None  # Nested user info
    used_by: UserBriefResponse | None = None  # Nested user info

class PaginatedInviteListResponse(BaseModel):
    """Paginated response for invites list"""

    items: list[InviteListResponse]
    total: int
    page: int = 1
    size: int = 100


class InviteValidation(BaseModel):
    """Schema for invite validation."""

    token: str


class InviteUse(BaseModel):
    """Schema for redeeming an invite during registration."""

    invite_token: str
    email: str
    first_name: str
    last_name: str
    preferred_username: str | None = None
    password: str | None = None  # for local authentication
    ui_language: str | None = None  # e.g., 'en-US', 'de-DE'
    audio_languages: list[str] | None = None  # e.g., ['en', 'de']
    subtitle_language: str | None = None  # None = disabled
