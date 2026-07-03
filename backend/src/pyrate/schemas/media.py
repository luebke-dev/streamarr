"""Unified media schemas for all content types."""

import uuid
from datetime import datetime

from pydantic import BaseModel, Field

from pyrate.models.media import AvailabilityStatus, MediaType
from pyrate.schemas.base import PaginatedResponse, BaseSchema
from pyrate.schemas.person import MediaCastRead


# ==================== Genre Schema ====================


class GenreRead(BaseSchema):
    """Schema for reading genres."""

    id: int
    name: str


# ==================== Platform Schema ====================


class PlatformRead(BaseSchema):
    """Schema for reading platforms."""

    id: int
    name: str
    logo_url: str | None = None


# ==================== External ID Schemas ====================


class MediaExternalIdRead(BaseSchema):
    """Schema for reading external IDs."""

    guid: uuid.UUID
    provider: str
    external_id: str
    created_at: datetime


class MediaExternalLinkRead(BaseSchema):
    """Schema for normalized provider links derived from external IDs."""

    provider: str
    provider_id: str
    display_name: str
    url: str


class MediaExternalIdCreate(BaseModel):
    """Schema for creating external IDs."""

    provider: str
    external_id: str


# ==================== Media File Schemas ====================


class MediaFileBase(BaseSchema):
    """Base schema for media files."""

    file_path: str
    file_name: str | None = None
    file_size: int | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    quality: str | None = None
    format: str | None = None
    probe_data: str | None = None


class MediaFileCreate(MediaFileBase):
    """Schema for creating media files."""

    media_item_guid: uuid.UUID


class MediaFileUpdate(BaseSchema):
    """Schema for updating media files."""

    file_name: str | None = None
    file_size: int | None = None
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    codec: str | None = None
    bitrate: int | None = None
    quality: str | None = None
    format: str | None = None
    probe_data: str | None = None


class MediaFileRead(MediaFileBase):
    """Schema for reading media files."""

    guid: uuid.UUID
    media_item_guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    imported_at: datetime | None = None


# ==================== Media Release Schemas ====================


class MediaReleaseLinkRead(BaseSchema):
    """Schema for reading release links."""

    guid: uuid.UUID
    link: str
    link_type: str
    created_at: datetime


class MediaReleaseLinkCreate(BaseModel):
    """Schema for creating release links."""

    link: str
    link_type: str


class MediaReleaseBase(BaseSchema):
    """Base schema for media releases."""

    title: str
    size: int | None = None
    quality: str | None = None
    score: int = 0
    release_metadata: dict | None = None


class MediaReleaseCreate(MediaReleaseBase):
    """Schema for creating media releases."""

    media_item_guid: uuid.UUID
    indexer_guid: uuid.UUID | None = None
    publish_date: datetime | None = None


class MediaReleaseUpdate(BaseSchema):
    """Schema for updating media releases."""

    title: str | None = None
    size: int | None = None
    quality: str | None = None
    score: int | None = None


class MediaReleaseRead(MediaReleaseBase):
    """Schema for reading media releases."""

    guid: uuid.UUID
    media_item_guid: uuid.UUID
    indexer_guid: uuid.UUID | None = None
    blacklisted_reason: str | None = None
    created_at: datetime
    publish_date: datetime | None = None
    links: list[MediaReleaseLinkRead] = []


class MediaReleaseWithScore(BaseSchema):
    """Schema for releases with score and matching rules."""

    release: MediaReleaseRead
    score: int
    rules: list[dict] = []


# ==================== Media Item Schemas ====================


class MediaItemBase(BaseSchema):
    """Base schema for media items."""

    title: str
    original_title: str | None = None
    description: str | None = None
    tagline: str | None = None
    release_date: datetime | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    content_rating: str | None = None
    min_age: int | None = None
    extra_data: str | None = Field(
        None, description="JSON string containing type-specific metadata"
    )


