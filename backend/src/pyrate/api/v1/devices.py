from pyrate.utils.extra_data import load_extra_data
"""Device API Endpoints for managing user devices"""

import json
import logging
import math
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ...auth.dependencies import get_current_superuser, get_current_user
from ...database import get_db_session
from ...models.device import Device
from ...models.media import MediaFile, MediaItem
from ...models.user import User
from ...schemas.activity_log import ActivityLogCreate, ActivityLogRead
from ...schemas.device import (
    DeviceActiveSessionRead,
    DeviceActiveSessionsResponse,
    DeviceAdminListResponse,
    DeviceCapabilitiesResponse,
    DeviceCapabilitiesUpdate,
    DeviceCommandCreate,
    DeviceCommandHistoryResponse,
    DeviceCommandResponse,
    DeviceListResponse,
    DeviceNowPlayingRead,
    DeviceOfflineItemRead,
    DeviceOfflineItemsResponse,
    DeviceOfflineItemUpdate,
    DeviceOfflineManifestItem,
    DeviceOfflineManifestResponse,
    DeviceOfflineManifestSubtitle,
    DeviceOfflineSyncRequest,
    DeviceRead,
    DeviceReadWithUser,
    DeviceSessionContractResponse,
    DeviceSessionMessageCreate,
    DeviceSessionPlayCommandCreate,
    DeviceSessionPlayMediaCreate,
    DeviceSessionPlayQueueCreate,
    DeviceSessionQueueState,
    DeviceSessionUserAdd,
    DeviceSessionUserRead,
    DeviceSessionUsersResponse,
    DeviceUpdate,
)
from ...services.activity_log import ActivityLogService
from ...services.device import DeviceService
from ...services.media_access import require_media_offline_access
from ...services.permission import PermissionService
from ...services.websocket import RemoteControlError, get_websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/me", response_model=DeviceListResponse)
async def get_my_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all devices for the current user"""
    service = DeviceService(session)
    skip = (page - 1) * page_size

    devices = await service.get_by_user(current_user.guid, skip=skip, limit=page_size)
    total = await service.count_by_user(current_user.guid)

    # Enrich devices with WebSocket connection status
    manager = get_websocket_manager()
    connected_ids = manager.get_connected_device_ids_for_user(str(current_user.guid))

    items = [service.enrich_device_read(d, connected_ids) for d in devices]

    return DeviceListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/me/{device_guid}", response_model=DeviceRead)
async def get_my_device(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get a specific device for the current user"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device or device.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    return DeviceRead.model_validate(device)


@router.put("/me/{device_guid}", response_model=DeviceRead)
async def update_my_device(
    device_guid: UUID,
    update_data: DeviceUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a device (e.g., set a custom name)"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device or device.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    # Regular users cannot set is_trusted
    updated = await service.update_device(
        device_guid,
        name=update_data.name,
    )
    logger.info("User %s updated device %s", current_user.guid, device_guid)

    return DeviceRead.model_validate(updated)


@router.delete("/me/{device_guid}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_my_device(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Remove a device from the user's account"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device or device.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    await service.deactivate_device(device_guid)
    logger.info("User %s deleted device %s", current_user.guid, device_guid)


def _device_capabilities_payload(device) -> DeviceCapabilitiesResponse:
    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    capabilities = device_info.get("capabilities")
    if not isinstance(capabilities, dict):
        capabilities = {}
    return DeviceCapabilitiesResponse(
        device_guid=device.guid,
        device_id=device.device_id,
        **capabilities,
    )


@router.get("/me/{device_guid}/capabilities", response_model=DeviceCapabilitiesResponse)
async def get_my_device_capabilities(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Get client capabilities registered for one of the current user's devices."""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)
    if not device or device.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return _device_capabilities_payload(device)


