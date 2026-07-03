"""Redis Pub/Sub event service for real-time event distribution across containers."""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import redis.asyncio as redis

from pyrate.config import settings

logger = logging.getLogger(__name__)

# Redis channel prefix for pub/sub
CHANNEL_PREFIX = "pyrate:events:"


class RedisEventService:
    """
    Manages Redis Pub/Sub for event distribution across multiple containers.

    This allows events to be published from any container (including workers)
    and received by all connected WebSocket clients regardless of which
    container they're connected to.
    """

    def __init__(self):
        self._redis: redis.Redis | None = None
        self._pubsub: redis.client.PubSub | None = None
        self._subscriber_task: asyncio.Task | None = None
        self._handlers: dict[str, list[Callable[[dict[str, Any]], Coroutine]]] = {}
        self._lock = asyncio.Lock()
        self._running = False

    async def _get_redis(self) -> redis.Redis:
        """Get or create Redis connection for publishing."""
        if self._redis is None:
            self._redis = redis.from_url(
                settings.redis_url,
                encoding="utf-8",
                decode_responses=True,
            )
        return self._redis

    def _get_channel_name(self, channel: str) -> str:
        """Get the full Redis channel name with prefix."""
        return f"{CHANNEL_PREFIX}{channel}"

    async def publish(
        self,
        channel: str,
        event: str,
        data: dict[str, Any],
    ) -> int:
        """
        Publish an event to a channel.

        Args:
            channel: The channel to publish to (e.g., "episode:uuid")
            event: The event type (e.g., "releases_updated")
            data: The event data

        Returns:
            Number of subscribers that received the message
        """
        r = await self._get_redis()

        message = {
            "event": event,
            "data": data,
            "timestamp": datetime.now(UTC).isoformat(),
        }

        full_channel = self._get_channel_name(channel)
        count = await r.publish(full_channel, json.dumps(message))

        logger.debug("Published '%s' to %s, %s subscribers", event, full_channel, count)
        return count

    async def publish_episode_releases_updated(
        self,
        episode_id: UUID,
        releases_count: int,
        total_found: int,
        message: str | None = None,
    ):
        """
        Publish that releases for an episode have been updated.

        This is a convenience method for the common use case.
        """
        await self.publish(
            channel=f"episode:{episode_id}",
            event="releases_updated",
            data={
                "episode_id": str(episode_id),
                "releases_count": releases_count,
                "total_found": total_found,
                "message": message,
            },
        )

    async def publish_movie_releases_updated(
        self,
        movie_id: UUID,
        releases_count: int,
        total_found: int,
        message: str | None = None,
    ):
        """
        Publish that releases for a movie have been updated.

        This is a convenience method for movie release notifications.
        """
        await self.publish(
            channel=f"movie:{movie_id}",
            event="releases_updated",
            data={
                "movie_id": str(movie_id),
                "releases_count": releases_count,
                "total_found": total_found,
                "message": message,
            },
        )

    async def publish_media_item_updated(
        self,
        media_item_id: UUID,
        update_type: str,
        data: dict[str, Any],
    ):
        """
        Publish that a media item has been updated.

        Args:
            media_item_id: The GUID of the media item
            update_type: Type of update (e.g., "releases_updated", "files_updated")
            data: Additional data about the update
        """
        await self.publish(
            channel=f"media_item:{media_item_id}",
            event=update_type,
            data={
                "media_item_id": str(media_item_id),
                **data,
            },
        )

    async def subscribe(
        self,
        channel: str,
        handler: Callable[[dict[str, Any]], Coroutine],
    ):
        """
        Subscribe to a channel with a handler function.

        Args:
            channel: The channel to subscribe to
            handler: Async function to call when a message is received
        """
        full_channel = self._get_channel_name(channel)

        async with self._lock:
            if full_channel not in self._handlers:
                self._handlers[full_channel] = []

                # Subscribe to the channel in Redis
                if self._pubsub is None:
                    r = await self._get_redis()
                    self._pubsub = r.pubsub()

                await self._pubsub.subscribe(full_channel)
                logger.debug("Subscribed to Redis channel: %s", full_channel)

            self._handlers[full_channel].append(handler)

        # Start the subscriber task if not running
        if not self._running:
            await self._start_subscriber()

    async def unsubscribe(
        self,
        channel: str,
        handler: Callable[[dict[str, Any]], Coroutine],
    ):
        """
        Unsubscribe a handler from a channel.

        Args:
            channel: The channel to unsubscribe from
            handler: The handler to remove
        """
        full_channel = self._get_channel_name(channel)

        async with self._lock:
            if full_channel in self._handlers:
                try:
                    self._handlers[full_channel].remove(handler)
                except ValueError:
                    logger.debug("Handler already removed from channel %s", full_channel)

                # If no more handlers, unsubscribe from Redis
                if not self._handlers[full_channel]:
                    del self._handlers[full_channel]
                    if self._pubsub:
                        await self._pubsub.unsubscribe(full_channel)
                        logger.debug("Unsubscribed from Redis channel: %s", full_channel)

    async def _start_subscriber(self):
        """Start the background task that listens for Redis messages."""
        if self._running:
            return

        self._running = True
        self._subscriber_task = asyncio.create_task(self._subscriber_loop())
        logger.info("Started Redis Pub/Sub subscriber loop")

    async def _subscriber_loop(self):
        """Background loop that receives messages from Redis and dispatches to handlers."""
        try:
            while self._running and self._pubsub:
                try:
                    message = await self._pubsub.get_message(
                        ignore_subscribe_messages=True,
                        timeout=1.0,
                    )

                    if message is None:
                        continue

                    if message["type"] != "message":
                        continue

                    channel = message["channel"]
                    try:
                        data = json.loads(message["data"])
                    except json.JSONDecodeError:
                        logger.warning("Invalid JSON in message on %s", channel)
                        continue

                    # Dispatch to handlers
                    async with self._lock:
                        handlers = list(self._handlers.get(channel, []))

                    for handler in handlers:
                        try:
                            await handler(data)
                        except Exception as e:
                            logger.error("Handler error on %s: %s", channel, e)

                except asyncio.CancelledError:
                    break
                except Exception as e:
                    logger.error("Error in subscriber loop: %s", e)
                    await asyncio.sleep(1)  # Backoff on error

        finally:
            self._running = False
            logger.info("Redis Pub/Sub subscriber loop stopped")

    async def stop(self):
        """Stop the subscriber and close connections."""
        self._running = False

        if self._subscriber_task:
            self._subscriber_task.cancel()
            try:
                await self._subscriber_task
            except asyncio.CancelledError:
                logger.debug("Redis subscriber task cancelled during shutdown")
            self._subscriber_task = None

        if self._pubsub:
            await self._pubsub.close()
            self._pubsub = None

        if self._redis:
            await self._redis.close()
            self._redis = None

        logger.info("Redis event service stopped")


# Global singleton instance
_redis_event_service: RedisEventService | None = None


def get_redis_event_service() -> RedisEventService:
    """Get the global Redis event service instance."""
    global _redis_event_service
    if _redis_event_service is None:
        _redis_event_service = RedisEventService()
    return _redis_event_service


async def shutdown_redis_event_service():
    """Shutdown the global Redis event service."""
    global _redis_event_service
    if _redis_event_service is not None:
        await _redis_event_service.stop()
        _redis_event_service = None
