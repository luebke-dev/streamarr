"""Tests for worker task lifecycle event helpers."""

from types import SimpleNamespace

import pytest


@pytest.mark.asyncio
async def test_worker_task_event_middleware_records_queued_and_completed(monkeypatch):
    from pyrate.services import task_events

    recorded = []

    async def fake_record_worker_task_event(**kwargs):
        recorded.append(kwargs)
        return kwargs["run_id"]

    monkeypatch.setattr(
        task_events,
        "record_worker_task_event",
        fake_record_worker_task_event,
    )
    middleware = task_events.WorkerTaskEventMiddleware()
    message = SimpleNamespace(
        task_name="pyrate.worker.import_trending_movies",
        labels={"pyrate_category": "metadata"},
    )

    returned_message = await middleware.pre_send(message)
    await middleware.post_execute(message, SimpleNamespace(is_err=False))

    assert returned_message is message
    assert recorded[0]["status"] == "queued"
    assert recorded[0]["task_id"] == "pyrate.worker.import_trending_movies"
    assert recorded[0]["category"] == "metadata"
    assert recorded[1]["status"] == "completed"
    assert recorded[1]["run_id"] == recorded[0]["run_id"]


@pytest.mark.asyncio
async def test_worker_task_event_middleware_records_failed(monkeypatch):
    from pyrate.services import task_events

    recorded = []

    async def fake_record_worker_task_event(**kwargs):
        recorded.append(kwargs)
        return kwargs["run_id"]

    monkeypatch.setattr(
        task_events,
        "record_worker_task_event",
        fake_record_worker_task_event,
    )
    middleware = task_events.WorkerTaskEventMiddleware()
    message = SimpleNamespace(task_name="cleanup_storage", labels={})

    await middleware.pre_send(message)
    await middleware.post_execute(
        message,
        SimpleNamespace(is_err=True, error=RuntimeError("disk unavailable")),
    )

    assert recorded[0]["category"] == "cleanup"
    assert recorded[1]["status"] == "failed"
    assert recorded[1]["error"] == "disk unavailable"
    assert recorded[1]["run_id"] == recorded[0]["run_id"]
