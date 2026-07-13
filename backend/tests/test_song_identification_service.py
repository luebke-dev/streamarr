from unittest.mock import AsyncMock, MagicMock

import pytest

from streamarr.services.song_identification import SongIdentificationService


@pytest.mark.asyncio
async def test_extract_audio_uses_configured_ffmpeg_task(monkeypatch):
    captured_volume_args = {}
    captured_task = {}
    deleted_tasks = []

    def fake_build_media_volumes(**kwargs):
        captured_volume_args.update(kwargs)
        return {
            "/host/downloads": "/downloads",
            "/host/temp": "/temp",
        }

    class FakeComputingService:
        def __init__(self, db):
            self.db = db

        async def __aenter__(self):
            return self

        async def __aexit__(self, _exc_type, _exc_val, _exc_tb):
            return False

        async def start_task(self, **kwargs):
            captured_task.update(kwargs)
            return "task-identify"

        async def get_task_status(self, task_id):
            assert task_id == "task-identify"
            return "completed"

        async def get_task_logs(self, task_id):
            assert task_id == "task-identify"
            return "ok"

        async def delete_task(self, task_id):
            deleted_tasks.append(task_id)

    settings_service = MagicMock()
    settings_service.get_transcoding_settings = AsyncMock(
        return_value={"ffmpeg_image": "custom/ffmpeg:latest"}
    )

    monkeypatch.setattr(
        "streamarr.services.song_identification.build_media_volumes",
        fake_build_media_volumes,
    )
    monkeypatch.setattr(
        "streamarr.services.song_identification._ffmpeg_runtime_user",
        lambda: {"PUID": "123", "PGID": "456"},
    )
    monkeypatch.setattr(
        "streamarr.services.song_identification.SystemSettingsService",
        MagicMock(return_value=settings_service),
    )
    monkeypatch.setattr(
        "streamarr.services.song_identification.ComputingService",
        FakeComputingService,
    )

    status, output = await SongIdentificationService(object())._extract_audio(
        "/downloads/movie.mkv",
        12.8,
        15,
        "/temp/shazam.wav",
    )

    assert status == "completed"
    assert output == "ok"
    assert deleted_tasks == ["task-identify"]

    assert captured_volume_args == {
        "include_writable_temp": True,
        "include_cache": False,
        "include_downloads": True,
        "read_only": True,
    }
    assert captured_task["image"] == "custom/ffmpeg:latest"
    assert captured_task["entrypoint"] == ["ffmpeg"]
    assert captured_task["env"] == {"PUID": "123", "PGID": "456"}
    assert captured_task["volumes"] == {
        "/host/downloads": "/downloads",
        "/host/temp": "/temp",
    }
    assert captured_task["timeout_seconds"] == 60
    assert captured_task["labels"]["streamarr.task_type"] == "song_identification"

    command = captured_task["command"]
    assert command[:4] == ["-hide_banner", "-loglevel", "error", "-ss"]
    assert command[command.index("-i") + 1] == "/downloads/movie.mkv"
    assert "-vn" in command
    assert command[-1] == "/temp/shazam.wav"
