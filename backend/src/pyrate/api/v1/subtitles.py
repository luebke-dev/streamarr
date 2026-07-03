"""Media subtitle metadata endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from starlette.responses import PlainTextResponse

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.models.media import MediaItem
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY
from pyrate.services.settings import SettingsService
from pyrate.services.subtitle_provider import (
    SubtitleProviderError,
    SubtitleProviderService,
)
from pyrate.utils.age_rating import is_allowed
from pyrate.utils.net import UnsafeUrlError, safe_get

router = APIRouter()

_REMOTE_SUBTITLE_MAX_BYTES = 2_000_000


class SubtitleTrack(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid.uuid4()), min_length=1)
    language: str = Field(min_length=2, max_length=16)
    title: str | None = None
    format: str | None = None
    path: str | None = None
    url: str | None = None
    is_forced: bool = False
    is_default: bool = False


class SubtitleTracksUpdate(BaseModel):
    subtitles: list[SubtitleTrack] = []


class SubtitleProviderResult(BaseModel):
    provider: str
    provider_id: str
    language: str
    title: str | None = None
    file_name: str | None = None
    release_group: str | None = None
    format: str | None = None
    path: str | None = None
    url: str | None = None
    score: float | None = None
    match_score: float | None = None
    match_reasons: list[str] = []
    downloads: int | None = None
    is_forced: bool = False
    is_hearing_impaired: bool = False


class SubtitleProviderSearchResponse(BaseModel):
    items: list[SubtitleProviderResult]
    total: int


class SubtitleProviderDownload(BaseModel):
    provider: str = Field(min_length=1, max_length=100)
    provider_id: str = Field(min_length=1, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    make_default: bool = False


class SubtitleProviderDownloadResponse(BaseModel):
    status: Literal["downloaded"]
    subtitle: SubtitleTrack


class SubtitleUpload(BaseModel):
    language: str = Field(min_length=2, max_length=16)
    content: str = Field(min_length=1, max_length=2_000_000)
    file_name: str | None = Field(default=None, max_length=255)
    title: str | None = Field(default=None, max_length=255)
    format: str = Field(default="srt", max_length=16)
    is_forced: bool = False
    make_default: bool = False


class SubtitleUploadResponse(BaseModel):
    status: Literal["uploaded"]
    subtitle: SubtitleTrack


def _load_extra_data(media_item: MediaItem) -> dict:
    if not media_item.extra_data:
        return {}
    try:
        data = json.loads(media_item.extra_data)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _parse_subtitles(extra_data: dict) -> list[SubtitleTrack]:
    raw_subtitles = extra_data.get("subtitles") or extra_data.get("subtitle_tracks") or []
    if not isinstance(raw_subtitles, list):
        return []

    subtitles: list[SubtitleTrack] = []
    for raw in raw_subtitles:
        if not isinstance(raw, dict):
            continue
        language = raw.get("language") or raw.get("lang")
        if not isinstance(language, str) or not language.strip():
            continue
        subtitles.append(
            SubtitleTrack(
                id=str(raw.get("id") or raw.get("guid") or uuid.uuid4()),
                language=language.strip(),
                title=raw.get("title") if isinstance(raw.get("title"), str) else None,
                format=raw.get("format") if isinstance(raw.get("format"), str) else None,
                path=raw.get("path") if isinstance(raw.get("path"), str) else None,
                url=raw.get("url") if isinstance(raw.get("url"), str) else None,
                is_forced=bool(raw.get("is_forced") or raw.get("forced")),
                is_default=bool(raw.get("is_default") or raw.get("default")),
            )
        )
    return subtitles


async def _get_visible_media_item(
    db: DatabaseSession,
    item_guid: uuid.UUID,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
) -> MediaItem:
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    library_name = MEDIA_TYPE_TO_LIBRARY.get(media_item.media_type.value)
    if library_name and library_name not in permissions.allowed_libraries:
        raise HTTPException(
            status_code=403,
            detail=f"Access denied to {library_name} library",
        )

    if not current_user.is_superuser and not is_allowed(
        media_item.min_age, current_user.parental_max_age
    ):
        raise HTTPException(status_code=404, detail="Media item not found")

    return media_item


def _store_subtitles(media_item: MediaItem, subtitles: list[SubtitleTrack]) -> None:
    extra_data = _load_extra_data(media_item)
    extra_data["subtitles"] = [
        subtitle.model_dump(exclude_none=True) for subtitle in subtitles
    ]
    media_item.extra_data = json.dumps(extra_data)


def _store_uploaded_subtitle(
    media_item: MediaItem,
    *,
    subtitle_id: str,
    upload: SubtitleUpload,
    actor_guid: uuid.UUID,
) -> None:
    extra_data = _load_extra_data(media_item)
    uploaded = extra_data.get("uploaded_subtitles")
    if not isinstance(uploaded, dict):
        uploaded = {}
    uploaded[subtitle_id] = {
        "content": upload.content,
        "file_name": upload.file_name,
        "format": upload.format,
        "language": upload.language,
        "uploaded_by": str(actor_guid),
        "uploaded_at": datetime.now(UTC).isoformat(),
    }
    extra_data["uploaded_subtitles"] = uploaded
    media_item.extra_data = json.dumps(extra_data)


def _remove_uploaded_subtitle(media_item: MediaItem, subtitle_id: str) -> None:
    extra_data = _load_extra_data(media_item)
    uploaded = extra_data.get("uploaded_subtitles")
    if not isinstance(uploaded, dict):
        return
    uploaded.pop(subtitle_id, None)
    if uploaded:
        extra_data["uploaded_subtitles"] = uploaded
    else:
        extra_data.pop("uploaded_subtitles", None)
    media_item.extra_data = json.dumps(extra_data)


def _get_uploaded_subtitle(media_item: MediaItem, subtitle_id: str) -> dict | None:
    uploaded = _load_extra_data(media_item).get("uploaded_subtitles")
    if not isinstance(uploaded, dict):
        return None
    raw = uploaded.get(subtitle_id)
    return raw if isinstance(raw, dict) else None


async def _fetch_remote_subtitle(url: str) -> str:
    try:
        response = await safe_get(url, timeout=15)
        response.raise_for_status()
    except UnsafeUrlError as e:
        raise HTTPException(status_code=404, detail="Subtitle content not found") from e
    except httpx.HTTPError as e:
        raise HTTPException(status_code=502, detail="Subtitle download failed") from e

    content = response.content
    if len(content) > _REMOTE_SUBTITLE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="Subtitle content too large")

    encoding = response.encoding or "utf-8"
    try:
        return content.decode(encoding, errors="replace")
    except LookupError:
        return content.decode("utf-8", errors="replace")


def _unset_language_default(
    subtitles: list[SubtitleTrack],
    language: str,
) -> list[SubtitleTrack]:
    return [
        subtitle.model_copy(update={"is_default": False})
        if subtitle.language == language
        else subtitle
        for subtitle in subtitles
    ]


async def _get_subtitle_provider_service(db: DatabaseSession) -> SubtitleProviderService:
    providers = await SettingsService(db).get("subtitles.providers", [])
    enabled = providers if isinstance(providers, list) else []
    provider_urls = await SettingsService(db).get("subtitles.provider_urls", {})
    urls = provider_urls if isinstance(provider_urls, dict) else {}
    provider_api_keys = await SettingsService(db).get("subtitles.provider_api_keys", {})
    api_keys = provider_api_keys if isinstance(provider_api_keys, dict) else {}
    return SubtitleProviderService(enabled, urls, api_keys)


@router.get("/{item_guid}/subtitles", response_model=list[SubtitleTrack])
async def get_media_subtitles(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get managed subtitle tracks for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return _parse_subtitles(_load_extra_data(media_item))


@router.put("/{item_guid}/subtitles", response_model=list[SubtitleTrack])
async def replace_media_subtitles(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: SubtitleTracksUpdate,
):
    """Replace managed subtitle tracks for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    _store_subtitles(media_item, body.subtitles)
    await db.commit()
    await db.refresh(media_item)
    return _parse_subtitles(_load_extra_data(media_item))