@router.put("/me/{device_guid}/capabilities", response_model=DeviceCapabilitiesResponse)
async def update_my_device_capabilities(
    device_guid: UUID,
    capabilities: DeviceCapabilitiesUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Register client capabilities for one of the current user's devices."""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)
    if not device or device.user_id != current_user.guid:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    device_info["capabilities"] = capabilities.model_dump()
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)

    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="session.capabilities",
            message=f"Updated capabilities for device {device.device_id}",
            entity_type="device",
            entity_guid=device.guid,
            extra_data=json.dumps(
                {
                    "device_id": device.device_id,
                    "supported_commands": capabilities.supported_commands,
                    "supports_play_queue": capabilities.supports_play_queue,
                    "app_name": capabilities.app_name,
                    "app_version": capabilities.app_version,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=current_user.guid,
    )

    return _device_capabilities_payload(device)


def _can_control_device(user: User, device) -> bool:
    return user.is_superuser or device.user_id == user.guid


def _get_session_user_ids(device) -> list[str]:
    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    raw_ids = device_info.get("session_user_ids", [])
    if not isinstance(raw_ids, list):
        return []
    return [str(user_id) for user_id in raw_ids if user_id]


def _get_offline_items(device) -> list[dict]:
    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    raw_items = device_info.get("offline_items", [])
    if not isinstance(raw_items, list):
        return []
    return [item for item in raw_items if isinstance(item, dict)]


def _media_extra_data(media_item: MediaItem) -> dict:
    return load_extra_data(media_item)


def _offline_manifest_subtitles(
    media_guid: UUID,
    media_item: MediaItem,
) -> list[DeviceOfflineManifestSubtitle]:
    raw_subtitles = (
        _media_extra_data(media_item).get("subtitles")
        or _media_extra_data(media_item).get("subtitle_tracks")
        or []
    )
    if not isinstance(raw_subtitles, list):
        return []

    subtitles: list[DeviceOfflineManifestSubtitle] = []
    for raw in raw_subtitles:
        if not isinstance(raw, dict):
            continue
        subtitle_id = str(raw.get("id") or raw.get("guid") or "")
        language = raw.get("language") or raw.get("lang")
        if not subtitle_id or not isinstance(language, str) or not language.strip():
            continue
        path = raw.get("path") if isinstance(raw.get("path"), str) else None
        url = raw.get("url") if isinstance(raw.get("url"), str) else None
        subtitles.append(
            DeviceOfflineManifestSubtitle(
                id=subtitle_id,
                language=language.strip(),
                title=raw.get("title") if isinstance(raw.get("title"), str) else None,
                format=raw.get("format") if isinstance(raw.get("format"), str) else None,
                url=url,
                content_url=(
                    f"/api/media/{media_guid}/subtitles/{subtitle_id}/content"
                    if (path and path.startswith("uploaded:")) or url
                    else None
                ),
                is_forced=bool(raw.get("is_forced") or raw.get("forced")),
                is_default=bool(raw.get("is_default") or raw.get("default")),
            )
        )
    return subtitles


async def _get_controllable_device(
    service: DeviceService,
    device_guid: UUID,
    current_user: User,
):
    device = await service.get_by_id(device_guid)
    if not device or not _can_control_device(current_user, device):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return device


async def _get_device_permission_context(
    session: AsyncSession,
    current_user: User,
    device,
) -> tuple[User, object]:
    permission_user = current_user
    if device.user_id != current_user.guid:
        permission_user = await session.get(User, device.user_id)
        if not permission_user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Device owner not found",
            )
    permissions = await PermissionService(session).resolve_user_permissions(
        permission_user.guid
    )
    return permission_user, permissions


def _session_user_read(user: User) -> DeviceSessionUserRead:
    name = f"{user.first_name} {user.last_name}".strip() or user.email
    return DeviceSessionUserRead(guid=user.guid, email=user.email, name=name)


async def _offline_item_read(
    session: AsyncSession,
    item: dict,
) -> DeviceOfflineItemRead | None:
    try:
        offline_item = DeviceOfflineItemRead(**item)
    except Exception:
        return None
    media_item = await session.get(MediaItem, offline_item.media_guid)
    if media_item:
        offline_item.media_title = media_item.title
        offline_item.media_type = media_item.media_type.value
    return offline_item


def _user_display_name(user: User | None) -> str | None:
    if not user:
        return None
    return f"{user.first_name} {user.last_name}".strip() or user.email


async def _offline_items_response(
    session: AsyncSession,
    device,
) -> DeviceOfflineItemsResponse:
    items: list[DeviceOfflineItemRead] = []
    for raw_item in _get_offline_items(device):
        item = await _offline_item_read(session, raw_item)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return DeviceOfflineItemsResponse(items=items, total=len(items))


