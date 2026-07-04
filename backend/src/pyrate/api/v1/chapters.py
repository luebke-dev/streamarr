"""Media chapter endpoints."""

from __future__ import annotations

import json
import uuid

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
from pyrate.services.media_access import require_media_read_access

router = APIRouter()


class ChapterRead(BaseModel):
    title: str | None = None
    start_seconds: float = Field(ge=0)
    end_seconds: float | None = Field(default=None, ge=0)
    image_path: str | None = None


class ChapterUpdate(BaseModel):
    chapters: list[ChapterRead] = []


def _load_extra_data(media_item: MediaItem) -> dict:
    return load_extra_data(media_item)


def _parse_chapters(extra_data: dict) -> list[ChapterRead]:
    raw_chapters = extra_data.get("chapters") or extra_data.get("chapter_points") or []
    if not isinstance(raw_chapters, list):
        return []

    chapters: list[ChapterRead] = []
    for index, raw in enumerate(raw_chapters):
        if not isinstance(raw, dict):
            continue
        start = (
            raw.get("start_seconds")
            if raw.get("start_seconds") is not None
            else raw.get("start")
        )
        if start is None:
            start = raw.get("time")
        try:
            start_seconds = float(start)
        except (TypeError, ValueError):
            continue

        end = raw.get("end_seconds") if raw.get("end_seconds") is not None else raw.get("end")
        try:
            end_seconds = float(end) if end is not None else None
        except (TypeError, ValueError):
            end_seconds = None

        title = raw.get("title") or raw.get("name") or raw.get("label")
        chapters.append(
            ChapterRead(
                title=title if isinstance(title, str) else f"Chapter {index + 1}",
                start_seconds=start_seconds,
                end_seconds=end_seconds,
                image_path=raw.get("image_path") or raw.get("thumbnail_path"),
            )
        )

    return sorted(chapters, key=lambda chapter: chapter.start_seconds)


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


@router.get("/{item_guid}/chapters", response_model=list[ChapterRead])
async def get_media_chapters(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get chapter points for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return _parse_chapters(_load_extra_data(media_item))


@router.put("/{item_guid}/chapters", response_model=list[ChapterRead])
async def replace_media_chapters(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: ChapterUpdate,
):
    """Replace chapter points for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    chapters = sorted(body.chapters, key=lambda chapter: chapter.start_seconds)
    for current, next_chapter in zip(chapters, chapters[1:], strict=False):
        if current.end_seconds is not None and current.end_seconds < current.start_seconds:
            raise HTTPException(status_code=400, detail="Chapter end is before start")
        if current.end_seconds is None:
            current.end_seconds = next_chapter.start_seconds

    if chapters and chapters[-1].end_seconds is not None:
        last = chapters[-1]
        if last.end_seconds < last.start_seconds:
            raise HTTPException(status_code=400, detail="Chapter end is before start")

    extra_data = dict(_load_extra_data(media_item))
    extra_data["chapters"] = [
        chapter.model_dump(exclude_none=True) for chapter in chapters
    ]
    media_item.extra_data = extra_data
    await db.commit()
    await db.refresh(media_item)

    return _parse_chapters(_load_extra_data(media_item))
