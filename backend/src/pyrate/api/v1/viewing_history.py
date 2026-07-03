"""
Viewing History API Endpoints

Provides endpoints for tracking and managing user viewing progress across media items.
"""

import json
import logging
import uuid
from datetime import UTC, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select

from pyrate.api.dependencies import CurrentUser, DatabaseSession
from pyrate.models.device import Device
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.viewing_history import ViewingHistory
from pyrate.schemas.media import MediaItemRead
from pyrate.schemas.viewing_history import (
    ContinueWatchingItem,
    PaginatedViewingHistoryResponse,
    RecentlyWatchedItem,
    UserViewingStats,
    ViewingHistoryCreate,
    ViewingHistoryRead,
    ViewingHistoryWithContent,
)
from pyrate.services.viewing_history import (
    ViewingHistoryService,
    _extract_episode_hierarchy,
)

logger = logging.getLogger(__name__)

router = APIRouter()


class NextUpItem(BaseModel):
    show_guid: uuid.UUID
    show_title: str
    season_number: int | None = None
    episode_number: int | None = None
    action: str
    progress_seconds: int = 0
    episode: MediaItemRead


class PlaystateReport(BaseModel):
    content_guid: uuid.UUID
    progress_seconds: int = 0
    duration_seconds: int | None = None
    progress_percentage: float | None = None
    is_playing: bool = False
    client_session_id: str | None = None
    event_name: Literal[
        "start",
        "progress",
        "pause",
        "resume",
        "stop",
        "finish",
        "seek",
    ] = "progress"
    device_guid: uuid.UUID | None = None
    media_type: str | None = None
    media_title: str | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    extra_data: str | None = None


class ItemPlaystateReport(BaseModel):
    """Playback event payload for item-scoped viewing-history commands."""

    position_ticks: int | None = None
    position_seconds: int | None = None
    duration_ticks: int | None = None
    duration_seconds: int | None = None
    progress_percentage: float | None = None
    play_session_id: str | None = None
    client_session_id: str | None = None
    device_guid: uuid.UUID | None = None
    device_id: str | None = None
    is_paused: bool = False
    media_type: str | None = None
    media_title: str | None = None
    media_source_id: str | None = None
    audio_stream_index: int | None = None
    subtitle_stream_index: int | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    extra_data: dict | str | None = None


class PlaystateReportResponse(BaseModel):
    history: ViewingHistoryRead
    device_guid: uuid.UUID | None = None
    client_session_id: str | None = None
    is_playing: bool
    event_name: str = "progress"
    is_paused: bool = False


class PlaystateSessionRead(BaseModel):
    session_id: str
    user_guid: uuid.UUID
    content_guid: uuid.UUID
    media_title: str | None = None
    media_type: str | None = None
    playlist_guid: uuid.UUID | None = None
    playlist_index: int | None = None
    device_guid: uuid.UUID | None = None
    progress_seconds: int = 0
    duration_seconds: int | None = None
    progress_percentage: float | None = None
    is_playing: bool = False
    is_paused: bool = False
    event_name: str
    reported_at: datetime | None = None


class PlaystateSessionsResponse(BaseModel):
    items: list[PlaystateSessionRead]
    total: int


def _load_extra_data(raw_extra_data: str | None) -> dict:
    if not raw_extra_data:
        return {}
    try:
        parsed = json.loads(raw_extra_data)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _ticks_to_seconds(ticks: int | None) -> int | None:
    if ticks is None:
        return None
    return max(0, int(ticks / 10_000_000))


def _item_playstate_extra_data(data: ItemPlaystateReport) -> str | None:
    if isinstance(data.extra_data, dict):
        extra_data = dict(data.extra_data)
    else:
        extra_data = _load_extra_data(data.extra_data)

    extra_data["route_source"] = "item_playstate_route"
    for key, value in {
        "play_session_id": data.play_session_id,
        "device_id": data.device_id,
        "media_source_id": data.media_source_id,
        "audio_stream_index": data.audio_stream_index,
        "subtitle_stream_index": data.subtitle_stream_index,
    }.items():
        if value is not None:
            extra_data[key] = value

    session_id = data.client_session_id or data.play_session_id
    if session_id:
        extra_data["client_session_id"] = session_id

    return json.dumps(extra_data, sort_keys=True) if extra_data else None