async def _offline_manifest_item(
    session: AsyncSession,
    raw_item: dict,
) -> DeviceOfflineManifestItem | None:
    offline_item = await _offline_item_read(session, raw_item)
    if offline_item is None or offline_item.status in {"removed", "failed"}:
        return None

    media_item = await session.get(MediaItem, offline_item.media_guid)
    if not media_item:
        return None

    media_file = None
    if offline_item.file_guid is not None:
        media_file = await session.get(MediaFile, offline_item.file_guid)
        if media_file and media_file.media_item_guid != media_item.guid:
            media_file = None
    if media_file is None:
        media_file = await session.scalar(
            select(MediaFile)
            .where(MediaFile.media_item_guid == media_item.guid)
            .order_by(MediaFile.file_size.desc().nullslast(), MediaFile.created_at.asc())
        )

    download_url = None
    if media_file:
        download_url = (
            f"/api/media/{media_item.guid}/files/{media_file.guid}/download"
        )

    return DeviceOfflineManifestItem(
        media_guid=media_item.guid,
        media_title=media_item.title,
        media_type=media_item.media_type.value,
        status=offline_item.status,
        file_guid=media_file.guid if media_file else None,
        file_name=media_file.file_name if media_file else None,
        file_size=media_file.file_size if media_file else None,
        duration=media_file.duration
        if media_file and media_file.duration is not None
        else media_item.duration,
        download_url=download_url,
        subtitles=_offline_manifest_subtitles(media_item.guid, media_item),
        expires_at=offline_item.expires_at,
        updated_at=offline_item.updated_at,
    )


async def _offline_manifest_response(
    session: AsyncSession,
    device,
) -> DeviceOfflineManifestResponse:
    items: list[DeviceOfflineManifestItem] = []
    for raw_item in _get_offline_items(device):
        item = await _offline_manifest_item(session, raw_item)
        if item is not None:
            items.append(item)
    items.sort(key=lambda item: item.updated_at, reverse=True)
    return DeviceOfflineManifestResponse(
        device_guid=device.guid,
        device_id=device.device_id,
        items=items,
        total=len(items),
    )


async def _count_user_active_offline_items(session: AsyncSession, user_guid: UUID) -> int:
    result = await session.execute(select(Device).where(Device.user_id == user_guid))
    seen: set[str] = set()
    for device in result.scalars():
        for item in _get_offline_items(device):
            status_value = item.get("status")
            media_guid = item.get("media_guid")
            if status_value not in {"removed", "failed"} and media_guid:
                seen.add(str(media_guid))
    return len(seen)


async def _active_session_read(
    session: AsyncSession,
    item: dict,
) -> DeviceActiveSessionRead | None:
    try:
        user_guid = UUID(str(item["user_id"]))
    except (KeyError, TypeError, ValueError):
        return None

    device_id = str(item.get("device_id") or "")
    if not device_id:
        return None

    user = await session.get(User, user_guid)
    device = await session.scalar(
        select(Device)
        .where(Device.user_id == user_guid)
        .where(Device.device_id == device_id)
    )
    is_playing = device.is_playing if device else False
    position = device.current_playback_position if device else 0
    duration = device.current_playback_duration if device else 0
    playback_state = (
        "playing"
        if is_playing
        else "paused"
        if device and device.current_media_guid
        else "idle"
    )
    progress_percentage = (
        round(max(0, min(position, duration)) / duration * 100, 2)
        if duration
        else None
    )

    return DeviceActiveSessionRead(
        user_id=user_guid,
        user_email=user.email if user else None,
        user_name=_user_display_name(user),
        device_guid=device.guid if device else None,
        device_id=device_id,
        device_name=device.name if device else None,
        browser=device.browser if device else None,
        platform=device.platform if device else None,
        connection_count=item.get("connection_count", 0),
        subscription_count=item.get("subscription_count", 0),
        connected_at=item["connected_at"],
        last_seen_at=item["last_seen_at"],
        playback_state=playback_state,
        is_playing=is_playing,
        current_media_type=device.current_media_type if device else None,
        current_media_guid=device.current_media_guid if device else None,
        current_media_title=device.current_media_title if device else None,
        current_playback_position=position,
        current_playback_duration=duration,
        progress_percentage=progress_percentage,
    )


async def _active_sessions_response(
    session: AsyncSession,
    *,
    user_id: UUID | None = None,
) -> DeviceActiveSessionsResponse:
    manager = get_websocket_manager()
    raw_sessions = manager.get_active_device_sessions(
        str(user_id) if user_id else None,
    )
    items = []
    for raw_session in raw_sessions:
        active_session = await _active_session_read(session, raw_session)
        if active_session is not None:
            items.append(active_session)
    return DeviceActiveSessionsResponse(items=items, total=len(items))


