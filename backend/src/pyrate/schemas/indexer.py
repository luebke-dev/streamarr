import uuid
from datetime import datetime

from pydantic import BaseModel

from pyrate.schemas.base import BaseSchema


class IndexerCategoryCreate(BaseSchema):
    label: str
    category_type: str  # 'movie', 'show', 'game', 'music', 'audiobook', 'book'
    newznab_category_id: int | None = None
    language: list[str] | None = None
    resolution: list[str] | None = None
    platform: str | None = None


class IndexerCategoryRead(IndexerCategoryCreate):
    guid: uuid.UUID
    indexer_guid: uuid.UUID


class _IndexerCommon(BaseSchema):
    """Fields shared by every indexer schema, excluding the secret api_key."""

    host: str
    ssl: bool = False
    verify_ssl: bool = True
    type: str
    label: str
    enabled: bool = True
    supports_rss: bool = True
    rss_enabled: bool = False
    priority: int = 25


class IndexerCreate(_IndexerCommon):
    api_key: str
    categories: list[IndexerCategoryCreate] = []


class IndexerUpdate(_IndexerCommon):
    # Optional so the frontend can omit it when the operator hasn't touched
    # the field — the service keeps the existing key.
    api_key: str | None = None
    categories: list[IndexerCategoryCreate] = []


class IndexerRead(_IndexerCommon):
    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    last_rss_sync_at: datetime | None = None
    categories: list[IndexerCategoryRead] = []
    # Boolean flag so the admin UI can show "configured" without ever seeing
    # the real secret.
    api_key_configured: bool = False


# Returned by the /caps endpoint
class NewznabCategory(BaseModel):
    id: int
    name: str
    subcategories: list["NewznabCategory"] = []


class NewznabCapsResponse(BaseModel):
    connected: bool
    error: str | None = None
    categories: list[NewznabCategory] = []