class MediaItemCreate(MediaItemBase):
    """Schema for creating media items."""

    media_type: MediaType
    parent_guid: uuid.UUID | None = None
    sequence_number: int | None = None
    availability_status: AvailabilityStatus = AvailabilityStatus.UNKNOWN


class MediaItemUpdate(BaseSchema):
    """Schema for updating media items."""

    title: str | None = None
    original_title: str | None = None
    description: str | None = None
    tagline: str | None = None
    release_date: datetime | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    availability_status: AvailabilityStatus | None = None
    sequence_number: int | None = None
    extra_data: str | None = None


class MediaItemSummary(BaseSchema):
    """Lightweight schema for media items in lists, search results, and cards."""

    guid: uuid.UUID
    media_type: MediaType
    title: str
    original_title: str | None = None
    poster_path: str | None = None
    backdrop_path: str | None = None
    release_date: datetime | None = None
    availability_status: AvailabilityStatus
    content_rating: str | None = None
    min_age: int | None = None
    genres: list[GenreRead] = []
    platforms: list[PlatformRead] = []


class MediaItemRead(MediaItemBase):
    """Schema for reading media items."""

    guid: uuid.UUID
    media_type: MediaType
    parent_guid: uuid.UUID | None = None
    sequence_number: int | None = None
    availability_status: AvailabilityStatus
    created_at: datetime
    updated_at: datetime
    last_searched_at: datetime | None = None
    last_metadata_updated_at: datetime | None = None

    # Computed field: count of child items (episodes, tracks, etc.)
    children_count: int = 0

    # Optional relationships (loaded on demand)
    files: list[MediaFileRead] = []
    releases: list[MediaReleaseRead] = []
    external_ids: list[MediaExternalIdRead] = []
    genres: list[GenreRead] = []
    platforms: list[PlatformRead] = []


class MediaItemWithChildren(MediaItemRead):
    """Schema for media items with child items (e.g., show with seasons)."""

    children: list["MediaItemRead"] = []


class MediaItemDetail(MediaItemRead):
    """Detailed media item schema with all relationships."""

    files: list[MediaFileRead] = []
    releases: list[MediaReleaseRead] = []
    external_ids: list[MediaExternalIdRead] = []
    external_links: list[MediaExternalLinkRead] = []
    cast: list[MediaCastRead] = []

    # Episode-specific fields (populated from parent hierarchy)
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None


# ==================== Hierarchy Schemas ====================


class SeasonWithEpisodes(BaseSchema):
    """Schema for a season with its episodes."""

    season: MediaItemRead
    episodes: list[MediaItemRead] = []


class ShowWithHierarchy(BaseSchema):
    """Schema for a show with complete hierarchy."""

    show: MediaItemRead
    seasons: list[SeasonWithEpisodes] = []


class AlbumWithTracks(BaseSchema):
    """Schema for an album with its tracks."""

    album: MediaItemRead
    tracks: list[MediaItemRead] = []


# Pagination envelopes — generic shape lives in schemas/base.py


class PaginatedMediaItemsResponse(PaginatedResponse[MediaItemRead]):
    pass


class PaginatedMediaSummaryResponse(PaginatedResponse[MediaItemSummary]):
    pass


class PaginatedMediaReleasesResponse(PaginatedResponse[MediaReleaseRead]):
    pass


# ==================== Search & Filter ====================


class MediaSearchRequest(BaseModel):
    """Search request for media items."""

    query: str
    media_type: MediaType | None = None
    limit: int = Field(50, ge=1, le=100)


class MediaSearchResponse(BaseModel):
    """Search response for media items."""

    results: list[MediaItemSummary]
    total: int


# ==================== Stats ====================


class MediaStats(BaseModel):
    """Statistics for media items."""

    total_items: int
    by_type: dict[str, int] = {}
    by_status: dict[str, int] = {}
    by_library: dict[str, int] = {}


# Update forward references
MediaItemWithChildren.model_rebuild()