async def _resolve_item_playstate_device_guid(
    db: DatabaseSession,
    current_user: CurrentUser,
    data: ItemPlaystateReport,
) -> uuid.UUID | None:
    if data.device_guid:
        return data.device_guid
    if not data.device_id:
        return None

    result = await db.execute(
        select(Device).where(
            Device.user_id == current_user.guid,
            Device.device_id == data.device_id,
        )
    )
    device = result.scalar_one_or_none()
    if not device:
        raise HTTPException(status_code=404, detail="Device not found")
    return device.guid


def _item_playstate_report(
    content_guid: uuid.UUID,
    data: ItemPlaystateReport,
    event_name: Literal["start", "progress", "pause", "stop"],
    device_guid: uuid.UUID | None,
) -> PlaystateReport:
    progress_seconds = data.position_seconds
    if progress_seconds is None:
        progress_seconds = _ticks_to_seconds(data.position_ticks) or 0

    duration_seconds = data.duration_seconds
    if duration_seconds is None:
        duration_seconds = _ticks_to_seconds(data.duration_ticks)

    progress_percentage = data.progress_percentage
    if progress_percentage is None and duration_seconds and duration_seconds > 0:
        progress_percentage = min(100.0, (progress_seconds / duration_seconds) * 100)

    normalized_event_name = "pause" if event_name == "progress" and data.is_paused else event_name

    return PlaystateReport(
        content_guid=content_guid,
        progress_seconds=progress_seconds,
        duration_seconds=duration_seconds,
        progress_percentage=progress_percentage,
        is_playing=normalized_event_name not in {"pause", "stop"},
        client_session_id=data.client_session_id or data.play_session_id,
        event_name=normalized_event_name,
        device_guid=device_guid,
        media_type=data.media_type,
        media_title=data.media_title,
        playlist_guid=data.playlist_guid,
        playlist_index=data.playlist_index,
        extra_data=_item_playstate_extra_data(data),
    )


def _playlist_context(extra_data: dict) -> tuple[uuid.UUID | None, int | None]:
    raw_playlist_guid = extra_data.get("playlist_guid") or extra_data.get("playlist_id")
    playlist_guid = None
    if raw_playlist_guid:
        try:
            playlist_guid = uuid.UUID(str(raw_playlist_guid))
        except ValueError:
            playlist_guid = None

    raw_index = extra_data.get("playlist_index")
    playlist_index = None
    if raw_index is not None:
        try:
            playlist_index = int(raw_index)
        except (TypeError, ValueError):
            playlist_index = None
    return playlist_guid, playlist_index


def _merge_playstate_extra_data(
    existing: ViewingHistory | None,
    data: PlaystateReport,
    event_time: datetime,
) -> str:
    extra_data = _load_extra_data(existing.extra_data if existing else None)
    incoming = _load_extra_data(data.extra_data)
    extra_data.update(incoming)
    if data.playlist_guid:
        extra_data["playlist_guid"] = str(data.playlist_guid)
    if data.playlist_index is not None:
        extra_data["playlist_index"] = data.playlist_index
    playstate = extra_data.get("playstate")
    if not isinstance(playstate, dict):
        playstate = {}
    event = {
        "event_name": data.event_name,
        "progress_seconds": data.progress_seconds,
        "duration_seconds": data.duration_seconds,
        "progress_percentage": data.progress_percentage,
        "is_playing": data.is_playing,
        "device_guid": str(data.device_guid) if data.device_guid else None,
        "playlist_guid": str(data.playlist_guid)
        if data.playlist_guid
        else extra_data.get("playlist_guid"),
        "playlist_index": data.playlist_index
        if data.playlist_index is not None
        else extra_data.get("playlist_index"),
        "client_session_id": data.client_session_id
        or incoming.get("client_session_id")
        or extra_data.get("client_session_id"),
        "reported_at": event_time.isoformat(),
    }
    events = playstate.get("events")
    if not isinstance(events, list):
        events = []
    events.append(event)
    playstate["last_event"] = event
    playstate["events"] = events[-20:]
    extra_data["playstate"] = playstate
    return json.dumps(extra_data, sort_keys=True)


