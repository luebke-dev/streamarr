"""API endpoints for watch parties."""

import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status

from pyrate.api.dependencies import CurrentSuperuser, CurrentUser, DatabaseSession
from pyrate.api.rate_limit import rate_limit
from pyrate.schemas.party import (
    PlaybackSync,
    WatchPartyAdminResponse,
    WatchPartyCreate,
    WatchPartyJoin,
    WatchPartyListResponse,
    WatchPartyResponse,
    WatchPartyUpdate,
)
from pyrate.services.party import WatchPartyService
from pyrate.services.websocket import get_websocket_manager

logger = logging.getLogger(__name__)

router = APIRouter()

# Throttle join attempts per client so party codes cannot be enumerated by
# unthrottled online guessing.
_join_rate_limit = rate_limit(max_calls=10, window_seconds=60, scope="party-join")


# Centralised mapping so the same ValueError phrase always produces the same
# HTTP status. The service layer still raises ``ValueError`` with a
# human-readable message; the endpoint layer translates.
_PARTY_ERROR_RULES: tuple[tuple[str, int], ...] = (
    # Authorization errors → 403
    ("only the host", status.HTTP_403_FORBIDDEN),
    ("not a member", status.HTTP_403_FORBIDDEN),
    ("not authorized", status.HTTP_403_FORBIDDEN),
    # Resource existence → 404
    ("session not found", status.HTTP_404_NOT_FOUND),
    ("member not found", status.HTTP_404_NOT_FOUND),
)


def _party_value_error_status(exc: ValueError) -> int:
    msg = str(exc).lower()
    for needle, code in _PARTY_ERROR_RULES:
        if needle in msg:
            return code
    return status.HTTP_400_BAD_REQUEST


