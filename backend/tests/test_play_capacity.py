"""Transcode capacity must not be blocked by bookkeeping that lags reality.

``max_concurrent_transcodes`` is counted from the active sessions in Redis, and
a session only stops being active when something clears it. Two cases leave it
marked active after its container is gone:

* the monitor cannot tell a dead container from an unknown one, and
* a play request the client abandoned mid-start leaves a session with no
  container at all.

Both ended the same way: the limit was "reached" on paper, every play request
got a 503, and only the six-hourly sweep could clear it. The capacity check now
sweeps once before refusing.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from streamarr.services.play import check_transcode_capacity


def _sessions(count):
    return [MagicMock(is_active=True) for _ in range(count)]


def _patch_deps(*, active_counts, max_concurrent, sweep_error=None):
    settings = MagicMock()
    settings.get_transcoding_settings = AsyncMock(
        return_value={"max_concurrent_transcodes": max_concurrent}
    )
    session_service = MagicMock()
    session_service.get_all_sessions = AsyncMock(
        side_effect=[_sessions(count) for count in active_counts]
    )
    session_service.cleanup_stale_sessions = AsyncMock(side_effect=sweep_error)

    return (
        patch(
            "streamarr.services.system_settings.SystemSettingsService",
            MagicMock(return_value=settings),
        ),
        patch(
            "streamarr.services.transcoding_session.get_transcoding_session_service",
            MagicMock(return_value=session_service),
        ),
        session_service,
    )


@pytest.mark.asyncio
async def test_unlimited_does_not_touch_the_session_store():
    settings_patch, service_patch, _ = _patch_deps(active_counts=[], max_concurrent=0)
    service_patch.new = MagicMock(side_effect=AssertionError("must not be consulted"))

    with settings_patch, service_patch:
        assert await check_transcode_capacity(db=None) is True


@pytest.mark.asyncio
async def test_below_the_limit_does_not_sweep():
    settings_patch, service_patch, session_service = _patch_deps(
        active_counts=[1], max_concurrent=2
    )

    with settings_patch, service_patch:
        assert await check_transcode_capacity(db=None) is True

    session_service.cleanup_stale_sessions.assert_not_awaited()


@pytest.mark.asyncio
async def test_a_stale_session_frees_the_slot_instead_of_a_503():
    """The outage case: limit reached by sessions whose containers are gone."""
    settings_patch, service_patch, session_service = _patch_deps(
        active_counts=[2, 1], max_concurrent=2
    )

    with settings_patch, service_patch:
        assert await check_transcode_capacity(db=None) is True

    session_service.cleanup_stale_sessions.assert_awaited_once()
    # Counted twice: once to notice the limit, once after the sweep.
    assert session_service.get_all_sessions.await_count == 2


@pytest.mark.asyncio
async def test_a_genuinely_full_server_still_refuses():
    settings_patch, service_patch, session_service = _patch_deps(
        active_counts=[2, 2], max_concurrent=2
    )

    with settings_patch, service_patch:
        assert await check_transcode_capacity(db=None) is False

    session_service.cleanup_stale_sessions.assert_awaited_once()


@pytest.mark.asyncio
async def test_a_failing_sweep_refuses_instead_of_admitting():
    settings_patch, service_patch, _ = _patch_deps(
        active_counts=[2], max_concurrent=2, sweep_error=RuntimeError("docker down")
    )

    with settings_patch, service_patch:
        assert await check_transcode_capacity(db=None) is False
