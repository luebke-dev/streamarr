"""Media lyrics endpoints."""

from __future__ import annotations

import json
import uuid
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from pyrate.utils.extra_data import load_extra_data
from pyrate.models.media import MediaItem
from pyrate.schemas.activity_log import ActivityLogCreate
from pyrate.services.activity_log import ActivityLogService
from pyrate.services.media_access import require_media_read_access
from pyrate.services.settings import SettingsService
from pyrate.utils.net import safe_get

router = APIRouter()


class LyricsResponse(BaseModel):
    lyrics: str = Field(min_length=1)
    synced: bool = False
    source: str | None = None


class LyricsUpdate(BaseModel):
    lyrics: str = Field(min_length=1)
    synced: bool = False
    source: str | None = None


class RemoteLyricsResult(BaseModel):
    provider: str
    provider_id: str
    title: str | None = None
    artist: str | None = None
    lyrics: str = Field(min_length=1)
    synced: bool = False
    source: str | None = None
    score: float | None = None


class RemoteLyricsSearchResponse(BaseModel):
    items: list[RemoteLyricsResult]
    total: int


class RemoteLyricsDownloadRequest(BaseModel):
    provider: str = Field(min_length=1)
    provider_id: str = Field(min_length=1)


def _load_extra_data(media_item: MediaItem) -> dict:
    return load_extra_data(media_item)


def _parse_lyrics(extra_data: dict) -> LyricsResponse | None:
    raw = extra_data.get("lyrics")
    if isinstance(raw, str) and raw.strip():
        return LyricsResponse(lyrics=raw, synced=False)
    if not isinstance(raw, dict):
        return None

    text = raw.get("lyrics") or raw.get("text") or raw.get("content")
    if not isinstance(text, str) or not text.strip():
        return None
    return LyricsResponse(
        lyrics=text,
        synced=bool(raw.get("synced")),
        source=raw.get("source") if isinstance(raw.get("source"), str) else None,
    )


def _coerce_remote_lyrics_result(raw: object, index: int) -> RemoteLyricsResult | None:
    if not isinstance(raw, dict):
        return None

    provider = raw.get("provider") or raw.get("source") or raw.get("name")
    if not isinstance(provider, str) or not provider.strip():
        provider = "metadata"

    synced_text = raw.get("syncedLyrics") or raw.get("synced_lyrics")
    plain_text = raw.get("plainLyrics") or raw.get("plain_lyrics")
    text = (
        raw.get("lyrics")
        or raw.get("text")
        or raw.get("content")
        or synced_text
        or plain_text
    )
    if not isinstance(text, str) or not text.strip():
        return None

    provider_id = (
        raw.get("provider_id")
        or raw.get("remote_id")
        or raw.get("id")
        or raw.get("key")
        or raw.get("url")
        or f"{provider}:{index}"
    )
    provider_id = str(provider_id).strip()
    if not provider_id:
        provider_id = f"{provider}:{index}"

    score = raw.get("score")
    try:
        score = float(score) if score is not None else None
    except (TypeError, ValueError):
        score = None

    title = raw.get("title") or raw.get("trackName") or raw.get("track_name")
    artist = (
        raw.get("artist")
        or raw.get("artistName")
        or raw.get("artist_name")
        or raw.get("album_artist")
    )
    source = raw.get("source") or provider

    return RemoteLyricsResult(
        provider=provider.strip(),
        provider_id=provider_id,
        title=title if isinstance(title, str) and title.strip() else None,
        artist=artist if isinstance(artist, str) and artist.strip() else None,
        lyrics=text,
        synced=bool(raw.get("synced") or synced_text),
        source=source if isinstance(source, str) and source.strip() else None,
        score=score,
    )


def _remote_lyrics_candidates(extra_data: dict) -> list[RemoteLyricsResult]:
    candidates: list[RemoteLyricsResult] = []
    for key in ("remote_lyrics", "lyrics_results", "lyric_provider_results"):
        raw_items = extra_data.get(key)
        if isinstance(raw_items, dict):
            raw_items = raw_items.get("items") or raw_items.get("results")
        if not isinstance(raw_items, list):
            continue
        for raw in raw_items:
            result = _coerce_remote_lyrics_result(raw, len(candidates))
            if result:
                candidates.append(result)
    return candidates


