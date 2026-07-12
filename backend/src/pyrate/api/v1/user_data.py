"""Per-item user data endpoints."""

import uuid
from datetime import datetime

from fastapi import APIRouter
from pydantic import BaseModel, Field
from sqlalchemy import select

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.media import MediaItem
from pyrate.models.viewing_history import ViewingHistory
from pyrate.services.favorite import MEDIA_TYPE_TO_ITEM_TYPE
from pyrate.services.list import ListService
from pyrate.services.media_access import (
    get_visible_media_item as _get_visible_media_item,
)
from pyrate.services.viewing_history import (
    ViewingHistoryService,
    get_playback_preferences as _get_playback_preferences,
)

router = APIRouter()

# Maps update-body field names to the persisted playback-preference keys.
_PLAYBACK_PREFERENCE_FIELD_MAP = {
    "selected_audio_track_index": "audio_track_index",
    "selected_subtitle_track_index": "subtitle_track_index",
    "selected_subtitle_track_id": "subtitle_track_id",
    "selected_audio_language": "audio_language",
    "selected_subtitle_language": "subtitle_language",
}


class MediaUserData(BaseModel):
    media_item_guid: uuid.UUID
    is_favorite: bool = False
    is_liked: bool = False
    is_played: bool = False
    playback_position_seconds: int = 0
    duration_seconds: int | None = None
    progress_percentage: float = 0.0
    last_played_at: datetime | None = None
    selected_audio_track_index: int | None = None
    selected_subtitle_track_index: int | None = None
    selected_subtitle_track_id: str | None = None
    selected_audio_language: str | None = None
    selected_subtitle_language: str | None = None
    liked_at: datetime | None = None


class MediaUserDataUpdate(BaseModel):
    is_favorite: bool | None = None
    is_liked: bool | None = None
    is_played: bool | None = None
    playback_position_seconds: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)
    progress_percentage: float | None = Field(default=None, ge=0, le=100)
    selected_audio_track_index: int | None = Field(default=None, ge=0)
    selected_subtitle_track_index: int | None = Field(default=None, ge=0)
    selected_subtitle_track_id: str | None = Field(default=None, max_length=255)
    selected_audio_language: str | None = Field(default=None, max_length=16)
    selected_subtitle_language: str | None = Field(default=None, max_length=16)


async def _get_history(
    db: DatabaseSession,
    user_guid: uuid.UUID,
    media_item_guid: uuid.UUID,
) -> ViewingHistory | None:
    result = await db.execute(
        select(ViewingHistory).where(
            ViewingHistory.user_guid == user_guid,
            ViewingHistory.media_item_guid == media_item_guid,
        )
    )
    return result.scalar_one_or_none()


async def _build_user_data(
    db: DatabaseSession,
    current_user: CurrentUser,
    media_item: MediaItem,
) -> MediaUserData:
    list_service = ListService(db)
    history = await _get_history(db, current_user.guid, media_item.guid)
    is_favorite = await list_service.is_in_favorites(current_user.guid, media_item.guid)
    like_item = await list_service.get_like_item(current_user.guid, media_item.guid)
    playback_preferences = _get_playback_preferences(history)
    return MediaUserData(
        media_item_guid=media_item.guid,
        is_favorite=is_favorite,
        is_liked=like_item is not None,
        is_played=bool(history.is_completed) if history else False,
        playback_position_seconds=history.progress_seconds if history else 0,
        duration_seconds=history.duration_seconds if history else None,
        progress_percentage=history.progress_percentage if history else 0.0,
        last_played_at=history.last_watched_at if history else None,
        selected_audio_track_index=playback_preferences.get("audio_track_index"),
        selected_subtitle_track_index=playback_preferences.get("subtitle_track_index"),
        selected_subtitle_track_id=playback_preferences.get("subtitle_track_id"),
        selected_audio_language=playback_preferences.get("audio_language"),
        selected_subtitle_language=playback_preferences.get("subtitle_language"),
        liked_at=like_item.created_at if like_item else None,
    )


