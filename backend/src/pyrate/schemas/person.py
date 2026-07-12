"""Schemas for person and media cast."""

import uuid
from datetime import date, datetime


from pyrate.schemas.base import BaseSchema

# ==================== Person Schemas ====================


class PersonBase(BaseSchema):
    """Base schema for persons."""

    name: str
    tmdb_id: int | None = None
    profile_path: str | None = None
    known_for_department: str | None = None


class PersonExternalLinkRead(BaseSchema):
    """Schema for normalized external person/provider links."""

    provider: str
    provider_id: str | None = None
    display_name: str
    url: str


class PersonRead(PersonBase):
    """Schema for reading a person."""

    guid: uuid.UUID
    biography: str | None = None
    birthday: date | None = None
    deathday: date | None = None
    place_of_birth: str | None = None
    homepage: str | None = None
    metadata_imported: bool = False
    metadata_imported_at: datetime | None = None
    external_links: list["PersonExternalLinkRead"] = []
    created_at: datetime
    updated_at: datetime


# ==================== Media Cast Schemas ====================


class MediaCastBase(BaseSchema):
    """Base schema for media cast entries."""

    character: str | None = None
    department: str | None = None
    job: str | None = None
    cast_order: int | None = None


class MediaCastRead(MediaCastBase):
    """Schema for reading a media cast entry with person details."""

    guid: uuid.UUID
    media_item_guid: uuid.UUID
    person_guid: uuid.UUID
    person: PersonRead
    created_at: datetime


class MediaItemBrief(BaseSchema):
    """Brief media item info for credits display."""

    guid: uuid.UUID
    title: str
    media_type: str
    poster_path: str | None = None
    backdrop_path: str | None = None
    release_date: date | None = None


class MediaCastWithMedia(MediaCastBase):
    """Schema for reading a cast entry from person perspective (includes media info)."""

    guid: uuid.UUID
    media_item_guid: uuid.UUID
    person_guid: uuid.UUID
    media_item: MediaItemBrief | None = None
    created_at: datetime
