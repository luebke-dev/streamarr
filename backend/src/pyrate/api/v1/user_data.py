"""Per-item user data endpoints."""

import json
import uuid
from datetime import datetime

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import delete as sa_delete
from sqlalchemy import select

from pyrate.api.dependencies import CurrentUser, DatabaseSession, UserPermissionsDep
from pyrate.models.list import List, ListItem, ListType
from pyrate.models.media import MediaItem
from pyrate.models.viewing_history import ViewingHistory
from pyrate.services.favorite import MEDIA_TYPE_TO_ITEM_TYPE
from pyrate.services.list import ListService
from pyrate.services.permission import MEDIA_TYPE_TO_LIBRARY
from pyrate.services.viewing_history import ViewingHistoryService
from pyrate.utils.age_rating import is_allowed

router = APIRouter()


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


def _load_history_extra_data(history: ViewingHistory | None) -> dict:
    if not history or not history.extra_data:
        return {}
    try:
        data = json.loads(history.extra_data)
    except (TypeError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _get_playback_preferences(history: ViewingHistory | None) -> dict:
    extra_data = _load_history_extra_data(history)
    raw_preferences = extra_data.get("playback_preferences")
    return raw_preferences if isinstance(raw_preferences, dict) else {}


_LIKED_MEDIA_UPDATE_SOURCE = "user:liked_media"


async def _get_or_create_likes_list(db: DatabaseSession, user_guid: uuid.UUID):
    return await ListService(db).get_or_create_system_list(
        user_guid,
        update_source=_LIKED_MEDIA_UPDATE_SOURCE,
        name="Liked Media",
        description="Media items liked by the user",
    )


async def _get_likes_list(db: DatabaseSession, user_guid: uuid.UUID):
    result = await db.execute(
        select(List).where(
            List.owner_guid == user_guid,
            List.update_source == _LIKED_MEDIA_UPDATE_SOURCE,
            List.list_type == ListType.SYSTEM,
            List.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none()


async def _get_like_item(
    db: DatabaseSession,
    user_guid: uuid.UUID,
    media_item_guid: uuid.UUID,
) -> ListItem | None:
    likes_list = await _get_likes_list(db, user_guid)
    if likes_list is None:
        return None
    result = await db.execute(
        select(ListItem).where(
            ListItem.list_guid == likes_list.guid,
            ListItem.item_guid == media_item_guid,
        )
    )
    return result.scalar_one_or_none()


async def _set_liked(
    db: DatabaseSession,
    *,
    user_guid: uuid.UUID,
    media_item: MediaItem,
    liked: bool,
) -> None:
    existing = await _get_like_item(db, user_guid, media_item.guid)
    if liked and existing is None:
        likes_list = await _get_or_create_likes_list(db, user_guid)
        media_type = media_item.media_type.value
        db.add(
            ListItem(
                list_guid=likes_list.guid,
                item_type=MEDIA_TYPE_TO_ITEM_TYPE.get(media_type, "MOVIE"),
                item_guid=media_item.guid,
                added_by_guid=user_guid,
            )
        )
        likes_list.item_count += 1
        await db.commit()
    elif not liked and existing is not None:
        likes_list = await _get_likes_list(db, user_guid)
        await db.execute(sa_delete(ListItem).where(ListItem.guid == existing.guid))
        if likes_list is not None:
            likes_list.item_count = max(0, likes_list.item_count - 1)
        await db.commit()


async def _update_playback_preferences(
    db: DatabaseSession,
    *,
    user_guid: uuid.UUID,
    media_item_guid: uuid.UUID,
    history: ViewingHistory | None,
    body: MediaUserDataUpdate,
) -> ViewingHistory:
    if history is None:
        history = ViewingHistory(
            user_guid=user_guid,
            media_item_guid=media_item_guid,
            progress_seconds=0,
            duration_seconds=None,
            progress_percentage=0.0,
            is_completed=False,
        )
        db.add(history)

    extra_data = _load_history_extra_data(history)
    preferences = _get_playback_preferences(history)
    field_map = {
        "selected_audio_track_index": "audio_track_index",
        "selected_subtitle_track_index": "subtitle_track_index",
        "selected_subtitle_track_id": "subtitle_track_id",
        "selected_audio_language": "audio_language",
        "selected_subtitle_language": "subtitle_language",
    }

    fields_set = body.model_fields_set
    for body_field, preference_key in field_map.items():
        if body_field not in fields_set:
            continue
        value = getattr(body, body_field)
        if value is None:
            preferences.pop(preference_key, None)
        else:
            preferences[preference_key] = value

    if preferences:
        extra_data["playback_preferences"] = preferences
    else:
        extra_data.pop("playback_preferences", None)

    history.extra_data = json.dumps(extra_data) if extra_data else None
    await db.commit()
    await db.refresh(history)
    return history


async def _build_user_data(
    db: DatabaseSession,
    current_user: CurrentUser,
    media_item: MediaItem,
) -> MediaUserData:
    history = await _get_history(db, current_user.guid, media_item.guid)
    is_favorite = await ListService(db).is_in_favorites(current_user.guid, media_item.guid)
    like_item = await _get_like_item(db, current_user.guid, media_item.guid)
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
        await _set_liked(
            db,
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

    preference_fields = {
        "selected_audio_track_index",
        "selected_subtitle_track_index",
        "selected_subtitle_track_id",
        "selected_audio_language",
        "selected_subtitle_language",
    }
    if preference_fields.intersection(body.model_fields_set):
        history = await _get_history(db, current_user.guid, media_item.guid)
        await _update_playback_preferences(
            db,
            user_guid=current_user.guid,
            media_item_guid=media_item.guid,
            history=history,
            body=body,
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