async def _apply_media_user_data_update(
    db: DatabaseSession,
    current_user: CurrentUser,
    media_item: MediaItem,
    body: MediaUserDataUpdate,
) -> MediaUserData:
    list_service = ListService(db)

    if body.is_favorite is not None:
        current_favorite = await list_service.is_in_favorites(
            current_user.guid, media_item.guid
        )
        if current_favorite != body.is_favorite:
            media_type = media_item.media_type.value
            await list_service.toggle_favorite(
                current_user.guid,
                media_item.guid,
                MEDIA_TYPE_TO_ITEM_TYPE.get(media_type, "MOVIE"),
            )

    if body.is_liked is not None:
        await list_service.set_liked(
            user_guid=current_user.guid,
            media_item=media_item,
            liked=body.is_liked,
        )

    should_update_history = any(
        value is not None
        for value in (
            body.is_played,
            body.playback_position_seconds,
            body.duration_seconds,
            body.progress_percentage,
        )
    )
    if should_update_history:
        progress_seconds = body.playback_position_seconds
        if progress_seconds is None:
            existing = await _get_history(db, current_user.guid, media_item.guid)
            progress_seconds = existing.progress_seconds if existing else 0

        progress_percentage = body.progress_percentage
        if body.is_played is True:
            progress_percentage = 100.0
        elif body.is_played is False and progress_percentage is None:
            progress_percentage = 0.0

        await ViewingHistoryService(db).create_or_update(
            user_guid=current_user.guid,
            media_item_guid=media_item.guid,
            progress_seconds=progress_seconds,
            duration_seconds=body.duration_seconds,
            progress_percentage=progress_percentage,
        )

    fields_set = body.model_fields_set
    if _PLAYBACK_PREFERENCE_FIELD_MAP.keys() & fields_set:
        preference_updates = {
            preference_key: getattr(body, body_field)
            for body_field, preference_key in _PLAYBACK_PREFERENCE_FIELD_MAP.items()
            if body_field in fields_set
        }
        history = await _get_history(db, current_user.guid, media_item.guid)
        await ViewingHistoryService(db).update_playback_preferences(
            user_guid=current_user.guid,
            media_item_guid=media_item.guid,
            preference_updates=preference_updates,
            history=history,
        )

    return await _build_user_data(db, current_user, media_item)


@router.get("/{item_guid}/user-data", response_model=MediaUserData)
async def get_media_user_data(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Get the current user's per-item favorite and playstate data."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _build_user_data(db, current_user, media_item)


@router.put("/{item_guid}/user-data", response_model=MediaUserData)
async def update_media_user_data(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
    body: MediaUserDataUpdate,
):
    """Update the current user's per-item favorite and playstate data."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(db, current_user, media_item, body)


@router.post("/{item_guid}/played", response_model=MediaUserData)
async def mark_media_played(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Mark an item played for the current user."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_played=True)
    )


@router.delete("/{item_guid}/played", response_model=MediaUserData)
async def mark_media_unplayed(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Mark an item unplayed for the current user."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_played=False)
    )


@router.post("/{item_guid}/favorite", response_model=MediaUserData)
async def mark_media_favorite(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Add an item to the current user's favorites."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_favorite=True)
    )


@router.delete("/{item_guid}/favorite", response_model=MediaUserData)
async def mark_media_unfavorite(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Remove an item from the current user's favorites."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_favorite=False)
    )


@router.post("/{item_guid}/like", response_model=MediaUserData)
async def mark_media_liked(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Like an item for the current user."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_liked=True)
    )


@router.delete("/{item_guid}/like", response_model=MediaUserData)
async def mark_media_unliked(
    db: DatabaseSession,
    current_user: CurrentUser,
    permissions: UserPermissionsDep,
    item_guid: uuid.UUID,
):
    """Unlike an item for the current user."""
    media_item = await _get_visible_media_item(db, item_guid, current_user, permissions)
    return await _apply_media_user_data_update(
        db, current_user, media_item, MediaUserDataUpdate(is_liked=False)
    )