@router.get(
    "/{item_guid}/subtitles/search",
    response_model=SubtitleProviderSearchResponse,
)
async def search_media_subtitle_providers(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    language: str | None = None,
    provider: str | None = None,
    query: str | None = None,
):
    """Search configured subtitle provider results for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    service = await _get_subtitle_provider_service(db)
    items = [
        SubtitleProviderResult(**candidate)
        for candidate in await service.search_async(
            media_item,
            language=language,
            provider=provider,
            query=query,
        )
    ]
    return SubtitleProviderSearchResponse(items=items, total=len(items))


@router.post(
    "/{item_guid}/subtitles/download",
    response_model=SubtitleProviderDownloadResponse,
)
async def download_media_subtitle_from_provider(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: SubtitleProviderDownload,
):
    """Attach a subtitle track from a configured provider result."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    service = await _get_subtitle_provider_service(db)
    try:
        candidate = await service.get_candidate_async(
            media_item,
            provider=body.provider,
            provider_id=body.provider_id,
        )
        candidate = await service.resolve_download_async(candidate)
    except SubtitleProviderError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    subtitle_id = f"{candidate['provider']}:{candidate['provider_id']}"
    subtitle = SubtitleTrack(
        id=subtitle_id,
        language=candidate["language"],
        title=body.title or candidate.get("title") or candidate.get("file_name"),
        format=candidate.get("format"),
        path=candidate.get("path"),
        url=candidate.get("url"),
        is_forced=candidate.get("is_forced", False),
        is_default=body.make_default,
    )

    subtitles = _parse_subtitles(_load_extra_data(media_item))
    remaining = [existing for existing in subtitles if existing.id != subtitle_id]
    if body.make_default:
        remaining = _unset_language_default(remaining, subtitle.language)
    remaining.append(subtitle)

    _store_subtitles(media_item, remaining)
    await db.commit()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="subtitle.download",
            message=(
                f"Downloaded {subtitle.language} subtitle from "
                f"{candidate['provider']} for {media_item.title}"
            ),
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "provider": candidate["provider"],
                    "provider_id": candidate["provider_id"],
                    "subtitle_id": subtitle.id,
                    "language": subtitle.language,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return SubtitleProviderDownloadResponse(status="downloaded", subtitle=subtitle)


