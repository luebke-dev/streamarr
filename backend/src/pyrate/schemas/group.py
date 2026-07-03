import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from pyrate.schemas.base import BaseSchema


# Group Schemas
class GroupBase(BaseModel):
    """Base group schema with common fields"""

    name: str = Field(..., min_length=1, max_length=100)
    description: str | None = None
    is_active: bool = True

    # Library Access
    allowed_libraries: list[str] = Field(default_factory=list)

    # Streaming
    max_concurrent_streams: int = Field(default=1, ge=0)
    max_game_streams: int = Field(default=0, ge=0)

    # Download Limits (rate limiting)
    offline_download_limit: int | None = None
    offline_download_period_minutes: int = 1440  # Default: per day

    # Automation Limits (rate limiting)
    prefetch_limit: int | None = None
    prefetch_period_minutes: int = 1440  # Default: per day
    on_demand_fetch_limit: int | None = None
    on_demand_fetch_period_minutes: int = 1440  # Default: per day

    # Quality
    max_video_quality: Literal["sd", "hd", "fhd", "uhd"] | None = "uhd"
    max_audio_quality: Literal["lossy", "lossless"] | None = "lossless"

    # Indexer Limits (flexible time periods)
    indexer_api_requests_limit: int | None = None
    indexer_api_requests_period_minutes: int = 60  # Default: per hour
    indexer_downloads_limit: int | None = None
    indexer_downloads_period_minutes: int = 1440  # Default: per day

    # Playback Limits (rate limiting)
    playback_limit: int | None = None
    playback_period_minutes: int = 1440  # Default: per day

    # Transcoding
    max_concurrent_transcodings: int = Field(default=1, ge=0)

    # Favorites
    favorites_permanent: bool = False


class GroupCreate(GroupBase):
    """Schema for creating a new group"""

    pass


class GroupUpdate(BaseModel):
    """Schema for updating a group (all fields optional)"""

    name: str | None = Field(None, min_length=1, max_length=100)
    description: str | None = None
    is_active: bool | None = None
    allowed_libraries: list[str] | None = None
    max_concurrent_streams: int | None = Field(None, ge=0)
    max_game_streams: int | None = Field(None, ge=0)
    offline_download_limit: int | None = None
    offline_download_period_minutes: int | None = None
    prefetch_limit: int | None = None
    prefetch_period_minutes: int | None = None
    on_demand_fetch_limit: int | None = None
    on_demand_fetch_period_minutes: int | None = None
    max_video_quality: Literal["sd", "hd", "fhd", "uhd"] | None = None
    max_audio_quality: Literal["lossy", "lossless"] | None = None
    indexer_api_requests_limit: int | None = None
    indexer_api_requests_period_minutes: int | None = None
    indexer_downloads_limit: int | None = None
    indexer_downloads_period_minutes: int | None = None
    playback_limit: int | None = None
    playback_period_minutes: int | None = None
    max_concurrent_transcodings: int | None = Field(None, ge=0)
    favorites_permanent: bool | None = None


class GroupRead(GroupBase):
    """Schema for reading a group"""

    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    member_count: int = 0  # Number of users in this group

    model_config = ConfigDict(from_attributes=True)


class GroupWithMembers(GroupRead):
    """Group with list of member user IDs"""

    member_ids: list[uuid.UUID] = Field(default_factory=list)


# User-Group Assignment Schemas
class UserGroupAssignment(BaseModel):
    """Schema for assigning users to groups"""

    user_id: uuid.UUID
    group_id: uuid.UUID


class BulkUserGroupAssignment(BaseModel):
    """Schema for bulk user-group assignments"""

    user_ids: list[uuid.UUID]
    group_id: uuid.UUID


class UserWithGroups(BaseSchema):
    """User with their assigned groups"""

    user_id: uuid.UUID
    email: str
    first_name: str
    last_name: str
    group_ids: list[uuid.UUID] = Field(default_factory=list)

# Permission Check Schema
class UserPermissions(BaseModel):
    """Computed permissions for a user (merged from all groups)"""

    user_id: uuid.UUID
    allowed_libraries: list[str]
    max_concurrent_streams: int
    max_game_streams: int
    offline_download_limit: int | None
    offline_download_period_minutes: int
    prefetch_limit: int | None
    prefetch_period_minutes: int
    on_demand_fetch_limit: int | None
    on_demand_fetch_period_minutes: int
    max_video_quality: str | None
    max_audio_quality: str | None
    indexer_api_requests_limit: int | None
    indexer_api_requests_period_minutes: int
    indexer_downloads_limit: int | None
    indexer_downloads_period_minutes: int
    playback_limit: int | None
    playback_period_minutes: int
    max_concurrent_transcodings: int
    favorites_permanent: bool
    remote_access_enabled: bool
    access_schedules: list[dict] = Field(default_factory=list)
    access_schedule_active: bool

    # Source groups
    group_names: list[str] = Field(default_factory=list)


class EffectivePermissions(BaseModel):
    """Effective permissions for a user after merging Global > Group > User-Override"""

    user_id: uuid.UUID
    allowed_libraries: list[str]
    max_concurrent_streams: int
    max_game_streams: int
    offline_download_limit: int | None
    offline_download_period_minutes: int
    prefetch_limit: int | None
    prefetch_period_minutes: int
    on_demand_fetch_limit: int | None
    on_demand_fetch_period_minutes: int
    max_video_quality: str | None
    max_audio_quality: str | None
    indexer_api_requests_limit: int | None
    indexer_api_requests_period_minutes: int
    indexer_downloads_limit: int | None
    indexer_downloads_period_minutes: int
    playback_limit: int | None
    playback_period_minutes: int
    max_concurrent_transcodings: int
    favorites_permanent: bool
    remote_access_enabled: bool
    access_schedules: list[dict] = Field(default_factory=list)
    access_schedule_active: bool

    # Sources
    group_names: list[str] = Field(default_factory=list)
    source: str = "global"  # 'global', 'group', 'user_override'
