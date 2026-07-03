"""FastAPI dependency objects for media list filtering."""

import uuid

from fastapi import Query

from pyrate.models.media import MediaType

_LIBRARY_TYPE_TO_MEDIA_TYPE = {
    "MOVIES": MediaType.MOVIES,
    "MOVIE": MediaType.MOVIES,
    "SHOWS": MediaType.SHOWS,
    "SHOW": MediaType.SHOWS,
    "SERIES": MediaType.SHOWS,
    "GAMES": MediaType.GAMES,
    "GAME": MediaType.GAMES,
    "MUSIC": MediaType.ARTISTS,
    "BOOKS": MediaType.BOOKS,
    "AUDIOBOOKS": getattr(MediaType, "AUDIOBOOKS", MediaType.BOOKS),
}


def media_type_for_library(library_type: str | None) -> MediaType | None:
    if not library_type:
        return None
    return _LIBRARY_TYPE_TO_MEDIA_TYPE.get(library_type.upper())


class MediaListQuery:
    """Grouped query params for the media list endpoint."""

    def __init__(
        self,
        media_type: MediaType | None = Query(None, description="Filter by media type"),
        library_guid: uuid.UUID | None = Query(None, description="Filter by library"),
        parent_guid: uuid.UUID | None = Query(
            None, description="Filter by parent (for episodes, tracks, etc.)"
        ),
        search_term: str | None = Query(
            None,
            max_length=200,
            description="Filter by title, original title, or description",
        ),
        genre_id: int | None = Query(None, description="Filter by genre"),
        genre_ids: list[int] | None = Query(
            None, description="Filter by any of these genres"
        ),
        genre_names: list[str] | None = Query(
            None, description="Filter by any of these genre names"
        ),
        exclude_genre_ids: list[int] | None = Query(
            None, description="Exclude any of these genres"
        ),
        exclude_genre_names: list[str] | None = Query(
            None, description="Exclude any of these genre names"
        ),
        platform_id: int | None = Query(None, description="Filter by platform"),
        platform_ids: list[int] | None = Query(
            None, description="Filter by any of these platforms"
        ),
        exclude_platform_ids: list[int] | None = Query(
            None, description="Exclude any of these platforms"
        ),
        availability: str | None = Query(
            None,
            description="Filter by file/release availability",
            pattern="^(local|releases|none)$",
        ),
        has_poster: bool | None = Query(None, description="Filter by poster presence"),
        has_backdrop: bool | None = Query(
            None, description="Filter by backdrop presence"
        ),
        has_description: bool | None = Query(
            None, description="Filter by non-empty description presence"
        ),
        year: int | None = Query(
            None, ge=1800, le=3000, description="Filter by release year"
        ),
        years: list[int] | None = Query(
            None, description="Filter by any of these release years"
        ),
        exclude_years: list[int] | None = Query(
            None, description="Exclude any of these release years"
        ),
        start_year: int | None = Query(
            None, ge=1800, le=3000, description="Minimum release year"
        ),
        end_year: int | None = Query(
            None, ge=1800, le=3000, description="Maximum release year"
        ),
        content_rating: str | None = Query(
            None, max_length=50, description="Filter by content rating"
        ),
        exclude_content_ratings: list[str] | None = Query(
            None, description="Exclude any of these content ratings"
        ),
        studio_name: str | None = Query(
            None, max_length=200, description="Filter by studio or production company"
        ),
        container: str | None = Query(
            None, max_length=50, description="Filter by media file container/format"
        ),
        exclude_containers: list[str] | None = Query(
            None, description="Exclude any of these media file containers/formats"
        ),
        person_guid: uuid.UUID | None = Query(
            None, description="Filter by cast or crew person"
        ),
        person_name: str | None = Query(
            None, max_length=200, description="Filter by cast or crew person name"
        ),
        exclude_person_guid: uuid.UUID | None = Query(
            None, description="Exclude items with this cast or crew person"
        ),
        exclude_person_name: str | None = Query(
            None,
            max_length=200,
            description="Exclude items with this cast or crew person name",
        ),
        is_favorite: bool | None = Query(
            None, description="Filter by current user's favorites"
        ),
        is_played: bool | None = Query(
            None, description="Filter by current user's completed playback state"
        ),
        page: int = Query(1, ge=1, description="Page number"),
        per_page: int = Query(20, ge=1, le=100, description="Items per page"),
        order_by: str = Query(
            "created_at",
            description="Field to order by",
            pattern="^(created_at|updated_at|title|year|sequence_number)$",
        ),
        order_desc: bool = Query(True, description="Descending order"),
    ) -> None:
        self.media_type = media_type
        self.library_guid = library_guid
        self.parent_guid = parent_guid
        self.search_term = search_term
        self.genre_id = genre_id
        self.genre_ids = genre_ids
        self.genre_names = genre_names
        self.exclude_genre_ids = exclude_genre_ids
        self.exclude_genre_names = exclude_genre_names
        self.platform_id = platform_id
        self.platform_ids = platform_ids
        self.exclude_platform_ids = exclude_platform_ids
        self.availability = availability
        self.has_poster = has_poster
        self.has_backdrop = has_backdrop
        self.has_description = has_description
        self.year = year
        self.years = years
        self.exclude_years = exclude_years
        self.start_year = start_year
        self.end_year = end_year
        self.content_rating = content_rating
        self.exclude_content_ratings = exclude_content_ratings
        self.studio_name = studio_name
        self.container = container
        self.exclude_containers = exclude_containers
        self.person_guid = person_guid
        self.person_name = person_name
        self.exclude_person_guid = exclude_person_guid
        self.exclude_person_name = exclude_person_name
        self.is_favorite = is_favorite
        self.is_played = is_played
        self.page = page
        self.per_page = per_page
        self.order_by = order_by
        self.order_desc = order_desc

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.per_page

    def service_kwargs(
        self,
        *,
        user_guid: uuid.UUID,
        max_age: int | None,
        allowed_media_types: list[MediaType] | None,
    ) -> dict:
        return {
            "library_guid": self.library_guid,
            "media_type": self.media_type,
            "parent_guid": self.parent_guid,
            "genre_id": self.genre_id,
            "genre_ids": self.genre_ids,
            "genre_names": self.genre_names,
            "exclude_genre_ids": self.exclude_genre_ids,
            "exclude_genre_names": self.exclude_genre_names,
            "availability": self.availability,
            "has_poster": self.has_poster,
            "has_backdrop": self.has_backdrop,
            "has_description": self.has_description,
            "platform_id": self.platform_id,
            "platform_ids": self.platform_ids,
            "exclude_platform_ids": self.exclude_platform_ids,
            "year": self.year,
            "years": self.years,
            "exclude_years": self.exclude_years,
            "start_year": self.start_year,
            "end_year": self.end_year,
            "content_rating": self.content_rating,
            "exclude_content_ratings": self.exclude_content_ratings,
            "studio_name": self.studio_name,
            "container": self.container,
            "exclude_containers": self.exclude_containers,
            "person_guid": self.person_guid,
            "person_name": self.person_name,
            "exclude_person_guid": self.exclude_person_guid,
            "exclude_person_name": self.exclude_person_name,
            "is_favorite": self.is_favorite,
            "is_played": self.is_played,
            "user_guid": user_guid,
            "search_term": self.search_term,
            "top_level_only": self.parent_guid is None,
            "max_age": max_age,
            "allowed_media_types": allowed_media_types,
        }