@router.post("/{item_guid}/subtitles/upload", response_model=SubtitleUploadResponse)
async def upload_media_subtitle(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    body: SubtitleUpload,
):
    """Upload a text subtitle for a visible media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)

    subtitle_format = body.format.lower().lstrip(".")
    if subtitle_format not in {"srt", "vtt", "ass", "ssa"}:
        raise HTTPException(status_code=422, detail="Unsupported subtitle format")

    subtitle_id = f"upload:{uuid.uuid4()}"
    subtitle = SubtitleTrack(
        id=subtitle_id,
        language=body.language,
        title=body.title or body.file_name,
        format=subtitle_format,
        path=f"uploaded:{subtitle_id}",
        is_forced=body.is_forced,
        is_default=body.make_default,
    )

    subtitles = _parse_subtitles(_load_extra_data(media_item))
    if body.make_default:
        subtitles = _unset_language_default(subtitles, subtitle.language)
    subtitles.append(subtitle)

    _store_subtitles(media_item, subtitles)
    _store_uploaded_subtitle(
        media_item,
        subtitle_id=subtitle_id,
        upload=body.model_copy(update={"format": subtitle_format}),
        actor_guid=current_user.guid,
    )
    await db.commit()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="subtitle.upload",
            message=f"Uploaded {subtitle.language} subtitle for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "subtitle_id": subtitle.id,
                    "language": subtitle.language,
                    "format": subtitle.format,
                    "file_name": body.file_name,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return SubtitleUploadResponse(status="uploaded", subtitle=subtitle)


@router.get("/{item_guid}/subtitles/{subtitle_id}/content")
async def get_media_subtitle_content(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    subtitle_id: str,
):
    """Return uploaded or URL-backed managed subtitle text for playback clients."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    subtitles = _parse_subtitles(_load_extra_data(media_item))
    subtitle = next((item for item in subtitles if item.id == subtitle_id), None)
    if not subtitle:
        raise HTTPException(status_code=404, detail="Subtitle not found")

    uploaded = _get_uploaded_subtitle(media_item, subtitle_id)
    if uploaded and isinstance(uploaded.get("content"), str):
        content = uploaded["content"]
    elif subtitle.url:
        content = await _fetch_remote_subtitle(subtitle.url)
    else:
        raise HTTPException(status_code=404, detail="Subtitle content not found")

    media_type = "text/vtt" if subtitle.format == "vtt" else "text/plain"
    return PlainTextResponse(content, media_type=media_type)


@router.delete("/{item_guid}/subtitles/{subtitle_id}", status_code=204)
async def delete_media_subtitle(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    subtitle_id: str,
):
    """Delete a managed subtitle track for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    subtitles = _parse_subtitles(_load_extra_data(media_item))
    remaining = [subtitle for subtitle in subtitles if subtitle.id != subtitle_id]
    if len(remaining) == len(subtitles):
        raise HTTPException(status_code=404, detail="Subtitle not found")

    _store_subtitles(media_item, remaining)
    _remove_uploaded_subtitle(media_item, subtitle_id)
    await db.commit()
