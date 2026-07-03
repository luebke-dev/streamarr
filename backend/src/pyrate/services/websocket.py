"""WebSocket service for real-time client connections with Redis Pub/Sub."""

import asyncio
import logging
import time
import uuid as _uuid
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from fastapi import WebSocket

from pyrate.services.observability import (
    record_websocket_connection_event,
    record_websocket_message,
    set_websocket_stats,
)
from pyrate.services.redis_event import get_redis_event_service

logger = logging.getLogger(__name__)

# Type for device status update callback
DeviceStatusCallback = Callable[
    [str, str, dict[str, Any]], Any
]  # user_id, device_id, status_data

# Global callback for device status updates (set by ws.py)
_device_status_callback: DeviceStatusCallback | None = None


class RemoteControlError(ValueError):
    """Raised when a remote-control command cannot be accepted or delivered."""


def set_device_status_callback(callback: DeviceStatusCallback | None):
    """Set the callback for device status updates."""
    global _device_status_callback
    _device_status_callback = callback


def get_device_status_callback() -> DeviceStatusCallback | None:
    """Get the current device status callback."""
    return _device_status_callback


class WebSocketConnection:
    """Represents a single WebSocket connection with its subscriptions."""

    def __init__(
        self, websocket: WebSocket, user_id: str, device_id: str | None = None
    ):
        self.websocket = websocket
        self.user_id = user_id
        self.device_id = device_id
        self.subscriptions: set[str] = set()
        self._handlers: dict[str, Any] = {}
        self.connected_at = datetime.now(UTC)
        self.last_seen_at = self.connected_at
        # Stable per-connection id. Previously built from ``id(websocket)``,
        # which CPython can reuse after the websocket is GC'd — two live
        # connections could collide. A fresh uuid makes that impossible.
        self.connection_id: str = f"{user_id}:{_uuid.uuid4().hex}"

    async def send_event(self, event: str, data: dict[str, Any]):
        """Send an event to this WebSocket connection."""
        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }
        try:
            await self.websocket.send_json(message)
        except Exception as e:
            logger.warning("Failed to send to WebSocket %s: %s", self.user_id, e)
            raise

    def mark_seen(self):
        """Mark this connection as recently active."""
        self.last_seen_at = datetime.now(UTC)