def _playback_state_for_device(device: Device) -> str:
    if device.is_playing:
        return "playing"
    if device.current_media_guid:
        return "paused"
    return "idle"


def _progress_percentage(position: int, duration: int) -> float | None:
    if not duration:
        return None
    return round(max(0, min(position, duration)) / duration * 100, 2)


def _now_playing_for_device(device: Device) -> DeviceNowPlayingRead | None:
    if (
        not device.current_media_guid
        and not device.current_media_title
        and not device.is_playing
        and not device.current_playback_position
        and not device.current_playback_duration
    ):
        return None
    position = device.current_playback_position or 0
    duration = device.current_playback_duration or 0
    return DeviceNowPlayingRead(
        media_guid=device.current_media_guid,
        media_type=device.current_media_type,
        media_title=device.current_media_title,
        position_seconds=position,
        duration_seconds=duration,
        is_playing=device.is_playing,
        playback_state=_playback_state_for_device(device),
        progress_percentage=_progress_percentage(position, duration),
        updated_at=device.playback_updated_at,
    )


def _queue_state_for_device(device: Device) -> DeviceSessionQueueState:
    device_info = device.device_info if isinstance(device.device_info, dict) else {}
    raw_queue = device_info.get("queue_state") or device_info.get("current_queue") or {}
    if not isinstance(raw_queue, dict):
        return DeviceSessionQueueState()
    items = raw_queue.get("items")
    if not isinstance(items, list):
        items = []
    start_index = raw_queue.get("start_index")
    current_index = raw_queue.get("current_index")
    return DeviceSessionQueueState(
        items=[item for item in items if isinstance(item, dict)],
        start_index=start_index if isinstance(start_index, int) else 0,
        current_index=current_index if isinstance(current_index, int) else None,
        repeat_mode=raw_queue.get("repeat_mode")
        if isinstance(raw_queue.get("repeat_mode"), str)
        else None,
        shuffle=raw_queue.get("shuffle")
        if isinstance(raw_queue.get("shuffle"), bool)
        else None,
        updated_at=device.updated_at,
    )


async def _active_session_for_device(
    session: AsyncSession,
    *,
    user_guid: UUID,
    device_id: str,
) -> DeviceActiveSessionRead | None:
    manager = get_websocket_manager()
    for raw_session in manager.get_active_device_sessions(str(user_guid)):
        if raw_session.get("device_id") != device_id:
            continue
        return await _active_session_read(session, raw_session)
    return None


async def _device_session_contract_response(
    session: AsyncSession,
    *,
    device: Device,
) -> DeviceSessionContractResponse:
    service = DeviceService(session)
    entries, _ = await ActivityLogService(session).list(
        skip=0,
        limit=10,
        event_type="session.command",
        entity_type="device",
        entity_guid=device.guid,
    )
    manager = get_websocket_manager()
    connected_ids = manager.get_connected_device_ids_for_user(str(device.user_id))

    return DeviceSessionContractResponse(
        device=service.enrich_device_read(device, connected_ids),
        active_session=await _active_session_for_device(
            session,
            user_guid=device.user_id,
            device_id=device.device_id,
        ),
        capabilities=_device_capabilities_payload(device),
        now_playing=_now_playing_for_device(device),
        queue_state=_queue_state_for_device(device),
        recent_commands=[ActivityLogRead.model_validate(entry) for entry in entries],
    )


