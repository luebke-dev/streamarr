"""Taskiq result backend must expire its results.

Taskiq's ``RedisAsyncResultBackend`` defaults to ``keep_results=True`` with no
expiry, and its ``set_result`` only adds an ``ex``/``px`` argument when one of
the TTL options is set. With the defaults every finished task therefore left a
permanent Redis key behind. Nothing in the codebase reads a result back, so the
keys accumulated unbounded: the live instance had grown to ~5M keys holding
1.3 GB, making Redis the largest memory consumer on the host and a repeated
cgroup OOM victim.

These tests pin the wiring so the TTL cannot silently disappear again.
"""

from pathlib import Path
from unittest.mock import patch

import pytest


def _build(ttl_seconds):
    """Call the real builder while capturing its constructor arguments.

    ``conftest.py`` replaces ``taskiq_redis`` with a blanket MagicMock, so the
    kwargs are recorded through the module reference the builder actually uses.
    """
    from streamarr.workers import runtime

    captured = {}

    class _RecordingBackend:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    with patch.object(runtime, "RedisAsyncResultBackend", _RecordingBackend):
        runtime.build_result_backend("redis://example/0", ttl_seconds)

    return captured


def test_default_ttl_is_one_hour():
    from streamarr.workers import runtime

    assert runtime._RESULT_TTL_SECONDS == 3600


def test_result_backend_sets_an_expiry():
    """The core regression: a positive TTL must reach the backend."""
    captured = _build(3600)

    assert captured["result_ex_time"] == 3600


def test_result_backend_passes_the_redis_url():
    captured = _build(3600)

    assert captured["redis_url"] == "redis://example/0"


def test_ttl_is_configurable():
    assert _build(120)["result_ex_time"] == 120


@pytest.mark.parametrize("value", [0, -1])
def test_zero_or_negative_ttl_disables_expiry_explicitly(value):
    """An explicit opt-out restores Taskiq's keep-forever behaviour."""
    assert _build(value)["result_ex_time"] is None


def test_source_keeps_the_ttl_argument():
    """Catch a dropped TTL at the source level, independent of the mocks."""
    source = (
        Path(__file__).resolve().parent.parent
        / "src"
        / "streamarr"
        / "workers"
        / "runtime.py"
    ).read_text()

    assert "RedisAsyncResultBackend(" in source
    assert "result_ex_time=" in source
    # And the module-level backend must be built through the helper, not with
    # a bare constructor call that could quietly omit the TTL again.
    assert "result_backend = build_result_backend(" in source