def _network_payload_candidates(
    provider_name: str,
    payload: Any,
) -> list[RemoteLyricsResult]:
    if isinstance(payload, dict):
        raw_items = payload.get("items") or payload.get("results") or payload.get("data")
    else:
        raw_items = payload
    if not isinstance(raw_items, list):
        return []

    candidates: list[RemoteLyricsResult] = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        raw.setdefault("provider", provider_name)
        result = _coerce_remote_lyrics_result(raw, len(candidates))
        if result:
            candidates.append(result)
    return candidates


def _lyrics_search_params(
    provider_name: str,
    media_item: MediaItem,
    *,
    query: str | None,
) -> dict[str, Any]:
    extra_data = _load_extra_data(media_item)
    artist = extra_data.get("artist") or extra_data.get("album_artist")
    album = extra_data.get("album") or extra_data.get("album_title")
    duration = extra_data.get("duration") or extra_data.get("duration_seconds")
    if provider_name == "lrclib":
        params = {
            "track_name": query or media_item.title,
            "artist_name": artist if isinstance(artist, str) else None,
            "album_name": album if isinstance(album, str) else None,
            "duration": duration,
        }
        return {key: value for key, value in params.items() if value is not None}

    return {
        "title": media_item.title,
        "query": query or media_item.title,
        "artist": artist if isinstance(artist, str) else None,
        "album": album if isinstance(album, str) else None,
        "duration": duration,
    }


async def _network_remote_lyrics_candidates(
    media_item: MediaItem,
    *,
    db: DatabaseSession,
    query: str | None,
    provider: str | None,
) -> list[RemoteLyricsResult]:
    settings = SettingsService(db)
    enabled = await settings.get("lyrics.providers", [])
    enabled_providers = {
        item.strip().lower()
        for item in (enabled if isinstance(enabled, list) else [])
        if isinstance(item, str) and item.strip()
    }
    raw_urls = await settings.get("lyrics.provider_urls", {})
    provider_urls = {
        key.strip().lower(): url.strip()
        for key, url in (raw_urls if isinstance(raw_urls, dict) else {}).items()
        if isinstance(key, str) and key.strip() and isinstance(url, str) and url.strip()
    }
    raw_api_keys = await settings.get("lyrics.provider_api_keys", {})
    api_keys = {
        key.strip().lower(): api_key.strip()
        for key, api_key in (raw_api_keys if isinstance(raw_api_keys, dict) else {}).items()
        if isinstance(key, str) and key.strip() and isinstance(api_key, str) and api_key.strip()
    }

    provider_filter = provider.strip().lower() if provider else None
    provider_urls = {
        key: url
        for key, url in provider_urls.items()
        if (not enabled_providers or key in enabled_providers)
        and (not provider_filter or key == provider_filter)
    }
    if not provider_urls:
        return []

    items: list[RemoteLyricsResult] = []
    async with httpx.AsyncClient(timeout=httpx.Timeout(10.0)) as client:
        for provider_name, url in provider_urls.items():
            headers = None
            if api_key := api_keys.get(provider_name):
                headers = {"Authorization": f"Bearer {api_key}"}
            try:
                response = await safe_get(
                    url,
                    client=client,
                    params=_lyrics_search_params(
                        provider_name,
                        media_item,
                        query=query,
                    ),
                    headers=headers,
                )
                response.raise_for_status()
                payload = response.json()
            except Exception as exc:
                raise HTTPException(
                    status_code=502,
                    detail=f"Lyrics provider '{provider_name}' request failed: {exc}",
                ) from exc
            items.extend(_network_payload_candidates(provider_name, payload))
    return items


def _dedupe_remote_lyrics_results(
    items: list[RemoteLyricsResult],
) -> list[RemoteLyricsResult]:
    deduped: dict[tuple[str, str], RemoteLyricsResult] = {}
    for item in items:
        deduped[(item.provider.casefold(), item.provider_id)] = item
    return sorted(
        deduped.values(),
        key=lambda item: item.score if item.score is not None else 0,
        reverse=True,
    )


def _matches_remote_lyrics_result(
    result: RemoteLyricsResult,
    *,
    query: str | None,
    provider: str | None,
) -> bool:
    if provider and result.provider.casefold() != provider.casefold():
        return False

    if not query:
        return True

    needle = query.casefold()
    haystack = " ".join(
        value
        for value in (
            result.provider,
            result.provider_id,
            result.title,
            result.artist,
            result.source,
            result.lyrics,
        )
        if value
    ).casefold()
    return needle in haystack


