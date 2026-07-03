import uuid
from datetime import datetime


from pyrate.schemas.base import BaseSchema


class _DownloaderCommon(BaseSchema):
    """Fields shared by every downloader schema, excluding the secret api_key."""

    host: str
    ssl: bool = False
    verify_ssl: bool = True
    type: str
    label: str


class DownloaderCreate(_DownloaderCommon):
    api_key: str | None = None


class DownloaderUpdate(_DownloaderCommon):
    # Optional: empty / missing means "keep the existing value".
    api_key: str | None = None


class DownloaderRead(_DownloaderCommon):
    guid: uuid.UUID
    created_at: datetime
    updated_at: datetime
    api_key_configured: bool = False
