from types import SimpleNamespace

from streamarr.services.playback_session import _normalize_transcode_start_position


def _media_file(duration):
    return SimpleNamespace(duration=duration)


def test_normalize_transcode_start_resets_positions_beyond_duration():
    assert _normalize_transcode_start_position(_media_file(3275.328), 3514) == 0


def test_normalize_transcode_start_clamps_positions_too_close_to_end():
    assert _normalize_transcode_start_position(_media_file(100), 95) == 90


def test_normalize_transcode_start_keeps_valid_resume_position():
    assert _normalize_transcode_start_position(_media_file(100), 45) == 45


def test_normalize_transcode_start_preserves_unknown_duration_positions():
    assert _normalize_transcode_start_position(_media_file(None), 45) == 45