def _history_to_read(item, data: ViewingHistoryCreate) -> ViewingHistoryRead:
    """Convert a ViewingHistory model to ViewingHistoryRead schema."""
    playlist_guid, playlist_index = _playlist_context(_load_extra_data(item.extra_data))
    return ViewingHistoryRead(
        guid=item.guid,
        user_guid=item.user_guid,
        content_type=data.content_type,
        movie_guid=data.movie_guid,
        episode_guid=data.episode_guid,
        song_guid=data.song_guid,
        playlist_guid=playlist_guid,
        playlist_index=playlist_index,
        progress_seconds=item.progress_seconds,
        duration_seconds=item.duration_seconds,
        progress_percentage=item.progress_percentage,
        is_completed=item.is_completed,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_watched_at=item.last_watched_at,
    )


def _media_item_read_shallow(item: MediaItem) -> MediaItemRead:
    return MediaItemRead(
        guid=item.guid,
        title=item.title,
        original_title=item.original_title,
        description=item.description,
        tagline=item.tagline,
        release_date=item.release_date,
        poster_path=item.poster_path,
        backdrop_path=item.backdrop_path,
        content_rating=item.content_rating,
        min_age=item.min_age,
        extra_data=item.extra_data,
        media_type=item.media_type,
        parent_guid=item.parent_guid,
        sequence_number=item.sequence_number,
        availability_status=item.availability_status,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_searched_at=item.last_searched_at,
        last_metadata_updated_at=item.last_metadata_updated_at,
    )


def _history_to_content(item) -> ViewingHistoryWithContent:
    """Convert a ViewingHistory model to ViewingHistoryWithContent schema."""
    hierarchy = _extract_episode_hierarchy(item.media_item)
    media_item_data = MediaItemRead.model_validate(item.media_item) if item.media_item else None
    playlist_guid, playlist_index = _playlist_context(_load_extra_data(item.extra_data))

    return ViewingHistoryWithContent(
        guid=item.guid,
        user_guid=item.user_guid,
        content_type=hierarchy["content_type"],
        movie_guid=hierarchy["movie_guid"],
        episode_guid=hierarchy["episode_guid"],
        playlist_guid=playlist_guid,
        playlist_index=playlist_index,
        progress_seconds=item.progress_seconds,
        duration_seconds=item.duration_seconds,
        progress_percentage=item.progress_percentage,
        is_completed=item.is_completed,
        created_at=item.created_at,
        updated_at=item.updated_at,
        last_watched_at=item.last_watched_at,
        media_item=media_item_data,
        show_title=hierarchy["show_title"],
        season_number=hierarchy["season_number"],
        episode_number=hierarchy["episode_number"],
    )


def _history_to_continue_watching(item) -> ContinueWatchingItem:
    """Convert a ViewingHistory model to ContinueWatchingItem schema."""
    hierarchy = _extract_episode_hierarchy(item.media_item)
    media_item_data = MediaItemRead.model_validate(item.media_item) if item.media_item else None
    playlist_guid, playlist_index = _playlist_context(_load_extra_data(item.extra_data))

    return ContinueWatchingItem(
        guid=item.guid,
        content_type=hierarchy["content_type"],
        movie_guid=hierarchy["movie_guid"],
        episode_guid=hierarchy["episode_guid"],
        playlist_guid=playlist_guid,
        playlist_index=playlist_index,
        progress_seconds=item.progress_seconds,
        duration_seconds=item.duration_seconds,
        progress_percentage=item.progress_percentage,
        last_watched_at=item.last_watched_at,
        media_item=media_item_data,
        show_title=hierarchy["show_title"],
        season_number=hierarchy["season_number"],
        episode_number=hierarchy["episode_number"],
    )


