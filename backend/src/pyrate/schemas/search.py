import uuid
from datetime import datetime
from enum import StrEnum
from typing import Generic, TypeVar

from pydantic import BaseModel, Field, model_validator

from pyrate.schemas.base import BaseSchema

T = TypeVar("T")


class SearchType(StrEnum):
    """Enum of available search types."""

    MOVIES = "movies"
    SHOWS = "shows"
    GAMES = "games"
    MUSIC = "music"
    BOOKS = "books"
    ALL = "all"


class SortOrder(StrEnum):
    """Enum for sort order."""

    ASC = "asc"
    DESC = "desc"


class SearchSortBy(StrEnum):
    """Enum of available sort fields."""

    RELEVANCE = "_score"
    TITLE = "title.keyword"
    RELEASE_DATE = "release_date"
    FIRST_AIR_DATE = "first_air_date"
    CREATED_AT = "created_at"
    UPDATED_AT = "updated_at"


class SearchRequest(BaseSchema):
    """Schema for search requests."""

    query: str | None = Field(default=None, max_length=500, description="Search term (optional in filter-only mode)")
    search_type: SearchType = Field(default=SearchType.ALL, description="Search type")

    # DB filters (for browse mode without a query)
    genre_id: int | None = Field(default=None, description="Genre id filter")
    genre_ids: list[int] = Field(
        default_factory=list,
        description="Filter by any of these genre ids",
    )
    exclude_genre_ids: list[int] = Field(
        default_factory=list,
        description="Exclude items with any of these genre ids",
    )
    exclude_genres: list[str] = Field(
        default_factory=list,
        description="Exclude items with any of these genre names",
    )
    platform_id: int | None = Field(default=None, description="Platform id filter (games)")
    platform_ids: list[int] = Field(
        default_factory=list,
        description="Filter by any of these platform ids",
    )
    exclude_platform_ids: list[int] = Field(
        default_factory=list,
        description="Exclude items with any of these platform ids",
    )
    media_type: str | None = Field(default=None, description="Media type filter (MOVIES, SHOWS, GAMES, MUSIC, BOOKS)")
    library_guid: uuid.UUID | None = Field(default=None, description="Deprecated: use media_type instead")
    availability: str | None = Field(default=None, description="Availability filter: 'local' (has files), 'releases' (has releases), 'none' (nothing)")
    has_poster: bool | None = Field(default=None, description="Filter by poster availability")
    has_backdrop: bool | None = Field(default=None, description="Filter by backdrop availability")
    has_description: bool | None = Field(default=None, description="Filter by description availability")
    is_favorite: bool | None = Field(default=None, description="Filter by favorite state")
    is_played: bool | None = Field(default=None, description="Filter by played state")
    person_guid: uuid.UUID | None = Field(default=None, description="Person/cast member filter")
    person_name: str | None = Field(
        default=None,
        max_length=200,
        description="Person/cast member name filter",
    )
    exclude_person_guid: uuid.UUID | None = Field(
        default=None, description="Exclude items with this person/cast member"
    )
    exclude_person_name: str | None = Field(
        default=None,
        max_length=200,
        description="Exclude items with this person/cast member name",
    )
    studio_name: str | None = Field(default=None, max_length=200, description="Studio or production company filter")
    container: str | None = Field(default=None, max_length=50, description="Media file container/format filter")
    exclude_containers: list[str] = Field(
        default_factory=list,
        description="Exclude items with any of these media file containers/formats",
    )
    content_rating: str | None = Field(default=None, max_length=64, description="Content rating filter")
    exclude_content_ratings: list[str] = Field(
        default_factory=list,
        description="Exclude items with any of these content ratings",
    )

    @model_validator(mode="after")
    def check_query_or_filters(self):
        has_query = self.query and self.query.strip()
        has_filters = (
            self.genre_id
            or self.genre_ids
            or self.genres
            or self.exclude_genre_ids
            or self.exclude_genres
            or self.platform_id
            or self.platform_ids
            or self.exclude_platform_ids
            or self.media_type
            or self.library_guid
            or self.availability is not None
            or self.has_poster is not None
            or self.has_backdrop is not None
            or self.has_description is not None
            or self.is_favorite is not None
            or self.is_played is not None
            or self.person_guid is not None
            or self.person_name
            or self.exclude_person_guid is not None
            or self.exclude_person_name
            or self.studio_name
            or self.container
            or self.exclude_containers
            or self.content_rating
            or self.exclude_content_ratings
            or self.years
            or self.exclude_years
            or self.year_from is not None
            or self.year_to is not None
            or self.sort_by != SearchSortBy.RELEVANCE
            or self.sort_order != SortOrder.DESC
        )
        if not has_query and not has_filters:
            raise ValueError("Either query or at least one filter must be provided")
        return self

    # Pagination
    page: int = Field(default=1, ge=1, description="Page number")
    per_page: int = Field(
        default=20, ge=1, le=100, description="Results per page"
    )

    # Sorting
    sort_by: SearchSortBy = Field(
        default=SearchSortBy.RELEVANCE, description="Sort field"
    )
    sort_order: SortOrder = Field(
        default=SortOrder.DESC, description="Sort order"
    )

    # Filters
    genres: list[str] = Field(default_factory=list, description="Genre filter")
    years: list[int] = Field(default_factory=list, description="Release years filter")
    exclude_years: list[int] = Field(
        default_factory=list, description="Release years to exclude"
    )
    year_from: int | None = Field(
        default=None, ge=1900, le=2100, description="Year from"
    )
    year_to: int | None = Field(default=None, ge=1900, le=2100, description="Year to")

    # Advanced search options
    fuzzy: bool = Field(default=True, description="Enable fuzzy search")
    boost_title: float = Field(
        default=2.0, ge=0.1, le=10.0, description="Title boost factor"
    )
    boost_original_title: float = Field(
        default=1.5, ge=0.1, le=10.0, description="Original-title boost factor"
    )
    boost_tagline: float = Field(
        default=1.2, ge=0.1, le=10.0, description="Tagline boost factor"
    )
    boost_description: float = Field(
        default=1.0, ge=0.1, le=10.0, description="Description boost factor"
    )


