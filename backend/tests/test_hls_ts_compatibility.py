"""Copying a codec into MPEG-TS HLS is not the same as the browser decoding it.

Codec negotiation answers "can this client decode AV1?". For an HLS stream that
answer is not enough: hls.js demuxes MPEG-TS, and MPEG-TS does not carry AV1 or
VP9 video nor Opus or FLAC audio. A direct-copy decision made on codec support
alone therefore produced a valid playlist holding segments no browser could
play - a black player with a 200 response, which is a miserable thing to debug.
"""

from types import SimpleNamespace

import pytest

from streamarr.services.playback_session import _enforce_hls_ts_compatibility


def _decision(video="h264", audio="aac", *, direct_file=False, no_codec_result=False):
    return SimpleNamespace(
        can_direct_file_play=direct_file,
        codec_result=None
        if no_codec_result
        else SimpleNamespace(video_codec="copy", audio_codec="copy"),
        source_info={"video_codec": video, "audio_codec": audio},
        effective_video_codec="copy",
        effective_audio_codec="copy",
        transcode_reasons=[],
        needs_transcode=False,
        can_direct_stream=True,
        can_transcode=True,
        playback_method="direct_stream",
    )


def test_av1_and_opus_copies_become_a_transcode():
    decision = _decision(video="av1", audio="opus")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "h264"
    assert decision.codec_result.audio_codec == "aac"
    assert decision.effective_video_codec == "h264"
    assert decision.effective_audio_codec == "aac"
    assert decision.needs_transcode is True
    assert decision.can_direct_stream is False
    assert decision.playback_method == "transcode"
    assert len(decision.transcode_reasons) == 2


def test_h264_and_aac_copies_are_left_alone():
    decision = _decision(video="h264", audio="aac")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "copy"
    assert decision.codec_result.audio_codec == "copy"
    assert decision.needs_transcode is False
    assert decision.playback_method == "direct_stream"
    assert decision.transcode_reasons == []


def test_only_the_unsupported_track_is_re_encoded():
    """A copy of h264 video with Opus audio must keep the video untouched."""
    decision = _decision(video="h264", audio="opus")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "copy"
    assert decision.codec_result.audio_codec == "aac"
    assert decision.needs_transcode is True


@pytest.mark.parametrize("video", ["vp9", "AV1"])
def test_video_codecs_without_an_mpegts_tag_are_re_encoded(video):
    decision = _decision(video=video, audio="aac")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "h264"


@pytest.mark.parametrize("video", ["hevc", "h265", "hvc1"])
def test_hevc_copies_stay_copies(video):
    """The command builder tags them hvc1, which is what makes them play."""
    decision = _decision(video=video, audio="aac")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "copy"
    assert decision.needs_transcode is False


def test_ac3_audio_is_re_encoded_even_though_mpegts_carries_it():
    """Demuxable is not decodable: no Chrome MSE profile handles AC-3."""
    decision = _decision(video="h264", audio="ac3")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.audio_codec == "aac"
    assert decision.codec_result.video_codec == "copy"


def test_a_direct_file_play_is_not_touched():
    """Handing the browser the file itself has no MPEG-TS constraint."""
    decision = _decision(video="av1", audio="opus", direct_file=True)

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "copy"
    assert decision.needs_transcode is False


def test_a_decision_without_codec_negotiation_is_not_touched():
    decision = _decision(video="av1", audio="opus", no_codec_result=True)

    _enforce_hls_ts_compatibility(decision)

    assert decision.needs_transcode is False


def test_an_unknown_source_codec_is_treated_as_unsupported():
    """Better one needless encode than a stream that cannot play."""
    decision = _decision(video="", audio="")

    _enforce_hls_ts_compatibility(decision)

    assert decision.codec_result.video_codec == "h264"
    assert decision.codec_result.audio_codec == "aac"