def _history_to_recently_watched(item) -> RecentlyWatchedItem:
    """Convert a ViewingHistory model to RecentlyWatchedItem schema."""
    hierarchy = _extract_episode_hierarchy(item.media_item)
    media_item_data = MediaItemRead.model_validate(item.media_item) if item.media_item else None
    playlist_guid, playlist_index = _playlist_context(_load_extra_data(item.extra_data))

    return RecentlyWatchedItem(
        guid=item.guid,
        content_type=hierarchy["content_type"],
        movie_guid=hierarchy["movie_guid"],
        episode_guid=hierarchy["episode_guid"],
        playlist_guid=playlist_guid,
        playlist_index=playlist_index,
        progress_seconds=item.progress_seconds,
        duration_seconds=item.duration_seconds,
        progress_percentage=item.progress_percentage,
        is_completed=item.is_completed,
        last_watched_at=item.last_watched_at,
        media_item=media_item_data,
        show_title=hierarchy["show_title"],
        season_number=hierarchy["season_number"],
        episode_number=hierarchy["episode_number"],
    )


async def _history_to_playstate_session(
    db: DatabaseSession,
    item: ViewingHistory,
) -> PlaystateSessionRead | None:
    extra_data = _load_extra_data(item.extra_data)
    playstate = extra_data.get("playstate")
    if not isinstance(playstate, dict):
        return None
    last_event = playstate.get("last_event")
    if not isinstance(last_event, dict):
        return None

    media_item = await db.get(MediaItem, item.media_item_guid) if item.media_item_guid else None

    event_name = str(last_event.get("event_name") or "progress")
    raw_device_guid = last_event.get("device_guid")
    device_guid = None
    if raw_device_guid:
        try:
            device_guid = uuid.UUID(str(raw_device_guid))
        except ValueError:
            device_guid = None

    raw_reported_at = last_event.get("reported_at")
    reported_at = None
    if raw_reported_at:
        try:
            reported_at = datetime.fromisoformat(str(raw_reported_at))
        except ValueError:
            reported_at = None

    session_id = (
        last_event.get("client_session_id")
        or extra_data.get("client_session_id")
        or (str(device_guid) if device_guid else None)
        or str(item.guid)
    )
    playlist_guid, playlist_index = _playlist_context(extra_data)
    if last_event.get("playlist_guid"):
        try:
            playlist_guid = uuid.UUID(str(last_event["playlist_guid"]))
        except ValueError:
            pass
    if last_event.get("playlist_index") is not None:
        try:
            playlist_index = int(last_event["playlist_index"])
        except (TypeError, ValueError):
            pass
    is_playing = bool(last_event.get("is_playing")) and event_name not in {
        "pause",
        "stop",
        "finish",
    }
    return PlaystateSessionRead(
        session_id=str(session_id),
        user_guid=item.user_guid,
        content_guid=item.media_item_guid,
        media_title=media_item.title if media_item else None,
        media_type=media_item.media_type.value if media_item else None,
        playlist_guid=playlist_guid,
        playlist_index=playlist_index,
        device_guid=device_guid,
        progress_seconds=int(last_event.get("progress_seconds") or item.progress_seconds or 0),
        duration_seconds=last_event.get("duration_seconds") or item.duration_seconds,
        progress_percentage=last_event.get("progress_percentage")
        if last_event.get("progress_percentage") is not None
        else item.progress_percentage,
        is_playing=is_playing,
        is_paused=event_name == "pause",
        event_name=event_name,
        reported_at=reported_at,
    )


