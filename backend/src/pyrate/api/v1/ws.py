"""WebSocket API endpoint for real-time updates."""

import logging
import ipaddress
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.database import get_db_session
from pyrate.models.device import Device
from pyrate.models.user import User
from pyrate.services.permission import PermissionService
from pyrate.services.websocket import (
    get_websocket_manager,
    set_device_status_callback,
)

logger = logging.getLogger(__name__)

router = APIRouter(tags=["websocket"])


def _is_remote_websocket(websocket: WebSocket) -> bool:
    if websocket.client is None or not websocket.client.host:
        return False
    host = websocket.client.host
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return host not in {"localhost"}
    return not (address.is_loopback or address.is_private or address.is_link_local)


async def update_device_status(
    user_id: str, device_id: str, status_data: dict[str, Any]
):
    """Update device playback state in the database.

    Called by the WebSocket manager once per ``device_status`` message —
    that's once every few seconds during playback per active device. We
    issue a single ``UPDATE ... WHERE`` instead of SELECT-then-update so
    each ping costs one round-trip instead of two.
    """
    from sqlalchemy import and_, update

    # Resolve media_guid up-front; the WS payload may omit it or send
    # a string we must coerce.
    media_guid_value: UUID | None = None
    raw_media_guid = status_data.get("media_guid")
    if raw_media_guid:
        try:
            media_guid_value = (
                UUID(raw_media_guid)
                if isinstance(raw_media_guid, str)
                else raw_media_guid
            )
        except (ValueError, TypeError):
            media_guid_value = None

    now = datetime.now(UTC)

    async for db in get_db_session():
        try:
            stmt = (
                update(Device)
                .where(
                    and_(
                        Device.user_id == UUID(user_id),
                        Device.device_id == device_id,
                    )
                )
                .values(
                    is_playing=status_data.get("is_playing", False),
                    current_media_type=status_data.get("media_type"),
                    current_media_title=status_data.get("media_title"),
                    current_media_guid=media_guid_value,
                    current_playback_position=status_data.get("position", 0),
                    current_playback_duration=status_data.get("duration", 0),
                    playback_updated_at=now,
                    last_activity=now,
                    updated_at=now,
                )
            )
            result = await db.execute(stmt)
            await db.commit()
            if result.rowcount == 0:
                logger.warning("Device %s not found for user %s", device_id, user_id)
            else:
                logger.debug(
                    "Updated device status for %s: playing=%s",
                    device_id, status_data.get("is_playing", False),
                )
        except Exception as e:
            logger.error("Error updating device status: %s", e)
            await db.rollback()
        break


# Register the callback on module load
set_device_status_callback(update_device_status)


@router.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT access token for authentication"),
    device_id: str | None = Query(None, description="Device ID for status tracking"),
):
    """
    WebSocket endpoint for real-time updates.

    Connect with: ws://host/api/ws?token=<jwt_token>&device_id=<device_uuid>

    After connecting, send JSON messages to subscribe/unsubscribe:

    Subscribe to episode updates:
    {
        "action": "subscribe",
        "resource_type": "episode",
        "resource_id": "<episode_uuid>"
    }

    Unsubscribe:
    {
        "action": "unsubscribe",
        "resource_type": "episode",
        "resource_id": "<episode_uuid>"
    }

    Keep-alive ping:
    {"action": "ping"}

    Device status update (send every few seconds during playback):
    {
        "action": "device_status",
        "device_id": "<device_uuid>",
        "is_playing": true,
        "media_type": "movie" | "episode",
        "media_guid": "<media_uuid>",
        "media_title": "Movie Title",
        "position": 123,
        "duration": 7200
    }

    Events you may receive:
    - connected: Initial connection confirmation
    - subscribed: Subscription confirmation
    - unsubscribed: Unsubscription confirmation
    - releases_updated: New releases found for an episode
    - pong: Response to ping
    - device_status_ack: Acknowledgment of device status update
    - error: Error message
    - heartbeat: Periodic keep-alive from server
    """
    # Validate token
    payload = jwt_handler.verify_token(token)
    if not payload or payload.get("type") != "access":
        await websocket.close(code=4001, reason="Invalid or expired token")
        return

    user_id = payload.get("sub")
    if not user_id:
        await websocket.close(code=4001, reason="Invalid token payload")
        return

    # Verify user exists and is active, and that the claimed device_id
    # (if any) actually belongs to this user. A stranger-supplied device_id
    # would otherwise let them toggle device-presence state for arbitrary
    # devices in ``ws:connected_devices``.
    verified_device_id: str | None = None
    async for db in get_db_session():
        user = await db.get(User, user_id)
        if not user or not user.is_active:
            await websocket.close(code=4003, reason="User not found or inactive")
            return
        if not user.is_superuser:
            permissions = await PermissionService(db).resolve_user_permissions(user.guid)
            if not permissions.access_schedule_active:
                await websocket.close(code=4003, reason="Access is not allowed at this time")
                return
            if _is_remote_websocket(websocket) and not permissions.remote_access_enabled:
                await websocket.close(code=4003, reason="Remote access is not allowed for this user")
                return

        if device_id:
            from sqlalchemy import and_, select

            device_lookup = await db.execute(
                select(Device.device_id).where(
                    and_(
                        Device.user_id == UUID(user_id),
                        Device.device_id == device_id,
                    )
                )
            )
            if device_lookup.scalar_one_or_none() is not None:
                verified_device_id = device_id
            else:
                logger.info(
                    "WebSocket connect: device_id %s does not belong to user %s, "
                    "connecting without device tracking",
                    device_id, user_id,
                )
        break

    manager = get_websocket_manager()
    connection = await manager.connect(websocket, user_id, verified_device_id)

    try:
        while True:
            try:
                # Receive message from client
                data = await websocket.receive_json()
                await manager.handle_message(connection, data)
            except ValueError as e:
                # Invalid JSON
                await connection.send_event(
                    "error",
                    {
                        "message": f"Invalid JSON: {str(e)}",
                    },
                )
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected: %s", user_id)
    except Exception as e:
        logger.error("WebSocket error for %s: %s", user_id, e)
    finally:
        await manager.disconnect(connection)
