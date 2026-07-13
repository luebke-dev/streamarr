import uuid
from datetime import datetime
from typing import TYPE_CHECKING


from streamarr.schemas.base import PaginatedResponse, BaseSchema

if TYPE_CHECKING:
    from .media import MediaItemRead


class ViewingHistoryBase(BaseSchema):
    content_type: str
    progress_seconds: int = 0
    duration_seconds: int | None = None
    progress_percentage: float = 0.0
    is_completed: bool = False


class ViewingHistoryCreate(BaseSchema):
    content_type: str
    content_guid: uuid.UUID | None = None  # Universal: works for any media type
    movie_guid: uuid.UUID | None = None
    episode_guid: uuid.UUID | None = None
    song_guid: uuid.UUID | None = None
    progress_seconds: int = 0
    duration_seconds: int | None = None
    progress_percentage: float | None = None  # For books: direct percentage
    extra_data: str | None = None  # For books: JSON with CFI position


class ViewingHistoryUpdate(BaseSchema):
    progress_seconds: int | None = None
    duration_seconds: int | None = None


class ViewingHistoryRead(ViewingHistoryBase):
    guid: uuid.UUID
    user_guid: uuid.UUID
    movie_guid: uuid.UUID | None = None
    episode_guid: uuid.UUID | None = None
    song_guid: uuid.UUID | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    created_at: datetime
    updated_at: datetime
    last_watched_at: datetime


class ViewingHistoryWithContent(ViewingHistoryRead):
    media_item: "MediaItemRead | None" = None
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None


class ContinueWatchingItem(BaseSchema):
    guid: uuid.UUID
    content_type: str
    movie_guid: uuid.UUID | None = None
    episode_guid: uuid.UUID | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    progress_seconds: int
    duration_seconds: int | None
    progress_percentage: float
    last_watched_at: datetime
    media_item: "MediaItemRead | None" = None
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None


class UserViewingStats(BaseSchema):
    total_watched: int
    total_movies_watched: int
    total_episodes_watched: int
    total_watch_time_seconds: int
    total_watch_time_hours: float
    completed_content: int
    in_progress_content: int


class RecentlyWatchedItem(BaseSchema):
    guid: uuid.UUID
    content_type: str
    movie_guid: uuid.UUID | None = None
    episode_guid: uuid.UUID | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    progress_seconds: int
    duration_seconds: int | None
    progress_percentage: float
    is_completed: bool
    last_watched_at: datetime
    media_item: "MediaItemRead | None" = None
    show_title: str | None = None
    season_number: int | None = None
    episode_number: int | None = None


class PaginatedViewingHistoryResponse(PaginatedResponse[ViewingHistoryWithContent]):
    pass


class PaginatedContinueWatchingResponse(PaginatedResponse[ContinueWatchingItem]):
    pass


class PaginatedRecentlyWatchedResponse(PaginatedResponse[RecentlyWatchedItem]):
    pass