async def _get_show_next_up_item(
    db: DatabaseSession,
    current_user: CurrentUser,
    show: MediaItem,
) -> NextUpItem | None:
    seasons_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.parent_guid == show.guid)
        .order_by(MediaItem.sequence_number.asc(), MediaItem.created_at.asc())
    )
    seasons = list(seasons_result.scalars().all())
    if not seasons:
        return None

    episodes_result = await db.execute(
        select(MediaItem)
        .where(MediaItem.parent_guid.in_([season.guid for season in seasons]))
    )
    episodes = list(episodes_result.scalars().all())
    if not episodes:
        return None

    season_number_by_guid = {
        season.guid: season.sequence_number for season in seasons
    }
    ordered_episodes = sorted(
        episodes,
        key=lambda episode: (
            season_number_by_guid.get(episode.parent_guid) or 0,
            episode.sequence_number or 0,
            episode.created_at,
        ),
    )
    episode_guids = [episode.guid for episode in ordered_episodes]
    history_result = await db.execute(
        select(ViewingHistory)
        .where(
            ViewingHistory.user_guid == current_user.guid,
            ViewingHistory.media_item_guid.in_(episode_guids),
        )
        .order_by(ViewingHistory.last_watched_at.desc())
    )
    history_items = list(history_result.scalars().all())
    episode_index_by_guid = {
        episode.guid: index for index, episode in enumerate(ordered_episodes)
    }

    for history in history_items:
        if not history.is_completed and history.progress_percentage > 5:
            index = episode_index_by_guid.get(history.media_item_guid)
            if index is None:
                continue
            episode = ordered_episodes[index]
            return NextUpItem(
                show_guid=show.guid,
                show_title=show.title,
                season_number=season_number_by_guid.get(episode.parent_guid),
                episode_number=episode.sequence_number,
                action="resume",
                progress_seconds=history.progress_seconds,
                episode=_media_item_read_shallow(episode),
            )

    completed_history_items = sorted(
        (history for history in history_items if history.is_completed),
        key=lambda history: episode_index_by_guid.get(history.media_item_guid, -1),
        reverse=True,
    )
    for history in completed_history_items:
        index = episode_index_by_guid.get(history.media_item_guid)
        if index is None:
            continue
        next_index = index + 1
        if next_index < len(ordered_episodes):
            episode = ordered_episodes[next_index]
            action = "next"
        else:
            episode = ordered_episodes[0]
            action = "replay"
        return NextUpItem(
            show_guid=show.guid,
            show_title=show.title,
            season_number=season_number_by_guid.get(episode.parent_guid),
            episode_number=episode.sequence_number,
            action=action,
            progress_seconds=0,
            episode=_media_item_read_shallow(episode),
        )

    episode = ordered_episodes[0]
    return NextUpItem(
        show_guid=show.guid,
        show_title=show.title,
        season_number=season_number_by_guid.get(episode.parent_guid),
        episode_number=episode.sequence_number,
        action="start",
        progress_seconds=0,
        episode=_media_item_read_shallow(episode),
    )