async def _log_device_command(
    session: AsyncSession,
    *,
    actor: User,
    device_guid: UUID,
    device_id: str,
    command: str,
    payload: dict,
    status_value: str,
    message: str,
):
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type="session.command",
            severity="info" if status_value == "sent" else "warning",
            message=message,
            entity_type="device",
            entity_guid=device_guid,
            extra_data=json.dumps(
                {
                    "device_id": device_id,
                    "command": command,
                    "payload": payload,
                    "status": status_value,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=actor.guid,
    )


async def _log_session_user_change(
    session: AsyncSession,
    *,
    actor: User,
    device,
    target_user: User,
    action: str,
):
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type=f"session.user_{action}",
            message=f"{'Added' if action == 'add' else 'Removed'} session user {target_user.email} on device {device.device_id}",
            entity_type="device",
            entity_guid=device.guid,
            extra_data=json.dumps(
                {
                    "device_id": device.device_id,
                    "target_user_guid": str(target_user.guid),
                    "target_user_email": target_user.email,
                    "action": action,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=actor.guid,
    )


async def _log_offline_item_change(
    session: AsyncSession,
    *,
    actor: User,
    device,
    media_guid: UUID,
    action: str,
    status_value: str,
):
    await ActivityLogService(session).create(
        ActivityLogCreate(
            event_type=f"offline.{action}",
            message=f"Updated offline item {media_guid} on device {device.device_id}",
            entity_type="device",
            entity_guid=device.guid,
            extra_data=json.dumps(
                {
                    "device_id": device.device_id,
                    "media_guid": str(media_guid),
                    "status": status_value,
                    "action": action,
                },
                sort_keys=True,
            ),
        ),
        actor_guid=actor.guid,
    )


@router.get("/{device_guid}/offline-items", response_model=DeviceOfflineItemsResponse)
async def list_device_offline_items(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List offline sync state for a device."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    return await _offline_items_response(session, device)


@router.post("/{device_guid}/offline-items", response_model=DeviceOfflineItemsResponse)
async def upsert_device_offline_item(
    device_guid: UUID,
    body: DeviceOfflineItemUpdate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Create or update offline sync state for a media item on a device."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    media_item = await session.get(MediaItem, body.media_guid)
    if not media_item:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Media item not found",
        )
    permission_user, permissions = await _get_device_permission_context(
        session,
        current_user,
        device,
    )
    require_media_offline_access(permission_user, permissions, media_item)

    from datetime import UTC, datetime

    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    items = [
        item
        for item in _get_offline_items(device)
        if str(item.get("media_guid")) != str(body.media_guid)
    ]
    item_data = body.model_dump(mode="json", exclude_none=True)
    item_data["updated_at"] = datetime.now(UTC).isoformat()
    items.append(item_data)
    device_info["offline_items"] = items
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)
    await _log_offline_item_change(
        session,
        actor=current_user,
        device=device,
        media_guid=body.media_guid,
        action="item_update",
        status_value=body.status,
    )
    return await _offline_items_response(session, device)


@router.post(
    "/{device_guid}/offline-items/sync-request",
    response_model=DeviceOfflineItemsResponse,
)
async def request_device_offline_sync(
    device_guid: UUID,
    body: DeviceOfflineSyncRequest,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Queue media items for offline availability on a device."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    permission_user, permissions = await _get_device_permission_context(
        session,
        current_user,
        device,
    )
    permission_user_guid = permission_user.guid

    media_items: list[MediaItem] = []
    requested_media_guids: list[UUID] = []
    seen_requested_media_guids: set[str] = set()
    for media_guid in body.media_guids:
        media_guid_key = str(media_guid)
        if media_guid_key in seen_requested_media_guids:
            continue
        seen_requested_media_guids.add(media_guid_key)
        requested_media_guids.append(media_guid)
        media_item = await session.get(MediaItem, media_guid)
        if not media_item:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Media item {media_guid} not found",
            )
        require_media_offline_access(permission_user, permissions, media_item)
        media_items.append(media_item)

    existing_items = _get_offline_items(device)
    existing_active = {
        str(item.get("media_guid"))
        for item in existing_items
        if item.get("status") not in {"removed", "failed"} and item.get("media_guid")
    }
    requested_new = {
        str(media_item.guid)
        for media_item in media_items
        if str(media_item.guid) not in existing_active
    }
    offline_limit = permissions.offline_download_limit
    if offline_limit is not None:
        active_count = await _count_user_active_offline_items(session, permission_user_guid)
        if active_count + len(requested_new) > offline_limit:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Offline download limit exceeded",
            )

    from datetime import UTC, datetime

    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    requested_media_guid_keys = {str(media_guid) for media_guid in requested_media_guids}
    retained_items = [
        item
        for item in existing_items
        if str(item.get("media_guid")) not in requested_media_guid_keys
    ]
    now = datetime.now(UTC).isoformat()
    for media_item in media_items:
        item_data = {
            "media_guid": str(media_item.guid),
            "status": body.status,
            "progress": 0,
            "updated_at": now,
        }
        if body.expires_at is not None:
            item_data["expires_at"] = body.expires_at.isoformat()
        retained_items.append(item_data)

    device_info["offline_items"] = retained_items
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)

    for media_item in media_items:
        await _log_offline_item_change(
            session,
            actor=current_user,
            device=device,
            media_guid=media_item.guid,
            action="sync_request",
            status_value=body.status,
        )
    return await _offline_items_response(session, device)


