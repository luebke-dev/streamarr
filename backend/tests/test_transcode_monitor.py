"""The transcode monitor must tell "finished" apart from "crashed".

ffmpeg exits 0 when it reaches the end of the media, and its container is then
gone exactly like a crashed one. The monitor treated both as a crash and
restarted the transcode from position 0 - re-encoding over the segment files the
player was downloading. That surfaced as the stream stalling every few minutes,
and it repeated for as long as the session stayed active: a full encode per
cycle, for an episode that was already complete on disk.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamarr.workers.playback import TranscodeMonitorWorker


def _session(session_id="s1", status="active"):
    return MagicMock(session_id=session_id, status=status)


def _session_service():
    service = MagicMock()
    service.mark_completed = AsyncMock(return_value=True)
    service.recover_crashed_session = AsyncMock(return_value="restarted")
    return service


def _computing(statuses):
    """A computing provider whose label lookup reports ``statuses``."""
    provider = MagicMock()
    provider.get_tasks_by_label = AsyncMock(
        return_value=[{"status": status} for status in statuses]
    )
    return provider


@asynccontextmanager
async def _fake_session():
    yield MagicMock()


@asynccontextmanager
async def _fake_computing(db):  # noqa: ARG001 - mirrors the real signature
    yield _fake_computing.provider


def _patched(provider):
    _fake_computing.provider = provider
    return (
        patch("streamarr.workers.playback.sessionmanager.session", _fake_session),
        patch("streamarr.workers.playback.ComputingService", _fake_computing),
        patch(
            "streamarr.workers.playback.get_redis_event_service", MagicMock()
        ),
        patch("streamarr.workers.playback.start_transcode_container", AsyncMock()),
    )


async def _monitor(sessions, statuses):
    service = _session_service()
    worker = TranscodeMonitorWorker(max_retries=2)
    patches = _patched(_computing(statuses))
    for applied in patches:
        applied.start()
    try:
        result = await worker._monitor_sessions(service, sessions)
    finally:
        for applied in reversed(patches):
            applied.stop()
    return result, service


@pytest.mark.asyncio
async def test_a_finished_transcode_is_not_restarted():
    """The bug: exit 0 means "the media is done", not "recover this"."""
    result, service = await _monitor([_session()], ["completed"])

    assert result == {"checked": 1, "restarted": 0, "failed": 0, "completed": 1}
    service.mark_completed.assert_awaited_once_with("s1")
    service.recover_crashed_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_running_transcode_is_left_alone():
    result, service = await _monitor([_session()], ["running"])

    assert result["checked"] == 1
    assert result["completed"] == 0
    service.mark_completed.assert_not_awaited()
    service.recover_crashed_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_vanished_container_is_recovered():
    result, service = await _monitor([_session()], [])

    assert result["restarted"] == 1
    service.recover_crashed_session.assert_awaited_once()
    service.mark_completed.assert_not_awaited()


@pytest.mark.asyncio
async def test_an_already_completed_session_is_skipped():
    """Otherwise the next monitor run would start the cycle all over again."""
    result, service = await _monitor([_session(status="completed")], ["completed"])

    assert result["checked"] == 0
    service.mark_completed.assert_not_awaited()
    service.recover_crashed_session.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_restart_container_wins_over_the_old_exited_one():
    """A restart leaves the previous container around briefly."""
    result, _ = await _monitor([_session()], ["completed", "running"])

    assert result["restarted"] == 0
    assert result["completed"] == 0


@pytest.mark.asyncio
async def test_an_unknown_status_is_treated_as_running():
    """A docker hiccup must not kill a healthy transcode."""
    service = _session_service()
    worker = TranscodeMonitorWorker(max_retries=2)
    provider = MagicMock()
    provider.get_tasks_by_label = AsyncMock(side_effect=RuntimeError("docker down"))

    patches = _patched(provider)
    for applied in patches:
        applied.start()
    try:
        result = await worker._monitor_sessions(service, [_session()])
    finally:
        for applied in reversed(patches):
            applied.stop()

    assert result["restarted"] == 0
    service.recover_crashed_session.assert_not_awaited()