@router.get("", response_model=PaginatedViewingHistoryResponse)
async def list_viewing_history(
    db: DatabaseSession,
    current_user: CurrentUser,
    content_type: str | None = Query(None, description="Filter by content type"),
    content_guid: uuid.UUID | None = Query(None, description="Filter by content GUID"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
):
    """List viewing history for the current user."""
    service = ViewingHistoryService(db)
    result = await service.get_paginated(
        user_guid=current_user.guid,
        content_guid=content_guid,
        page=page,
        per_page=per_page,
    )

    return PaginatedViewingHistoryResponse(
        items=[_history_to_content(item) for item in result["items"]],
        total=result["total"],
        page=result["page"],
        per_page=result["per_page"],
        total_pages=result["total_pages"],
    )


@router.post("", response_model=ViewingHistoryRead)
async def create_or_update_viewing_history(
    db: DatabaseSession,
    current_user: CurrentUser,
    data: ViewingHistoryCreate,
):
    """Create or update viewing history for a media item."""
    media_item_guid = data.content_guid or data.movie_guid or data.episode_guid or data.song_guid

    if not media_item_guid:
        raise HTTPException(
            status_code=400,
            detail="A content GUID must be provided (content_guid, movie_guid, episode_guid, or song_guid)",
        )

    service = ViewingHistoryService(db)
    try:
        item = await service.create_or_update(
            user_guid=current_user.guid,
            media_item_guid=media_item_guid,
            progress_seconds=data.progress_seconds,
            duration_seconds=data.duration_seconds,
            progress_percentage=data.progress_percentage,
            extra_data=data.extra_data,
        )
    except ValueError as e:
        if str(e) == "media_item_not_found":
            raise HTTPException(status_code=404, detail="Media item not found")
        raise

    return _history_to_read(item, data)


async def _record_playstate(
    db: DatabaseSession,
    current_user: CurrentUser,
    data: PlaystateReport,
) -> PlaystateReportResponse:
    device = None
    media_item = None
    if data.device_guid:
        device = await db.get(Device, data.device_guid)
        if not device or device.user_id != current_user.guid:
            raise HTTPException(status_code=404, detail="Device not found")
        media_item = await db.get(MediaItem, data.content_guid)

    now = datetime.now(UTC)
    existing_result = await db.execute(
        select(ViewingHistory).where(
            ViewingHistory.user_guid == current_user.guid,
            ViewingHistory.media_item_guid == data.content_guid,
        )
    )
    existing_history = existing_result.scalar_one_or_none()
    extra_data = _merge_playstate_extra_data(existing_history, data, now)
    progress_percentage = data.progress_percentage
    is_playing = data.is_playing
    if data.event_name in {"pause", "stop", "finish"}:
        is_playing = False
    if data.event_name == "finish":
        progress_percentage = 100.0

    service = ViewingHistoryService(db)
    try:
        item = await service.create_or_update(
            user_guid=current_user.guid,
            media_item_guid=data.content_guid,
            progress_seconds=data.progress_seconds,
            duration_seconds=data.duration_seconds,
            progress_percentage=progress_percentage,
            extra_data=extra_data,
        )
    except ValueError as e:
        if str(e) == "media_item_not_found":
            raise HTTPException(status_code=404, detail="Media item not found")
        raise

    updated_device_guid = None
    if device:
        device.is_playing = is_playing
        device.current_media_guid = data.content_guid
        device.current_media_type = data.media_type or (
            media_item.media_type.value.lower() if media_item else None
        )
        device.current_media_title = data.media_title or (
            media_item.title if media_item else None
        )
        device.current_playback_position = data.progress_seconds
        device.current_playback_duration = data.duration_seconds or 0
        device.playback_updated_at = now
        device.last_activity = now
        device.updated_at = now
        await db.commit()
        await db.refresh(device)
        updated_device_guid = device.guid

    history_data = ViewingHistoryCreate(
        content_type=data.media_type or "media",
        content_guid=data.content_guid,
        progress_seconds=data.progress_seconds,
        duration_seconds=data.duration_seconds,
        progress_percentage=progress_percentage,
        extra_data=extra_data,
    )
    return PlaystateReportResponse(
        history=_history_to_read(item, history_data),
        device_guid=updated_device_guid,
        client_session_id=data.client_session_id
        or _load_extra_data(data.extra_data).get("client_session_id"),
        is_playing=is_playing,
        event_name=data.event_name,
        is_paused=data.event_name == "pause",
    )


@router.post("/playstate", response_model=PlaystateReportResponse)
async def report_playstate(
    db: DatabaseSession,
    current_user: CurrentUser,
    data: PlaystateReport,
):
    """Report cross-client playback state over HTTP."""
    return await _record_playstate(db, current_user, data)


@router.post("/{content_guid}/playing", response_model=PlaystateReportResponse)
async def report_item_playing(
    content_guid: uuid.UUID,
    data: ItemPlaystateReport,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Report a playback start event for an item."""
    device_guid = await _resolve_item_playstate_device_guid(db, current_user, data)
    report = _item_playstate_report(content_guid, data, "start", device_guid)
    return await _record_playstate(db, current_user, report)


@router.post("/{content_guid}/progress", response_model=PlaystateReportResponse)
async def report_item_progress(
    content_guid: uuid.UUID,
    data: ItemPlaystateReport,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Report a playback progress or pause event for an item."""
    device_guid = await _resolve_item_playstate_device_guid(db, current_user, data)
    report = _item_playstate_report(content_guid, data, "progress", device_guid)
    return await _record_playstate(db, current_user, report)


@router.post("/{content_guid}/stopped", response_model=PlaystateReportResponse)
async def report_item_stopped(
    content_guid: uuid.UUID,
    data: ItemPlaystateReport,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Report a playback stop event for an item."""
    device_guid = await _resolve_item_playstate_device_guid(db, current_user, data)
    report = _item_playstate_report(content_guid, data, "stop", device_guid)
    return await _record_playstate(db, current_user, report)


@router.get("/playstate/sessions", response_model=PlaystateSessionsResponse)
async def list_playstate_sessions(
    db: DatabaseSession,
    current_user: CurrentUser,
    active_only: bool = Query(False),
    limit: int = Query(50, ge=1, le=200),
):
    """Return latest reported playback sessions for the current user."""
    result = await db.execute(
        select(ViewingHistory)
        .where(ViewingHistory.user_guid == current_user.guid)
        .order_by(ViewingHistory.updated_at.desc())
        .limit(limit * 2)
    )
    sessions: dict[str, PlaystateSessionRead] = {}
    for history in result.scalars().all():
        session = await _history_to_playstate_session(db, history)
        if session is None:
            continue
        if active_only and not (session.is_playing or session.is_paused):
            continue
        sessions.setdefault(session.session_id, session)
        if len(sessions) >= limit:
            break

    items = list(sessions.values())
    return PlaystateSessionsResponse(items=items, total=len(items))


@router.delete("/{history_guid}", status_code=204)
async def delete_viewing_history(
    db: DatabaseSession,
    current_user: CurrentUser,
    history_guid: uuid.UUID,
):
    """Delete a viewing history record."""
    service = ViewingHistoryService(db)
    try:
        await service.delete(user_guid=current_user.guid, history_guid=history_guid)
        logger.debug("User %s deleted viewing history %s", current_user.guid, history_guid)
    except ValueError as e:
        if str(e) == "not_found":
            raise HTTPException(status_code=404, detail="Viewing history not found")
        raise


@router.get("/continue-watching", response_model=list[ContinueWatchingItem])
async def get_continue_watching(
    db: DatabaseSession,
    current_user: CurrentUser,
    content_type: str | None = Query(
        None, description="Filter by content type (movie, episode)"
    ),
    limit: int = Query(10, ge=1, le=50, description="Number of items to return"),
):
    """Get continue watching list for the current user."""
    service = ViewingHistoryService(db)
    items = await service.get_continue_watching(
        user_guid=current_user.guid,
        content_type=content_type,
        limit=limit,
    )
    return [_history_to_continue_watching(item) for item in items]


@router.get("/next-up", response_model=list[NextUpItem])
async def get_next_up(
    db: DatabaseSession,
    current_user: CurrentUser,
    show_guid: uuid.UUID | None = Query(None, description="Optional show GUID"),
    limit: int = Query(20, ge=1, le=100, description="Maximum shows to return"),
    include_unwatched: bool = Query(True),
):
    """Return one next actionable episode per show."""
    query = select(MediaItem).where(
        MediaItem.media_type == MediaType.SHOWS,
        MediaItem.parent_guid.is_(None),
    )
    if show_guid:
        query = query.where(MediaItem.guid == show_guid)
    query = query.order_by(MediaItem.title.asc()).limit(limit)

    result = await db.execute(query)
    shows = list(result.scalars().all())
    next_up_items: list[NextUpItem] = []
    for show in shows:
        item = await _get_show_next_up_item(db, current_user, show)
        if not item:
            continue
        if not include_unwatched and item.action == "start":
            continue
        next_up_items.append(item)

    if show_guid and not shows:
        raise HTTPException(status_code=404, detail="Show not found")
    return next_up_items


@router.get("/recently-watched", response_model=list[RecentlyWatchedItem])
async def get_recently_watched(
    db: DatabaseSession,
    current_user: CurrentUser,
    limit: int = Query(10, ge=1, le=50, description="Number of items to return"),
):
    """Get recently watched list for the current user."""
    service = ViewingHistoryService(db)
    items = await service.get_recently_watched(
        user_guid=current_user.guid,
        limit=limit,
    )
    return [_history_to_recently_watched(item) for item in items]


@router.get("/stats", response_model=UserViewingStats)
async def get_viewing_stats(
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """Get viewing statistics for the current user."""
    service = ViewingHistoryService(db)
    stats = await service.get_stats(user_guid=current_user.guid)
    return UserViewingStats(**stats)