@router.get(
    "/{device_guid}/offline-items/manifest",
    response_model=DeviceOfflineManifestResponse,
)
async def get_device_offline_manifest(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return concrete media/subtitle URLs for a device offline queue."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    return await _offline_manifest_response(session, device)


@router.delete(
    "/{device_guid}/offline-items/{media_guid}",
    response_model=DeviceOfflineItemsResponse,
)
async def remove_device_offline_item(
    device_guid: UUID,
    media_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Remove offline sync state for a media item on a device."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    device_info["offline_items"] = [
        item
        for item in _get_offline_items(device)
        if str(item.get("media_guid")) != str(media_guid)
    ]
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)
    await _log_offline_item_change(
        session,
        actor=current_user,
        device=device,
        media_guid=media_guid,
        action="item_remove",
        status_value="removed",
    )
    return await _offline_items_response(session, device)


@router.get("/{device_guid}/session-users", response_model=DeviceSessionUsersResponse)
async def list_device_session_users(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List users explicitly attached to a device session."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    users = []
    for user_id in _get_session_user_ids(device):
        try:
            user_guid = UUID(user_id)
        except ValueError:
            continue
        user = await session.get(User, user_guid)
        if user and user.is_active:
            users.append(_session_user_read(user))
    return DeviceSessionUsersResponse(items=users, total=len(users))


@router.post("/{device_guid}/session-users", response_model=DeviceSessionUsersResponse)
async def add_device_session_user(
    device_guid: UUID,
    body: DeviceSessionUserAdd,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Attach a user to a device session."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    target_user = await session.get(User, body.user_guid)
    if not target_user or not target_user.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    session_user_ids = _get_session_user_ids(device)
    target_id = str(target_user.guid)
    if target_id not in session_user_ids:
        session_user_ids.append(target_id)
    device_info["session_user_ids"] = session_user_ids
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)
    await _log_session_user_change(
        session,
        actor=current_user,
        device=device,
        target_user=target_user,
        action="add",
    )
    return await list_device_session_users(device_guid, current_user, session)


@router.delete(
    "/{device_guid}/session-users/{user_guid}",
    response_model=DeviceSessionUsersResponse,
)
async def remove_device_session_user(
    device_guid: UUID,
    user_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Detach a user from a device session."""
    service = DeviceService(session)
    device = await _get_controllable_device(service, device_guid, current_user)
    target_user = await session.get(User, user_guid)
    if not target_user:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="User not found",
        )

    device_info = dict(device.device_info) if isinstance(device.device_info, dict) else {}
    device_info["session_user_ids"] = [
        value for value in _get_session_user_ids(device) if value != str(user_guid)
    ]
    device.device_info = device_info
    await session.commit()
    await session.refresh(device)
    await _log_session_user_change(
        session,
        actor=current_user,
        device=device,
        target_user=target_user,
        action="remove",
    )
    return await list_device_session_users(device_guid, current_user, session)


@router.post("/{device_guid}/commands", response_model=DeviceCommandResponse)
async def send_device_command(
    device_guid: UUID,
    command_data: DeviceCommandCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Send a remote-control command to a connected device."""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device or not _can_control_device(current_user, device):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    if not device.is_active:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Device is inactive",
        )

    manager = get_websocket_manager()
    try:
        result = await manager.send_remote_control_command(
            user_id=str(device.user_id),
            target_device_id=device.device_id,
            command=command_data.command,
            payload=command_data.payload,
            from_device_id=command_data.from_device_id,
            actor_user_id=str(current_user.guid),
        )
    except RemoteControlError as e:
        message = str(e)
        await _log_device_command(
            session,
            actor=current_user,
            device_guid=device.guid,
            device_id=device.device_id,
            command=command_data.command,
            payload=command_data.payload,
            status_value="failed",
            message=f"Remote command {command_data.command} failed for {device.device_id}: {message}",
        )
        if "Rate limit" in message:
            error_status = status.HTTP_429_TOO_MANY_REQUESTS
        elif "not connected" in message:
            error_status = status.HTTP_409_CONFLICT
        else:
            error_status = status.HTTP_422_UNPROCESSABLE_CONTENT
        raise HTTPException(status_code=error_status, detail=message) from e

    await _log_device_command(
        session,
        actor=current_user,
        device_guid=device.guid,
        device_id=device.device_id,
        command=command_data.command,
        payload=command_data.payload,
        status_value="sent",
        message=f"Remote command {command_data.command} sent to {device.device_id}",
    )

    return DeviceCommandResponse(**result)


@router.get(
    "/sessions/active/me",
    response_model=DeviceActiveSessionsResponse,
)
async def list_my_active_device_sessions(
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """List live client sessions for the current user."""
    return await _active_sessions_response(session, user_id=current_user.guid)


@router.get(
    "/sessions/active",
    response_model=DeviceActiveSessionsResponse,
)
async def list_active_device_sessions(
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """List all live client sessions."""
    return await _active_sessions_response(session)


@router.post("/by-id/{device_id}/commands", response_model=DeviceCommandResponse)
async def send_device_command_by_device_id(
    device_id: str,
    command_data: DeviceCommandCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Send a remote-control command by stable client device_id."""
    service = DeviceService(session)
    device = await service.get_by_device_id(current_user.guid, device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )
    return await send_device_command(
        device.guid,
        command_data,
        current_user,
        session,
    )


@router.get(
    "/by-id/{device_id}/session",
    response_model=DeviceSessionContractResponse,
)
async def get_device_session_contract(
    device_id: str,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the native session contract for one of the current user's devices."""
    service = DeviceService(session)
    device = await service.get_by_device_id(current_user.guid, device_id)
    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    return await _device_session_contract_response(
        session,
        device=device,
    )


@router.get(
    "/{device_guid}/session",
    response_model=DeviceSessionContractResponse,
)
async def get_device_session_contract_by_guid(
    device_guid: UUID,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return the native session contract for a controllable device."""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)
    if not device or not _can_control_device(current_user, device):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    return await _device_session_contract_response(
        session,
        device=device,
    )


@router.post("/by-id/{device_id}/message", response_model=DeviceCommandResponse)
async def send_device_session_message(
    device_id: str,
    body: DeviceSessionMessageCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Send a display message to one of the current user's active device sessions."""
    payload = {"text": body.text}
    if body.title:
        payload["title"] = body.title
    if body.timeout_seconds is not None:
        payload["timeout_seconds"] = body.timeout_seconds
    return await send_device_command_by_device_id(
        device_id,
        DeviceCommandCreate(
            command="message",
            payload=payload,
            from_device_id=body.from_device_id,
        ),
        current_user,
        session,
    )


@router.post("/by-id/{device_id}/play-media", response_model=DeviceCommandResponse)
async def send_device_session_play_media(
    device_id: str,
    body: DeviceSessionPlayMediaCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Ask one of the current user's active device sessions to play media."""
    payload = {"media_guid": str(body.media_guid)}
    if body.media_type:
        payload["media_type"] = body.media_type
    if body.media_title:
        payload["media_title"] = body.media_title
    if body.file_guid:
        payload["file_guid"] = str(body.file_guid)
    return await send_device_command_by_device_id(
        device_id,
        DeviceCommandCreate(
            command="play_media",
            payload=payload,
            from_device_id=body.from_device_id,
        ),
        current_user,
        session,
    )


@router.post("/by-id/{device_id}/play-queue", response_model=DeviceCommandResponse)
async def send_device_session_play_queue(
    device_id: str,
    body: DeviceSessionPlayQueueCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Ask one of the current user's active device sessions to play a queue."""
    if body.start_index >= len(body.items):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_index is outside the queue",
        )
    payload = {
        "items": [
            item.model_dump(mode="json", exclude_none=True)
            for item in body.items
        ],
        "start_index": body.start_index,
    }
    if body.start_position_seconds is not None:
        payload["start_position_seconds"] = body.start_position_seconds
    return await send_device_command_by_device_id(
        device_id,
        DeviceCommandCreate(
            command="play_queue",
            payload=payload,
            from_device_id=body.from_device_id,
        ),
        current_user,
        session,
    )


@router.post("/by-id/{device_id}/playing", response_model=DeviceCommandResponse)
async def send_device_session_play_command(
    device_id: str,
    body: DeviceSessionPlayCommandCreate,
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Send a play instruction to one of the current user's sessions."""
    if body.start_index is not None and body.start_index >= len(body.item_ids):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="start_index is outside the item list",
        )

    start_position_seconds = body.start_position_seconds
    if start_position_seconds is None and body.start_position_ticks is not None:
        start_position_seconds = body.start_position_ticks // 10_000_000

    payload = {
        "item_ids": [str(item_id) for item_id in body.item_ids],
        "play_command": body.play_command,
    }
    if start_position_seconds is not None:
        payload["start_position_seconds"] = start_position_seconds
    if body.start_position_ticks is not None:
        payload["start_position_ticks"] = body.start_position_ticks
    if body.media_source_id:
        payload["media_source_id"] = body.media_source_id
    if body.audio_stream_index is not None:
        payload["audio_stream_index"] = body.audio_stream_index
    if body.subtitle_stream_index is not None:
        payload["subtitle_stream_index"] = body.subtitle_stream_index
    if body.start_index is not None:
        payload["start_index"] = body.start_index

    return await send_device_command_by_device_id(
        device_id,
        DeviceCommandCreate(
            command="play_command",
            payload=payload,
            from_device_id=body.from_device_id,
        ),
        current_user,
        session,
    )


@router.get("/{device_guid}/commands", response_model=DeviceCommandHistoryResponse)
async def get_device_command_history(
    device_guid: UUID,
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    current_user: User = Depends(get_current_user),
    session: AsyncSession = Depends(get_db_session),
):
    """Return recent remote-control command attempts for a device."""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device or not _can_control_device(current_user, device):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    skip = (page - 1) * per_page
    entries, total = await ActivityLogService(session).list(
        skip=skip,
        limit=per_page,
        event_type="session.command",
        entity_type="device",
        entity_guid=device.guid,
    )
    return DeviceCommandHistoryResponse(
        items=[ActivityLogRead.model_validate(entry) for entry in entries],
        total=total,
        page=page,
        per_page=per_page,
        total_pages=math.ceil(total / per_page) if total > 0 else 1,
    )


# Admin endpoints
@router.get("", response_model=DeviceAdminListResponse)
async def list_all_devices(
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    search: str | None = Query(None),
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """List all devices (admin only)"""
    service = DeviceService(session)
    skip = (page - 1) * page_size

    devices, total = await service.get_all(
        skip=skip,
        limit=page_size,
        search=search,
        include_inactive=include_inactive,
    )

    manager = get_websocket_manager()
    connected_ids = manager.get_all_connected_device_ids()

    items = [
        service.enrich_device_read_with_user(device, connected_ids)
        for device in devices
    ]

    return DeviceAdminListResponse(
        items=items,
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{device_guid}", response_model=DeviceReadWithUser)
async def get_device(
    device_guid: UUID,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Get a specific device (admin only)"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    return service.enrich_device_read_with_user(device, set())


@router.put("/{device_guid}", response_model=DeviceReadWithUser)
async def admin_update_device(
    device_guid: UUID,
    update_data: DeviceUpdate,
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Update a device (admin only - can set is_trusted)"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    updated = await service.update_device(
        device_guid,
        name=update_data.name,
        is_trusted=update_data.is_trusted,
    )
    logger.info("Admin %s updated device %s", current_user.guid, device_guid)

    return service.enrich_device_read_with_user(updated, set())


@router.delete("/{device_guid}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_delete_device(
    device_guid: UUID,
    permanent: bool = Query(False),
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Delete a device (admin only)"""
    service = DeviceService(session)
    device = await service.get_by_id(device_guid)

    if not device:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Device not found",
        )

    if permanent:
        await service.delete_device(device_guid)
    else:
        await service.deactivate_device(device_guid)
    logger.info("Admin %s deleted device %s (permanent=%s)", current_user.guid, device_guid, permanent)


@router.get("/user/{user_guid}", response_model=DeviceListResponse)
async def get_user_devices(
    user_guid: UUID,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    include_inactive: bool = Query(False),
    current_user: User = Depends(get_current_superuser),
    session: AsyncSession = Depends(get_db_session),
):
    """Get all devices for a specific user (admin only)"""
    # 404 when the user doesn't exist instead of returning an empty list — an
    # admin asking for a non-existent user wants a clear signal, not silence.
    target_user = await session.get(User, user_guid)
    if target_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="User not found"
        )

    service = DeviceService(session)
    skip = (page - 1) * page_size

    devices = await service.get_by_user(
        user_guid,
        skip=skip,
        limit=page_size,
        include_inactive=include_inactive,
    )
    total = await service.count_by_user(user_guid, active_only=not include_inactive)

    return DeviceListResponse(
        items=[DeviceRead.model_validate(d) for d in devices],
        total=total,
        page=page,
        page_size=page_size,
    )