async def _get_visible_media_item(
    db: DatabaseSession,
    item_guid: uuid.UUID,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
) -> MediaItem:
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    require_media_read_access(
        current_user,
        permissions,
        media_item,
        hide_age_denials=True,
    )
    return media_item


@router.get("/{item_guid}/lyrics", response_model=LyricsResponse)
async def get_media_lyrics(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get lyrics for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    lyrics = _parse_lyrics(_load_extra_data(media_item))
    if not lyrics:
        raise HTTPException(status_code=404, detail="Lyrics not found")
    return lyrics


@router.get("/{item_guid}/lyrics/search", response_model=RemoteLyricsSearchResponse)
async def search_remote_lyrics(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    query: str | None = None,
    provider: str | None = None,
):
    """Search configured remote lyrics candidates for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    items = [
        result
        for result in _remote_lyrics_candidates(_load_extra_data(media_item))
        if _matches_remote_lyrics_result(result, query=query, provider=provider)
    ]
    items.extend(
        result
        for result in await _network_remote_lyrics_candidates(
            media_item,
            db=db,
            query=query,
            provider=provider,
        )
        if _matches_remote_lyrics_result(result, query=query, provider=provider)
    )
    items = _dedupe_remote_lyrics_results(items)
    return RemoteLyricsSearchResponse(items=items, total=len(items))


@router.put("/{item_guid}/lyrics", response_model=LyricsResponse)
async def replace_media_lyrics(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: LyricsUpdate,
):
    """Replace lyrics for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    extra_data = dict(_load_extra_data(media_item))
    extra_data["lyrics"] = body.model_dump(exclude_none=True)
    media_item.extra_data = extra_data
    await db.commit()
    await db.refresh(media_item)

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="lyrics.update",
            message=f"Updated lyrics for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "synced": body.synced,
                    "source": body.source,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    lyrics = _parse_lyrics(_load_extra_data(media_item))
    if not lyrics:
        raise HTTPException(status_code=500, detail="Lyrics were not saved")
    return lyrics


@router.post("/{item_guid}/lyrics/download", response_model=LyricsResponse)
async def download_remote_lyrics(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: RemoteLyricsDownloadRequest,
):
    """Apply a configured remote lyrics candidate to a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    extra_data = dict(_load_extra_data(media_item))
    selected = next(
        (
            result
            for result in _remote_lyrics_candidates(extra_data)
            if result.provider.casefold() == body.provider.casefold()
            and result.provider_id == body.provider_id
        ),
        None,
    )
    if not selected:
        selected = next(
            (
                result
                for result in await _network_remote_lyrics_candidates(
                    media_item,
                    db=db,
                    query=None,
                    provider=body.provider,
                )
                if result.provider.casefold() == body.provider.casefold()
                and result.provider_id == body.provider_id
            ),
            None,
        )
    if not selected:
        raise HTTPException(status_code=404, detail="Remote lyrics not found")

    extra_data["lyrics"] = LyricsUpdate(
        lyrics=selected.lyrics,
        synced=selected.synced,
        source=selected.source or selected.provider,
    ).model_dump(exclude_none=True)
    media_item.extra_data = extra_data
    await db.commit()
    await db.refresh(media_item)

    lyrics = _parse_lyrics(_load_extra_data(media_item))
    if not lyrics:
        raise HTTPException(status_code=500, detail="Lyrics were not saved")

    await ActivityLogService(db).create(
        ActivityLogCreate(
            event_type="lyrics.download",
            message=f"Downloaded lyrics from {selected.provider} for {media_item.title}",
            entity_type="media_item",
            entity_guid=media_item.guid,
            extra_data=json.dumps(
                {
                    "provider": selected.provider,
                    "provider_id": selected.provider_id,
                    "synced": selected.synced,
                    "source": selected.source,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )
    return lyrics


@router.delete("/{item_guid}/lyrics", status_code=204)
async def delete_media_lyrics(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
):
    """Delete lyrics for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    extra_data = dict(_load_extra_data(media_item))
    extra_data.pop("lyrics", None)
    media_item.extra_data = extra_data
    await db.commit()
