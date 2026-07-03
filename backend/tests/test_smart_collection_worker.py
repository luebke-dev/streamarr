"""Unit tests for the smart-collection worker functions.

The worker functions are intentionally exposed as ``_impl`` coroutines so
they can be exercised without booting taskiq's broker. We mock the DB
session, the Redis client and the dispatch target.
"""

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from pyrate.models.smart_collection import SmartCollectionRunStatus
from pyrate.workers import smart_collection_worker as worker


# ---------------------------------------------------------------------------
# tick_smart_collections_impl
# ---------------------------------------------------------------------------


class _FakeRedis:
    """Minimal async stand-in for redis.asyncio.Redis used in the worker."""

    def __init__(self, *, can_acquire: bool = True) -> None:
        self.can_acquire = can_acquire
        self.set_calls: list[tuple] = []
        self.delete_calls: list[str] = []
        self.closed = False

    async def set(self, key, value, ex=None, nx=False):
        self.set_calls.append((key, value, ex, nx))
        return self.can_acquire

    async def delete(self, key):
        self.delete_calls.append(key)

    async def close(self):
        self.closed = True


def _due_rules(*guids):
    """Return SQLAlchemy-style ``.all()`` rows for a fake query result."""
    return [(g,) for g in guids]


class TestTick:
    @pytest.mark.asyncio
    async def test_skips_when_lock_held(self):
        redis = _FakeRedis(can_acquire=False)
        with patch.object(
            worker.redis_async, "from_url", return_value=redis
        ):
            enqueued = await worker.tick_smart_collections_impl()
        assert enqueued == 0
        assert redis.closed is True
        # We never reached the worker import path.

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self):
        redis = _FakeRedis()
        fake_db = AsyncMock()
        fake_settings = AsyncMock()
        fake_settings.get = AsyncMock(return_value=False)  # disabled
        with (
            patch.object(worker.redis_async, "from_url", return_value=redis),
            patch.object(worker.sessionmanager, "session") as session_cm,
            patch.object(worker, "SettingsService", return_value=fake_settings),
        ):
            session_cm.return_value.__aenter__.return_value = fake_db
            session_cm.return_value.__aexit__.return_value = None
            enqueued = await worker.tick_smart_collections_impl()
        assert enqueued == 0

    @pytest.mark.asyncio
    async def test_dispatches_due_rules(self):
        redis = _FakeRedis()
        fake_db = AsyncMock()
        fake_settings = AsyncMock()
        fake_settings.get = AsyncMock(return_value=True)
        guid1 = "11111111-1111-1111-1111-111111111111"
        guid2 = "22222222-2222-2222-2222-222222222222"
        execute_result = MagicMock()
        execute_result.all = MagicMock(return_value=_due_rules(guid1, guid2))
        fake_db.execute = AsyncMock(return_value=execute_result)

        kiq_calls: list[str] = []
        fake_task = SimpleNamespace(
            kiq=AsyncMock(side_effect=lambda g: kiq_calls.append(g))
        )
        with (
            patch.object(worker.redis_async, "from_url", return_value=redis),
            patch.object(worker.sessionmanager, "session") as session_cm,
            patch.object(worker, "SettingsService", return_value=fake_settings),
            patch(
                "pyrate.worker.run_smart_collection_rule",
                fake_task,
                create=True,
            ),
        ):
            session_cm.return_value.__aenter__.return_value = fake_db
            session_cm.return_value.__aexit__.return_value = None
            enqueued = await worker.tick_smart_collections_impl()
        assert enqueued == 2
        assert kiq_calls == [guid1, guid2]
        assert redis.delete_calls == [worker._TICK_LOCK_KEY]


# ---------------------------------------------------------------------------
# run_smart_collection_rule_impl
# ---------------------------------------------------------------------------


class TestRunRuleImpl:
    @pytest.mark.asyncio
    async def test_rejects_invalid_guid(self):
        with pytest.raises(ValueError):
            await worker.run_smart_collection_rule_impl("not-a-uuid")

    @pytest.mark.asyncio
    async def test_invokes_service_and_records_events(self):
        rule_guid = "33333333-3333-3333-3333-333333333333"
        run_guid = "44444444-4444-4444-4444-444444444444"

        fake_db = AsyncMock()
        fake_settings = AsyncMock()
        fake_settings.get = AsyncMock(return_value={"tmdb": "key"})

        fake_result = SimpleNamespace(
            rule_guid=rule_guid,
            run_guid=run_guid,
            status=SmartCollectionRunStatus.SUCCESS,
            items_added=12,
            items_removed=3,
            items_unresolved=1,
            items_resolved=12,
            items_filtered=12,
            items_fetched=20,
            duration_ms=421,
            error=None,
        )
        fake_service = MagicMock()
        fake_service.run = AsyncMock(return_value=fake_result)

        events: list[dict] = []

        async def fake_record(**kwargs):
            events.append(kwargs)
            return kwargs.get("run_id") or "run-id"

        with (
            patch.object(worker.sessionmanager, "session") as session_cm,
            patch.object(worker, "SettingsService", return_value=fake_settings),
            patch.object(
                worker, "SmartCollectionService", return_value=fake_service
            ),
            patch.object(worker, "record_worker_task_event", side_effect=fake_record),
        ):
            session_cm.return_value.__aenter__.return_value = fake_db
            session_cm.return_value.__aexit__.return_value = None
            payload = await worker.run_smart_collection_rule_impl(rule_guid)

        assert payload["status"] == "SUCCESS"
        assert payload["items_added"] == 12
        # First event = "queued", second = "completed"
        assert [e["status"] for e in events] == ["queued", "completed"]
        assert rule_guid in events[0]["message"]
        assert "+12/-3 items" in events[1]["message"]
        fake_service.run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_marks_failed_status_correctly(self):
        rule_guid = "55555555-5555-5555-5555-555555555555"
        run_guid = "66666666-6666-6666-6666-666666666666"

        fake_result = SimpleNamespace(
            rule_guid=rule_guid,
            run_guid=run_guid,
            status=SmartCollectionRunStatus.FAILED,
            items_added=0,
            items_removed=0,
            items_unresolved=0,
            items_resolved=0,
            items_filtered=0,
            items_fetched=0,
            duration_ms=12,
            error="boom",
        )
        fake_service = MagicMock()
        fake_service.run = AsyncMock(return_value=fake_result)

        events: list[dict] = []

        async def fake_record(**kwargs):
            events.append(kwargs)
            return "run-id"

        fake_settings = AsyncMock()
        fake_settings.get = AsyncMock(return_value={})

        with (
            patch.object(worker.sessionmanager, "session") as session_cm,
            patch.object(worker, "SettingsService", return_value=fake_settings),
            patch.object(
                worker, "SmartCollectionService", return_value=fake_service
            ),
            patch.object(worker, "record_worker_task_event", side_effect=fake_record),
        ):
            session_cm.return_value.__aenter__.return_value = AsyncMock()
            session_cm.return_value.__aexit__.return_value = None
            payload = await worker.run_smart_collection_rule_impl(rule_guid)

        assert payload["status"] == "FAILED"
        assert payload["error"] == "boom"
        assert events[-1]["status"] == "failed"
        assert events[-1]["error"] == "boom"