@router.post("", response_model=WatchPartyResponse, status_code=status.HTTP_201_CREATED)
async def create_watch_party(
    data: WatchPartyCreate,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> WatchPartyResponse:
    """
    Create a new group watch session.

    Creates a session for synchronized viewing with other users.
    The creator becomes the host with full control.
    """
    service = WatchPartyService(db)
    try:
        result = await service.create_session(current_user.guid, data)
        logger.info("User %s created watch party %s", current_user.guid, result.guid)
        return result
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.post(
    "/join",
    response_model=WatchPartyResponse,
    dependencies=[Depends(_join_rate_limit)],
)
async def join_watch_party(
    data: WatchPartyJoin,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> WatchPartyResponse:
    """
    Join an existing group session via code.

    Allows users to join a session by entering the 6-character session code.
    """
    service = WatchPartyService(db)
    try:
        result = await service.join_session(current_user.guid, data.party_code)
        logger.info("User %s joined watch party via code %s", current_user.guid, data.party_code)
        return result
    except ValueError as e:
        raise HTTPException(status_code=_party_value_error_status(e), detail=str(e))


@router.get("", response_model=list[WatchPartyListResponse])
async def get_user_sessions(
    db: DatabaseSession,
    current_user: CurrentUser,
) -> list[WatchPartyListResponse]:
    """
    Get all active group sessions for the current user.

    Returns sessions where the user is currently a member.
    """
    service = WatchPartyService(db)
    return await service.get_user_sessions(current_user.guid)


@router.get("/friends", response_model=list[WatchPartyListResponse])
async def get_friends_watch_parties(
    db: DatabaseSession,
    current_user: CurrentUser,
) -> list[WatchPartyListResponse]:
    """
    Get active watch parties from friends.

    Returns active sessions hosted by friends of the current user.
    """
    service = WatchPartyService(db)
    return await service.get_friends_sessions(current_user.guid)


@router.get("/{session_id}", response_model=WatchPartyResponse)
async def get_watch_party(
    session_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> WatchPartyResponse:
    """
    Get detailed information about a specific session.

    Includes current playback state and member list.
    """
    service = WatchPartyService(db)
    session = await service.get_session(session_id)

    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Session not found"
        )

    # Check if user is the owner or a *connected* member. Kicked/departed
    # members keep their row with is_connected=False and must not retain access.
    is_connected_member = any(
        m.user_id == current_user.guid and m.is_connected for m in session.members
    )
    if session.owner_id != current_user.guid and not is_connected_member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You are not a member of this session",
        )

    return session


@router.post("/{session_id}/sync", response_model=WatchPartyResponse)
async def sync_playback(
    session_id: uuid.UUID,
    sync_data: PlaybackSync,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> WatchPartyResponse:
    """
    Update playback state for a session.

    Synchronizes playback position, play/pause state, and playback rate
    across all session members.

    Only the host (or members if allow_control is enabled) can update playback.
    """
    service = WatchPartyService(db)
    try:
        result = await service.sync_playback(session_id, current_user.guid, sync_data)
        logger.info("User %s synced playback for party %s", current_user.guid, session_id)

        # Broadcast sync to all party members via WebSocket
        try:
            ws_manager = get_websocket_manager()
            await ws_manager.broadcast_to_resource(
                resource_type="party",
                resource_id=str(session_id),
                event="party_sync",
                data={
                    "party_id": str(session_id),
                    "current_time": sync_data.current_time,
                    "is_playing": sync_data.is_playing,
                    "playback_rate": sync_data.playback_rate,
                    "from_user_id": str(current_user.guid),
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )
        except Exception:
            logger.warning("Failed to broadcast sync for party %s", session_id)

        return result
    except ValueError as e:
        raise HTTPException(
            status_code=_party_value_error_status(e),
            detail=str(e),
        )


@router.patch("/{session_id}", response_model=WatchPartyResponse)
async def update_watch_party(
    session_id: uuid.UUID,
    data: WatchPartyUpdate,
    db: DatabaseSession,
    current_user: CurrentUser,
) -> WatchPartyResponse:
    """
    Update watch party settings (host only).

    Can update name, allow_control, media_id, and media_type.
    """
    service = WatchPartyService(db)
    try:
        result = await service.update_session(session_id, current_user.guid, data)

        # Broadcast media change to all party members so they navigate to the new content
        if data.media_id is not None:
            ws_manager = get_websocket_manager()
            if ws_manager:
                await ws_manager.broadcast_to_resource(
                    resource_type="party",
                    resource_id=str(session_id),
                    event="party_media_changed",
                    data={
                        "party_id": str(session_id),
                        "media_id": str(data.media_id),
                        "media_type": data.media_type or result.media_type,
                        "media_title": result.media_title,
                        "from_user_id": str(current_user.guid),
                    },
                )

        return result
    except ValueError as e:
        raise HTTPException(status_code=_party_value_error_status(e), detail=str(e))


@router.post("/{session_id}/heartbeat", status_code=status.HTTP_204_NO_CONTENT)
async def session_heartbeat(
    session_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    Send a heartbeat to indicate the user is still connected.

    Should be called periodically (e.g., every 10-30 seconds) to maintain
    connection status.
    """
    service = WatchPartyService(db)
    await service.heartbeat(session_id, current_user.guid)


@router.delete(
    "/{session_id}/members/{user_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def kick_member(
    session_id: uuid.UUID,
    user_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    Remove a member from the watch party (host only).
    """
    service = WatchPartyService(db)
    try:
        await service.kick_member(session_id, current_user.guid, user_id)
        logger.info("User %s kicked user %s from party %s", current_user.guid, user_id, session_id)
    except ValueError as e:
        raise HTTPException(status_code=_party_value_error_status(e), detail=str(e))

    # Broadcast kick event to all party members via WebSocket
    ws_manager = get_websocket_manager()
    await ws_manager.broadcast_to_resource(
        resource_type="party",
        resource_id=str(session_id),
        event="party_member_kicked",
        data={
            "party_id": str(session_id),
            "kicked_user_id": str(user_id),
        },
    )


@router.delete("/{session_id}/leave", status_code=status.HTTP_204_NO_CONTENT)
async def leave_watch_party(
    session_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    Leave a group session.

    If the host leaves, the session will be ended for all members.
    """
    service = WatchPartyService(db)
    await service.leave_session(current_user.guid, session_id)
    logger.info("User %s left watch party %s", current_user.guid, session_id)


@router.delete("/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def end_watch_party(
    session_id: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,
):
    """
    End a group session (host only).

    Terminates the session and disconnects all members.
    """
    service = WatchPartyService(db)
    try:
        await service.end_session(session_id, host_id=current_user.guid)
        logger.info("User %s ended watch party %s", current_user.guid, session_id)
    except ValueError as e:
        code = _party_value_error_status(e)
        detail = str(e)
        raise HTTPException(status_code=code, detail=detail)


# Admin endpoints


@router.get("/admin/all", response_model=list[WatchPartyAdminResponse])
async def admin_list_watch_parties(
    db: DatabaseSession,
    _: CurrentSuperuser,
) -> list[WatchPartyAdminResponse]:
    """
    List all active watch parties (admin only).
    """
    service = WatchPartyService(db)
    return await service.get_all_active_sessions()


@router.delete("/admin/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def admin_end_watch_party(
    session_id: uuid.UUID,
    db: DatabaseSession,
    _: CurrentSuperuser,
):
    """
    Force-end a watch party (admin only).
    """
    service = WatchPartyService(db)
    try:
        await service.admin_end_session(session_id)
        logger.info("Admin force-ended watch party %s", session_id)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=str(e)
        )