class WebSocketManager:
    """
    Manages WebSocket connections and their subscriptions.

    Integrates with Redis Pub/Sub to receive events from any container
    and forward them to connected clients.
    """

    def __init__(self):
        self._connections: dict[str, WebSocketConnection] = {}
        self._lock = asyncio.Lock()
        self._redis_service = get_redis_event_service()
        self._last_sync_persist: dict[str, float] = {}  # party_id → monotonic timestamp

    async def connect(
        self,
        websocket: WebSocket,
        user_id: str,
        device_id: str | None = None,
    ) -> WebSocketConnection:
        """
        Accept a new WebSocket connection.

        Args:
            websocket: The FastAPI WebSocket
            user_id: The authenticated user's ID
            device_id: Optional device ID for status tracking

        Returns:
            The WebSocketConnection object
        """
        await websocket.accept()

        connection = WebSocketConnection(websocket, user_id, device_id)
        connection_id = connection.connection_id

        async with self._lock:
            self._connections[connection_id] = connection
            self._update_metrics_locked()

        # Publish connected device_id to Redis so the Rust backend (or any
        # other process) can see which devices currently have an active
        # WebSocket — used by /api/devices{,/me}.is_ws_connected.
        if device_id:
            try:
                r = await self._redis_service._get_redis()
                await r.sadd("ws:connected_devices", device_id)
                await r.sadd(f"ws:connected_devices:{user_id}", device_id)
            except Exception as e:
                logger.debug("Failed to SADD ws:connected_devices: %s", e)

        logger.info("WebSocket connected: %s", connection_id)
        record_websocket_connection_event("connect")

        # Send welcome message
        await connection.send_event(
            "connected",
            {
                "message": "WebSocket connection established",
                "connection_id": connection_id,
            },
        )

        # Auto-subscribe to user's own channel for personal notifications
        await self.subscribe(connection, "user", str(user_id))

        return connection

    async def disconnect(self, connection: WebSocketConnection):
        """
        Clean up a disconnected WebSocket.

        Args:
            connection: The connection to remove
        """
        connection_id = connection.connection_id

        # Unsubscribe from all channels
        for channel in list(connection.subscriptions):
            await self._unsubscribe_from_channel(connection, channel)

        async with self._lock:
            self._connections.pop(connection_id, None)
            # Check if this user still has other connections for this device
            still_connected = any(
                c.device_id == connection.device_id and c.user_id == connection.user_id
                for c in self._connections.values()
            )
            self._update_metrics_locked()

        # Remove device from the Redis cross-backend set once the last
        # connection for that device on this process closes.
        if connection.device_id and not still_connected:
            try:
                r = await self._redis_service._get_redis()
                await r.srem("ws:connected_devices", connection.device_id)
                await r.srem(
                    f"ws:connected_devices:{connection.user_id}",
                    connection.device_id,
                )
            except Exception as e:
                logger.debug("Failed to SREM ws:connected_devices: %s", e)

        logger.info("WebSocket disconnected: %s", connection_id)
        record_websocket_connection_event("disconnect")

    async def subscribe(
        self,
        connection: WebSocketConnection,
        resource_type: str,
        resource_id: str | UUID,
    ):
        """
        Subscribe a connection to a resource channel.

        Args:
            connection: The WebSocket connection
            resource_type: Type of resource (e.g., "episode")
            resource_id: ID of the resource
        """
        channel = f"{resource_type}:{resource_id}"

        if channel in connection.subscriptions:
            return

        async def handler(message: dict[str, Any]):
            """Handler for Redis messages - forwards to WebSocket."""
            try:
                await connection.send_event(
                    event=message.get("event", "unknown"),
                    data=message.get("data", {}),
                )
            except Exception as e:
                # Connection probably closed, will be cleaned up
                logger.debug("Failed to forward message to WebSocket client: %s", e)

        connection._handlers[channel] = handler
        connection.subscriptions.add(channel)
        self._update_metrics_locked()

        await self._redis_service.subscribe(channel, handler)

        logger.debug("Connection %s subscribed to %s", connection.user_id, channel)

        # Confirm subscription to client
        await connection.send_event(
            "subscribed",
            {
                "channel": channel,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
            },
        )

    async def unsubscribe(
        self,
        connection: WebSocketConnection,
        resource_type: str,
        resource_id: str | UUID,
    ):
        """
        Unsubscribe a connection from a resource channel.

        Args:
            connection: The WebSocket connection
            resource_type: Type of resource (e.g., "episode")
            resource_id: ID of the resource
        """
        channel = f"{resource_type}:{resource_id}"
        await self._unsubscribe_from_channel(connection, channel)

        # Confirm unsubscription to client
        await connection.send_event(
            "unsubscribed",
            {
                "channel": channel,
                "resource_type": resource_type,
                "resource_id": str(resource_id),
            },
        )

    async def _unsubscribe_from_channel(
        self,
        connection: WebSocketConnection,
        channel: str,
    ):
        """Internal method to unsubscribe from a channel."""
        if channel not in connection.subscriptions:
            return

        handler = connection._handlers.pop(channel, None)
        connection.subscriptions.discard(channel)

        if handler:
            await self._redis_service.unsubscribe(channel, handler)

        self._update_metrics_locked()
        logger.debug("Connection %s unsubscribed from %s", connection.user_id, channel)

    async def handle_message(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle an incoming message from a WebSocket client.

        Message format:
        {
            "action": "subscribe" | "unsubscribe" | "ping",
            "resource_type": "episode",  // for subscribe/unsubscribe
            "resource_id": "uuid"         // for subscribe/unsubscribe
        }
        """
        connection.mark_seen()
        action = message.get("action")
        record_websocket_message(str(action or "unknown"))

        if action == "subscribe":
            resource_type = message.get("resource_type")
            resource_id = message.get("resource_id")

            if not resource_type or not resource_id:
                await connection.send_event(
                    "error",
                    {
                        "message": "Missing resource_type or resource_id",
                    },
                )
                return

            # Restrict subscribable resource types to prevent unauthorized access
            allowed_types = {
                "user", "episode", "media", "movie", "show",
                "download", "library", "party", "transcode",
            }
            if resource_type not in allowed_types:
                await connection.send_event(
                    "error",
                    {
                        "message": f"Invalid resource_type: {resource_type}",
                    },
                )
                return

            # Users can only subscribe to their own user channel
            if resource_type == "user" and str(resource_id) != str(connection.user_id):
                await connection.send_event(
                    "error",
                    {
                        "message": "Cannot subscribe to another user's channel",
                    },
                )
                return

            await self.subscribe(connection, resource_type, resource_id)

        elif action == "unsubscribe":
            resource_type = message.get("resource_type")
            resource_id = message.get("resource_id")

            if not resource_type or not resource_id:
                await connection.send_event(
                    "error",
                    {
                        "message": "Missing resource_type or resource_id",
                    },
                )
                return

            await self.unsubscribe(connection, resource_type, resource_id)

        elif action == "ping":
            await connection.send_event(
                "pong",
                {
                    "timestamp": datetime.now(UTC).isoformat(),
                },
            )

        elif action == "device_status":
            # Handle device status updates (playback status, activity, etc.)
            await self._handle_device_status(connection, message)

        elif action == "remote_control":
            # Handle remote control commands (play, pause, seek on other devices)
            await self._handle_remote_control(connection, message)

        elif action == "party_sync":
            # Handle watch party playback synchronization
            await self._handle_party_sync(connection, message)

        elif action == "party_member_update":
            # Handle watch party member status updates (position, heartbeat)
            await self._handle_party_member_update(connection, message)

        elif action == "party_request_sync":
            # Late joiner requests current playback state from host
            await self._handle_party_request_sync(connection, message)

        else:
            await connection.send_event(
                "error",
                {
                    "message": f"Unknown action: {action}",
                },
            )

    async def broadcast_to_resource(
        self,
        resource_type: str,
        resource_id: str | UUID,
        event: str,
        data: dict[str, Any],
    ):
        """
        Broadcast an event to all subscribers of a resource.

        This publishes to Redis, which will then be received by all
        containers and forwarded to their connected clients.

        Args:
            resource_type: Type of resource (e.g., "episode")
            resource_id: ID of the resource
            event: Event name
            data: Event data
        """
        await self._redis_service.publish(
            channel=f"{resource_type}:{resource_id}",
            event=event,
            data=data,
        )

    def get_connected_device_ids_for_user(self, user_id: str) -> set[str]:
        """Return the set of device_ids that are currently WebSocket-connected for a user."""
        return {
            conn.device_id
            for conn in self._connections.values()
            if conn.user_id == user_id and conn.device_id
        }

    def get_all_connected_device_ids(self) -> set[str]:
        """Return the set of all device_ids that currently have an active WebSocket connection."""
        return {conn.device_id for conn in self._connections.values() if conn.device_id}

    def get_online_user_ids(self) -> set[str]:
        """Return the set of user_ids that currently have at least one live WebSocket."""
        return {conn.user_id for conn in self._connections.values() if conn.user_id}

    def get_active_device_sessions(
        self,
        user_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """Return live WebSocket-backed device session summaries."""
        sessions: dict[tuple[str, str], dict[str, Any]] = {}
        for conn in self._connections.values():
            if not conn.user_id or not conn.device_id:
                continue
            if user_id and conn.user_id != user_id:
                continue

            key = (conn.user_id, conn.device_id)
            existing = sessions.setdefault(
                key,
                {
                    "user_id": conn.user_id,
                    "device_id": conn.device_id,
                    "connection_count": 0,
                    "subscription_count": 0,
                    "connected_at": conn.connected_at,
                    "last_seen_at": conn.last_seen_at,
                },
            )
            existing["connection_count"] += 1
            existing["subscription_count"] += len(conn.subscriptions)
            existing["connected_at"] = min(existing["connected_at"], conn.connected_at)
            existing["last_seen_at"] = max(existing["last_seen_at"], conn.last_seen_at)

        return sorted(
            sessions.values(),
            key=lambda item: item["last_seen_at"],
            reverse=True,
        )

    def get_connection_count(self) -> int:
        """Get the number of active connections."""
        return len(self._connections)

    def get_subscription_count(
        self, resource_type: str, resource_id: str | UUID
    ) -> int:
        """Get the number of subscriptions to a specific resource."""
        channel = f"{resource_type}:{resource_id}"
        count = 0
        for conn in self._connections.values():
            if channel in conn.subscriptions:
                count += 1
        return count

    def _update_metrics_locked(self) -> None:
        """Refresh WebSocket gauges. Caller should hold ``_lock`` for mutations."""
        subscriptions_by_type: dict[str, int] = {}
        for connection in self._connections.values():
            for channel in connection.subscriptions:
                resource_type = channel.split(":", 1)[0] if ":" in channel else channel
                subscriptions_by_type[resource_type] = (
                    subscriptions_by_type.get(resource_type, 0) + 1
                )

        set_websocket_stats(
            connections=len(self._connections),
            online_users=len(
                {conn.user_id for conn in self._connections.values() if conn.user_id}
            ),
            connected_devices=len(
                {conn.device_id for conn in self._connections.values() if conn.device_id}
            ),
            subscriptions_by_type=subscriptions_by_type,
        )

    async def _handle_device_status(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle device status updates from clients.

        Message format:
        {
            "action": "device_status",
            "device_id": "uuid",                    // Required: device identifier
            "is_playing": true,                     // Optional: playback state
            "media_type": "movie" | "episode",      // Optional: type of media
            "media_guid": "uuid",                   // Optional: media identifier
            "media_title": "Movie Title",           // Optional: cached title for display
            "position": 123,                        // Optional: playback position in seconds
            "duration": 7200                        // Optional: total duration in seconds
        }
        """
        device_id = message.get("device_id") or connection.device_id

        if not device_id:
            await connection.send_event(
                "error",
                {
                    "message": "Missing device_id in status update",
                },
            )
            return

        # Update connection's device_id if provided
        if not connection.device_id:
            connection.device_id = device_id

        # Extract status data
        status_data = {
            "is_playing": message.get("is_playing", False),
            "media_type": message.get("media_type"),
            "media_guid": message.get("media_guid"),
            "media_title": message.get("media_title"),
            "position": message.get("position", 0),
            "duration": message.get("duration", 0),
        }

        # Call the registered callback to update device in database
        callback = get_device_status_callback()
        if callback:
            try:
                await callback(connection.user_id, device_id, status_data)
            except Exception as e:
                logger.error("Error in device status callback: %s", e)

        # Acknowledge the status update
        await connection.send_event(
            "device_status_ack",
            {
                "device_id": device_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

    # Rate limit: max remote control commands per user per minute
    _RC_MAX_PER_MINUTE = 60
    _rc_counters: dict[str, list[float]] = {}

    def _check_rc_rate_limit(self, user_id: str) -> bool:
        """Return True if within rate limit, False if exceeded."""
        now = datetime.now(UTC).timestamp()
        window = now - 60
        key = str(user_id)
        timestamps = self._rc_counters.get(key, [])
        timestamps = [t for t in timestamps if t > window]
        if len(timestamps) >= self._RC_MAX_PER_MINUTE:
            self._rc_counters[key] = timestamps
            return False
        timestamps.append(now)
        self._rc_counters[key] = timestamps
        return True

    _VALID_RC_COMMANDS = {
        "play", "pause", "resume", "stop", "seek",
        "volume", "mute", "next", "previous",
        "skip_forward", "skip_backward", "play_media", "play_command",
        "message", "browse",
    }
    _VALID_MEDIA_TYPES = {"movie", "episode", "music", "game"}
    _VALID_BROWSE_ROUTES = {"home", "search", "item", "view", "library", "favorites"}
    _VALID_PLAY_COMMANDS = {
        "play_now", "play_next", "play_last", "play_instant_mix", "play_shuffle",
    }

    def _sanitize_remote_control_payload(
        self,
        command: str,
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Validate and normalize a remote-control command payload."""
        payload = payload or {}
        sanitized_payload: dict[str, Any] = {}

        if command in {"play", "play_media"}:
            media_type = payload.get("media_type")
            if media_type and media_type not in self._VALID_MEDIA_TYPES:
                raise RemoteControlError(f"Invalid media_type: {media_type}")
            sanitized_payload["media_type"] = media_type
            sanitized_payload["media_guid"] = payload.get("media_guid")
            sanitized_payload["media_title"] = str(payload.get("media_title", ""))[:200]
            if payload.get("file_guid"):
                sanitized_payload["file_guid"] = payload["file_guid"]

            if command == "play_media" and not sanitized_payload["media_guid"]:
                raise RemoteControlError(
                    "play_media command requires 'media_guid' in payload"
                )
        elif command == "play_command":
            item_ids = payload.get("item_ids")
            if not isinstance(item_ids, list) or not item_ids:
                raise RemoteControlError(
                    "play_command requires non-empty 'item_ids' in payload"
                )
            sanitized_payload["item_ids"] = [
                str(item_id) for item_id in item_ids[:500] if item_id
            ]
            if not sanitized_payload["item_ids"]:
                raise RemoteControlError(
                    "play_command requires non-empty 'item_ids' in payload"
                )
            play_command = payload.get("play_command") or "play_now"
            if play_command not in self._VALID_PLAY_COMMANDS:
                raise RemoteControlError(f"Invalid play_command: {play_command}")
            sanitized_payload["play_command"] = play_command
            start_index = payload.get("start_index")
            if isinstance(start_index, int):
                if start_index < 0 or start_index >= len(sanitized_payload["item_ids"]):
                    raise RemoteControlError("start_index is outside the item list")
                sanitized_payload["start_index"] = start_index
            start_position_seconds = payload.get("start_position_seconds")
            if isinstance(start_position_seconds, (int, float)):
                sanitized_payload["start_position_seconds"] = max(
                    0, int(start_position_seconds)
                )
            start_position_ticks = payload.get("start_position_ticks")
            if isinstance(start_position_ticks, int) and start_position_ticks >= 0:
                sanitized_payload["start_position_ticks"] = start_position_ticks
            media_source_id = payload.get("media_source_id")
            if media_source_id:
                sanitized_payload["media_source_id"] = str(media_source_id)[:255]
            for key in ("audio_stream_index", "subtitle_stream_index"):
                value = payload.get(key)
                if isinstance(value, int) and value >= 0:
                    sanitized_payload[key] = value
        elif command == "seek":
            position = payload.get("position")
            if position is None or not isinstance(position, (int, float)):
                raise RemoteControlError(
                    "Seek command requires numeric 'position' in payload"
                )
            sanitized_payload["position"] = max(position, 0)
        elif command == "volume":
            level = payload.get("level")
            if level is None or not isinstance(level, (int, float)):
                raise RemoteControlError(
                    "Volume command requires numeric 'level' in payload"
                )
            sanitized_payload["level"] = max(0.0, min(float(level), 1.0))
        elif command in {"skip_forward", "skip_backward"}:
            seconds = payload.get("seconds", 10)
            if not isinstance(seconds, (int, float)) or seconds <= 0:
                seconds = 10
            sanitized_payload["seconds"] = seconds
        elif command == "message":
            text = payload.get("text") or payload.get("message")
            if not isinstance(text, str) or not text.strip():
                raise RemoteControlError(
                    "Message command requires non-empty 'text' in payload"
                )
            sanitized_payload["text"] = text.strip()[:500]
            title = payload.get("title")
            if isinstance(title, str) and title.strip():
                sanitized_payload["title"] = title.strip()[:100]
            timeout_seconds = payload.get("timeout_seconds")
            if isinstance(timeout_seconds, (int, float)) and timeout_seconds > 0:
                sanitized_payload["timeout_seconds"] = min(float(timeout_seconds), 300.0)
        elif command == "browse":
            route = payload.get("route") or payload.get("target")
            if route not in self._VALID_BROWSE_ROUTES:
                raise RemoteControlError(
                    "Browse command requires valid 'route' in payload"
                )
            sanitized_payload["route"] = route
            media_type = payload.get("media_type")
            if media_type:
                sanitized_payload["media_type"] = str(media_type)[:50]
            for key in ("item_guid", "view_guid"):
                value = payload.get(key)
                if value:
                    sanitized_payload[key] = str(value)
            query = payload.get("query")
            if isinstance(query, str) and query.strip():
                sanitized_payload["query"] = query.strip()[:200]

        return sanitized_payload

    async def send_remote_control_command(
        self,
        *,
        user_id: str,
        target_device_id: str,
        command: str,
        payload: dict[str, Any] | None = None,
        from_device_id: str | None = None,
        actor_user_id: str | None = None,
    ) -> dict[str, Any]:
        """Send a remote-control command to a connected device."""
        if command not in self._VALID_RC_COMMANDS:
            raise RemoteControlError(f"Invalid command: {command}")

        if not self._check_rc_rate_limit(actor_user_id or user_id):
            raise RemoteControlError("Rate limit exceeded. Try again later.")

        sanitized_payload = self._sanitize_remote_control_payload(command, payload)

        target_connection = None
        async with self._lock:
            for conn in self._connections.values():
                if conn.device_id == target_device_id and conn.user_id == user_id:
                    target_connection = conn
                    break

        if not target_connection:
            raise RemoteControlError("Target device not connected")

        now = datetime.now(UTC).isoformat()
        try:
            await target_connection.send_event(
                "remote_control",
                {
                    "command": command,
                    "payload": sanitized_payload,
                    "from_device_id": from_device_id,
                    "from_user_id": actor_user_id or user_id,
                    "timestamp": now,
                },
            )
        except Exception as e:
            logger.error("Error forwarding remote control command: %s", e)
            raise RemoteControlError(
                "Failed to send command to target device"
            ) from e

        logger.info(
            "Remote control: user=%s actor=%s cmd=%s from=%s to=%s",
            user_id,
            actor_user_id or user_id,
            command,
            from_device_id,
            target_device_id,
        )
        return {
            "target_device_id": target_device_id,
            "command": command,
            "status": "sent",
            "timestamp": now,
        }

    async def _handle_remote_control(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle remote control commands from clients.

        Forwards commands to another device owned by the same user.
        """
        target_device_id = message.get("target_device_id")
        command = message.get("command")
        payload = message.get("payload") or {}

        # Validate required fields
        if not target_device_id or not command:
            await connection.send_event("error", {
                "message": "Missing target_device_id or command",
            })
            return

        if command not in self._VALID_RC_COMMANDS:
            await connection.send_event("error", {
                "message": f"Invalid command: {command}",
            })
            return

        try:
            result = await self.send_remote_control_command(
                user_id=connection.user_id,
                target_device_id=target_device_id,
                command=command,
                payload=payload,
                from_device_id=connection.device_id,
                actor_user_id=connection.user_id,
            )
        except RemoteControlError as e:
            await connection.send_event("remote_control_error", {
                "message": str(e),
                "target_device_id": target_device_id,
            })
            return

        await connection.send_event("remote_control_ack", result)


    async def _handle_party_sync(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle watch party playback synchronization.

        Message format:
        {
            "action": "party_sync",
            "party_id": "uuid",          // Required: watch party identifier
            "current_time": 123.45,      // Required: playback position in seconds
            "is_playing": true,          // Required: playback state
            "playback_rate": 1.0         // Optional: playback speed
        }

        This broadcasts the sync event to all members of the watch party.
        """
        party_id = message.get("party_id")
        current_time = message.get("current_time")
        is_playing = message.get("is_playing")
        playback_rate = message.get("playback_rate", 1.0)

        if not party_id or current_time is None or is_playing is None:
            await connection.send_event(
                "error",
                {
                    "message": "Missing party_id, current_time, or is_playing",
                },
            )
            return

        # Broadcast sync to all party members
        await self.broadcast_to_resource(
            resource_type="party",
            resource_id=party_id,
            event="party_sync",
            data={
                "party_id": party_id,
                "current_time": current_time,
                "is_playing": is_playing,
                "playback_rate": playback_rate,
                "from_user_id": connection.user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.debug(
            "Watch party %s sync: position=%ss, playing=%s, from user=%s",
            party_id, current_time, is_playing, connection.user_id,
        )

        # Persist sync state to DB (throttled: every 10s or on pause)
        now = time.monotonic()
        last_write = self._last_sync_persist.get(party_id, 0)
        should_persist = (now - last_write > 10) or not is_playing

        if should_persist:
            self._last_sync_persist[party_id] = now
            try:
                from pyrate.database import sessionmanager
                from pyrate.models.party import WatchParty

                async with sessionmanager.session() as db:
                    from sqlalchemy import select

                    stmt = select(WatchParty).where(
                        WatchParty.guid == UUID(party_id),
                        WatchParty.is_active,
                    )
                    result = await db.execute(stmt)
                    session = result.scalar_one_or_none()
                    if session:
                        session.current_time = current_time
                        session.is_playing = is_playing
                        session.playback_rate = playback_rate
                        session.last_sync_at = datetime.now(UTC)
                        await db.commit()
            except Exception:
                logger.warning(
                    "Failed to persist watch party sync to DB for %s", party_id
                )

    async def _handle_party_member_update(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle watch party member status updates.

        Message format:
        {
            "action": "party_member_update",
            "party_id": "uuid",          // Required: watch party identifier
            "last_position": 123.45,     // Optional: current position
            "is_connected": true         // Optional: connection status
        }

        This broadcasts member updates to all party members.
        """
        party_id = message.get("party_id")
        last_position = message.get("last_position")
        is_connected = message.get("is_connected", True)

        if not party_id:
            await connection.send_event(
                "error",
                {
                    "message": "Missing party_id",
                },
            )
            return

        # Broadcast member update to all party members
        await self.broadcast_to_resource(
            resource_type="party",
            resource_id=party_id,
            event="party_member_update",
            data={
                "party_id": party_id,
                "user_id": connection.user_id,
                "last_position": last_position,
                "is_connected": is_connected,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.debug(
            "Watch party %s member update: user=%s, position=%s, connected=%s",
            party_id, connection.user_id, last_position, is_connected,
        )

    async def _handle_party_request_sync(
        self,
        connection: WebSocketConnection,
        message: dict[str, Any],
    ):
        """
        Handle a late joiner requesting the current playback state.

        Broadcasts a sync_requested event so the host can respond
        with its current player state.
        """
        party_id = message.get("party_id")

        if not party_id:
            await connection.send_event(
                "error",
                {"message": "Missing party_id"},
            )
            return

        await self.broadcast_to_resource(
            resource_type="party",
            resource_id=party_id,
            event="party_sync_requested",
            data={
                "party_id": party_id,
                "requesting_user_id": connection.user_id,
                "timestamp": datetime.now(UTC).isoformat(),
            },
        )

        logger.debug(
            "Watch party %s sync requested by user=%s",
            party_id, connection.user_id,
        )


# Global singleton instance
_websocket_manager: WebSocketManager | None = None


def get_websocket_manager() -> WebSocketManager:
    """Get the global WebSocket manager instance."""
    global _websocket_manager
    if _websocket_manager is None:
        _websocket_manager = WebSocketManager()
    return _websocket_manager
