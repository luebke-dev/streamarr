"""Media attachment endpoints."""

from __future__ import annotations

import json
import uuid

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from streamarr.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
    UserPermissionsDep,
)
from streamarr.utils.extra_data import load_extra_data
from streamarr.models.media import MediaItem
from streamarr.services.media_access import (
    get_visible_media_item as _get_visible_media_item,
)

router = APIRouter()


class MediaAttachment(BaseModel):
    name: str = Field(min_length=1)
    path: str | None = None
    url: str | None = None
    mime_type: str | None = None
    attachment_type: str | None = None
    size_bytes: int | None = Field(default=None, ge=0)


class MediaAttachmentsUpdate(BaseModel):
    attachments: list[MediaAttachment] = []


def _load_extra_data(media_item: MediaItem) -> dict:
    return load_extra_data(media_item)


def _parse_attachments(extra_data: dict) -> list[MediaAttachment]:
    raw_attachments = extra_data.get("attachments") or extra_data.get("video_attachments") or []
    if not isinstance(raw_attachments, list):
        return []

    attachments: list[MediaAttachment] = []
    for raw in raw_attachments:
        if not isinstance(raw, dict):
            continue
        name = raw.get("name") or raw.get("filename") or raw.get("title")
        if not isinstance(name, str) or not name.strip():
            continue
        attachments.append(
            MediaAttachment(
                name=name.strip(),
                path=raw.get("path") if isinstance(raw.get("path"), str) else None,
                url=raw.get("url") if isinstance(raw.get("url"), str) else None,
                mime_type=raw.get("mime_type") or raw.get("mimeType"),
                attachment_type=raw.get("attachment_type") or raw.get("type"),
                size_bytes=raw.get("size_bytes") or raw.get("size"),
            )
        )
    return attachments


@router.get("/{item_guid}/attachments", response_model=list[MediaAttachment])
async def get_media_attachments(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get attachments for a media item."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return _parse_attachments(_load_extra_data(media_item))


@router.put("/{item_guid}/attachments", response_model=list[MediaAttachment])
async def replace_media_attachments(
    db: DatabaseSession,
    current_user: CurrentSuperuser,
    item_guid: uuid.UUID,
    body: MediaAttachmentsUpdate,
):
    """Replace attachments for a media item."""
    media_item = await db.get(MediaItem, item_guid)
    if not media_item:
        raise HTTPException(status_code=404, detail="Media item not found")

    extra_data = dict(_load_extra_data(media_item))
    extra_data["attachments"] = [
        attachment.model_dump(exclude_none=True) for attachment in body.attachments
    ]
    media_item.extra_data = extra_data
    await db.commit()
    await db.refresh(media_item)

    return _parse_attachments(_load_extra_data(media_item))
