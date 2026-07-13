import uuid

from pydantic import BaseModel


class FavoriteStatusResponse(BaseModel):
    is_favorited: bool
    # True when the favorited root is monitored (auto-download/upgrade on).
    monitored: bool = False


class FavoriteListItem(BaseModel):
    guid: uuid.UUID
    media_item_guid: uuid.UUID
    title: str
    media_type: str
    poster_url: str | None = None


class FavoriteListResponse(BaseModel):
    items: list[FavoriteListItem]
    total: int
