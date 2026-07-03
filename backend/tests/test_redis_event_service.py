"""Tests for RedisEventService (publish / subscribe via Redis Pub/Sub)."""

import asyncio
import json
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from pyrate.services.redis_event import RedisEventService, CHANNEL_PREFIX


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def service() -> RedisEventService:
    svc = RedisEventService()
    # Use a mock Redis to avoid real connections
    mock_redis = AsyncMock()
    mock_redis.publish = AsyncMock(return_value=1)
    mock_redis.pubsub = MagicMock()

    mock_pubsub = AsyncMock()
    mock_pubsub.subscribe = AsyncMock()
    mock_pubsub.unsubscribe = AsyncMock()
    mock_pubsub.listen = MagicMock(return_value=iter([]))
    mock_redis.pubsub.return_value = mock_pubsub

    svc._redis = mock_redis
    return svc


# ---------------------------------------------------------------------------
# Channel naming
# ---------------------------------------------------------------------------

class TestChannelNaming:
    def test_get_channel_name(self):
        svc = RedisEventService()
        assert svc._get_channel_name("episode:123") == f"{CHANNEL_PREFIX}episode:123"


# ---------------------------------------------------------------------------
# Publish
# ---------------------------------------------------------------------------

class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_event(self, service: RedisEventService):
        count = await service.publish("test:channel", "test_event", {"key": "value"})
        assert count == 1
        service._redis.publish.assert_awaited_once()

        # Verify the published message structure
        call_args = service._redis.publish.call_args
        channel = call_args[0][0]
        raw_msg = call_args[0][1]
        msg = json.loads(raw_msg)
        assert channel == f"{CHANNEL_PREFIX}test:channel"
        assert msg["event"] == "test_event"
        assert msg["data"]["key"] == "value"
        assert "timestamp" in msg


# ---------------------------------------------------------------------------
# Convenience publishers
# ---------------------------------------------------------------------------

class TestConveniencePublishers:
    @pytest.mark.asyncio
    async def test_publish_episode_releases_updated(self, service: RedisEventService):
        episode_id = uuid.uuid4()
        await service.publish_episode_releases_updated(
            episode_id=episode_id,
            releases_count=5,
            total_found=10,
            message="Found new releases",
        )
        service._redis.publish.assert_awaited_once()
        call_args = service._redis.publish.call_args
        msg = json.loads(call_args[0][1])
        assert msg["event"] == "releases_updated"
        assert msg["data"]["releases_count"] == 5

    @pytest.mark.asyncio
    async def test_publish_movie_releases_updated(self, service: RedisEventService):
        movie_id = uuid.uuid4()
        await service.publish_movie_releases_updated(
            movie_id=movie_id,
            releases_count=3,
            total_found=8,
        )
        service._redis.publish.assert_awaited_once()
        call_args = service._redis.publish.call_args
        msg = json.loads(call_args[0][1])
        assert msg["data"]["movie_id"] == str(movie_id)

    @pytest.mark.asyncio
    async def test_publish_media_item_updated(self, service: RedisEventService):
        media_id = uuid.uuid4()
        await service.publish_media_item_updated(
            media_item_id=media_id,
            update_type="files_updated",
            data={"file_count": 2},
        )
        service._redis.publish.assert_awaited_once()
        call_args = service._redis.publish.call_args
        msg = json.loads(call_args[0][1])
        assert msg["event"] == "files_updated"
        assert msg["data"]["file_count"] == 2


# ---------------------------------------------------------------------------
# Subscribe / Unsubscribe
# ---------------------------------------------------------------------------

class TestSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_registers_handler(self, service: RedisEventService):
        handler = AsyncMock()
        # Patch _start_subscriber to avoid background task
        with patch.object(service, "_start_subscriber", new_callable=AsyncMock):
            await service.subscribe("test:channel", handler)

        full_channel = f"{CHANNEL_PREFIX}test:channel"
        assert full_channel in service._handlers
        assert handler in service._handlers[full_channel]

    @pytest.mark.asyncio
    async def test_unsubscribe_removes_handler(self, service: RedisEventService):
        handler = AsyncMock()
        full_channel = f"{CHANNEL_PREFIX}test:channel"

        # Set up pubsub
        mock_pubsub = AsyncMock()
        mock_pubsub.subscribe = AsyncMock()
        mock_pubsub.unsubscribe = AsyncMock()
        service._pubsub = mock_pubsub

        with patch.object(service, "_start_subscriber", new_callable=AsyncMock):
            await service.subscribe("test:channel", handler)

        await service.unsubscribe("test:channel", handler)

        assert full_channel not in service._handlers or handler not in service._handlers.get(full_channel, [])


# ---------------------------------------------------------------------------
# Stop
# ---------------------------------------------------------------------------

class TestStop:
    @pytest.mark.asyncio
    async def test_stop_cleans_up(self, service: RedisEventService):
        service._running = True

        # Create a real task that blocks until cancelled
        async def blocked():
            await asyncio.sleep(3600)

        mock_task = asyncio.create_task(blocked())
        service._subscriber_task = mock_task

        mock_pubsub = AsyncMock()
        mock_pubsub.close = AsyncMock()
        service._pubsub = mock_pubsub

        await service.stop()

        assert service._running is False
        assert mock_task.cancelled()