class SearchHit(BaseSchema):
    """Schema for an individual search result."""

    id: uuid.UUID | None = Field(
        default=None,
        description="Unique id of the item (None when not in the local DB)",
    )
    tmdb_id: int | None = Field(default=None, description="TMDB id")
    igdb_id: int | None = Field(default=None, description="IGDB id")
    spotify_id: str | None = Field(default=None, description="Spotify id")
    type: SearchType = Field(..., description="Item type")
    score: float = Field(..., description="Relevance score")

    # Basic info
    title: str = Field(..., description="Title")
    original_title: str | None = Field(default=None, description="Original title")
    description: str | None = Field(default=None, description="Description")
    tagline: str | None = Field(default=None, description="Tagline")

    # Media paths
    poster_path: str | None = Field(default=None, description="Poster path")
    backdrop_path: str | None = Field(default=None, description="Backdrop path")

    # Date info
    release_date: datetime | str | None = Field(
        default=None, description="Release date (movies)"
    )
    first_air_date: datetime | str | None = Field(
        default=None, description="First air date (shows)"
    )

    # Metadata
    genres: list[str] = Field(default_factory=list, description="Genres")
    genre_ids: list[int] = Field(
        default_factory=list, description="Genre ids (from provider)"
    )
    created_at: datetime | None = Field(default=None, description="Created-at timestamp")
    updated_at: datetime | None = Field(
        default=None, description="Updated-at timestamp"
    )

    # Show-specific extras
    status: str | None = Field(default=None, description="Status (shows only)")
    number_of_seasons: int | None = Field(
        default=None, description="Number of seasons (shows only)"
    )
    number_of_episodes: int | None = Field(
        default=None, description="Number of episodes (shows only)"
    )

    # Provider-specific fields
    popularity: float | None = Field(default=None, description="Popularity score")
    vote_average: float | None = Field(
        default=None, description="Average rating"
    )
    vote_count: int | None = Field(default=None, description="Vote count")

    # Source info
    source: str | None = Field(
        default=None, description="Data source (provider/local)"
    )
    in_library: bool = Field(
        default=False, description="Whether the item is already in the local library"
    )
    library_id: str | None = Field(
        default=None, description="Library guid when present in the library"
    )


class SearchFacet(BaseSchema):
    """Schema for a search facet."""

    key: str = Field(..., description="Facet key")
    doc_count: int = Field(..., description="Document count")


class SearchFacets(BaseSchema):
    """Schema for the full set of search facets."""

    genres: list[SearchFacet] = Field(
        default_factory=list, description="Genre facets"
    )
    years: list[SearchFacet] = Field(default_factory=list, description="Year facets")
    types: list[SearchFacet] = Field(default_factory=list, description="Type facets")


class SearchResponse(BaseSchema, Generic[T]):
    """Generic search-results response."""

    hits: list[T] = Field(..., description="Search results")
    total: int = Field(..., description="Total result count")
    page: int = Field(..., description="Current page")
    per_page: int = Field(..., description="Results per page")
    total_pages: int = Field(..., description="Total page count")

    # Search metadata
    query: str | None = Field(default=None, description="Query used")
    search_type: SearchType = Field(..., description="Search type used")
    took: int = Field(default=0, description="Search time in milliseconds")

    # Facets for advanced filtering
    facets: SearchFacets | None = Field(default=None, description="Available facets")

    # Source info
    source: str | None = Field(
        default=None, description="Source of results (provider/local)"
    )
    provider: str | None = Field(
        default=None, description="Provider name (tmdb/elasticsearch)"
    )

    # List search results (separate from media hits)
    list_hits: list[dict] = Field(
        default_factory=list, description="Matching lists (system, own, public)"
    )


class SearchHitsResponse(SearchResponse[SearchHit]):
    """Response for general search results."""

    pass


class SearchSuggestion(BaseSchema):
    """Schema for a search suggestion."""

    text: str = Field(..., description="Suggested text")
    score: float = Field(..., description="Relevance score")
    type: SearchType = Field(..., description="Suggestion type")


class SearchSuggestionsRequest(BaseModel):
    """Schema for search-suggestion requests."""

    query: str = Field(..., min_length=1, max_length=200, description="Search term")
    size: int = Field(default=5, ge=1, le=20, description="Number of suggestions")

