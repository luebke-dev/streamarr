from types import SimpleNamespace

from streamarr.services.playback_session import (
    _enforce_hls_ts_compatibility,
    _normalize_transcode_start_position,
)


def test_hls_ts_transcodes_av1_and_opus_copies():
    decision = SimpleNamespace(
        can_direct_file_play=False,
        codec_result=SimpleNamespace(video_codec="copy", audio_codec="copy"),
        source_info={"video_codec": "av1", "audio_codec": "opus"},
        effective_video_codec="copy",
        effective_audio_codec="copy",
        transcode_reasons=[],
        needs_transcode=False,
        can_direct_stream=True,
        can_transcode=False,
        playback_method="direct_stream",
    )

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "h264"
    assert decision.codec_result.audio_codec == "aac"
    assert decision.needs_transcode is True
    assert decision.playback_method == "transcode"


def test_hls_ts_keeps_h264_and_aac_copies():
    decision = SimpleNamespace(
        can_direct_file_play=False,
        codec_result=SimpleNamespace(video_codec="copy", audio_codec="copy"),
        source_info={"video_codec": "h264", "audio_codec": "aac"},
        effective_video_codec="copy",
        effective_audio_codec="copy",
        transcode_reasons=[],
        needs_transcode=False,
        can_direct_stream=True,
        can_transcode=True,
        playback_method="direct_stream",
    )

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "copy"
    assert decision.codec_result.audio_codec == "copy"
    assert decision.needs_transcode is False


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
