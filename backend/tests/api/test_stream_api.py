"""Tests for the Stream API endpoints (/api/stream/*)."""

import shutil
import uuid
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _mock_token_service(session_id="test-session", file_path="/path/to/file.mp3", content_id="content-123"):
    """Build a mock play token service and play token."""
    mock_service = AsyncMock()
    mock_play_token = MagicMock()
    mock_play_token.session_id = session_id
    mock_play_token.file_path = file_path
    mock_play_token.content_id = content_id
    mock_service.get_token = AsyncMock(return_value=mock_play_token)
    mock_service.extend_ttl = AsyncMock()
    mock_service.delete_token = AsyncMock()
    return mock_service, mock_play_token


def _mock_token_service_invalid():
    """Build a mock play token service that returns None (invalid token)."""
    mock_service = AsyncMock()
    mock_service.get_token = AsyncMock(return_value=None)
    return mock_service


# ===========================================================================
# GET /{session_id}/playlist.m3u8
# ===========================================================================
class TestGetPlaylist:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/test-session/playlist.m3u8")
        assert resp.status_code == 401
        assert "No play token" in resp.json()["detail"]

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/test-session/playlist.m3u8?token=bad-token")
        assert resp.status_code == 401
        assert "Invalid or expired" in resp.json()["detail"]

    async def test_session_mismatch(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="different-session")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/test-session/playlist.m3u8?token=valid-token")
        assert resp.status_code == 403
        assert "does not match" in resp.json()["detail"]

    async def test_playlist_not_found(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            mock_path_cls.return_value = mock_path_instance

            resp = await client.get("/api/stream/test-session/playlist.m3u8?token=valid-token")
        assert resp.status_code == 404
        assert "Playlist not found" in resp.json()["detail"]

    async def test_success(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_instance.read_text.return_value = "#EXTM3U\n#EXT-X-TARGETDURATION:6\n"
            mock_path_cls.return_value = mock_path_instance

            resp = await client.get("/api/stream/test-session/playlist.m3u8?token=valid-token")
        assert resp.status_code == 200
        assert resp.headers["content-type"] == "application/vnd.apple.mpegurl"
        assert "#EXTM3U" in resp.text
        mock_service.extend_ttl.assert_called_once()

    async def test_token_from_header(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_instance.read_text.return_value = "#EXTM3U\n"
            mock_path_cls.return_value = mock_path_instance

            resp = await client.get(
                "/api/stream/test-session/playlist.m3u8",
                headers={"Authorization": "Bearer valid-token"},
            )
        assert resp.status_code == 200


# ===========================================================================
# GET /{session_id}/status
# ===========================================================================
class TestGetStreamStatus:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/test-session/status")
        assert resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/test-session/status?token=bad")
        assert resp.status_code == 401

    async def test_session_mismatch(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="other")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/test-session/status?token=tok")
        assert resp.status_code == 403

    async def test_status_ready(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
            patch("glob.glob", return_value=["/temp/test-session_000.ts", "/temp/test-session_001.ts"]),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance

            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(return_value=[])
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.get("/api/stream/test-session/status?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_ready"] is True
        assert data["segment_count"] == 2
        assert data["status"] == "ready"

    async def test_status_not_ready(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
            patch("glob.glob", return_value=[]),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = False
            mock_path_cls.return_value = mock_path_instance

            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(return_value=[])
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.get("/api/stream/test-session/status?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_ready"] is False
        assert data["status"] == "initializing"

    async def test_status_transcoding(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
            patch("glob.glob", return_value=["/temp/test-session_000.ts"]),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance

            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(
                return_value=[{"status": "running", "task_id": "abc"}]
            )
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.get("/api/stream/test-session/status?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_transcoding"] is True
        assert data["status"] == "transcoding"

    async def test_status_computing_service_exception(self, client: AsyncClient):
        """When ComputingService raises, is_transcoding should be False."""
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
            patch("glob.glob", return_value=["/temp/test-session_000.ts"]),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
        ):
            mock_path_instance = MagicMock()
            mock_path_instance.exists.return_value = True
            mock_path_cls.return_value = mock_path_instance

            mock_cs.return_value.__aenter__ = AsyncMock(side_effect=Exception("docker down"))
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.get("/api/stream/test-session/status?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_transcoding"] is False


# ===========================================================================
# GET /{session_id}/trickplay
# ===========================================================================
class TestGetTrickplayManifest:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/test-session/trickplay")
        assert resp.status_code == 401

    async def test_lists_generated_sprites(self, client: AsyncClient):
        session_id = f"test-{uuid.uuid4().hex}"
        trickplay_dir = Path(f"/temp/{session_id}_trickplay")
        trickplay_dir.mkdir(parents=True, exist_ok=True)
        try:
            (trickplay_dir / "sprite_001.webp").write_bytes(b"second")
            (trickplay_dir / "sprite_000.webp").write_bytes(b"first")
            (trickplay_dir / "bad.webp").write_bytes(b"ignored")

            mock_service, _ = _mock_token_service(session_id=session_id)
            with patch(
                "streamarr.api.v1.stream.get_play_token_service",
                return_value=mock_service,
            ):
                resp = await client.get(
                    f"/api/stream/{session_id}/trickplay?token=tok"
                )

            assert resp.status_code == 200
            data = resp.json()
            assert data["ready"] is True
            assert data["sprite_count"] == 2
            assert data["columns"] == 10
            assert data["rows"] == 10
            assert [sprite["file_name"] for sprite in data["sprites"]] == [
                "sprite_000.webp",
                "sprite_001.webp",
            ]
            assert data["sprites"][0]["start_seconds"] == 0
            assert data["sprites"][0]["end_seconds"] == 1000
            assert data["sprites"][1]["start_seconds"] == 1000
            assert data["sprites"][0]["url"].endswith(
                f"/trickplay/sprite_000.webp?token=tok"
            )
        finally:
            shutil.rmtree(trickplay_dir, ignore_errors=True)

    async def test_no_sprites(self, client: AsyncClient):
        session_id = f"test-{uuid.uuid4().hex}"
        trickplay_dir = Path(f"/temp/{session_id}_trickplay")
        shutil.rmtree(trickplay_dir, ignore_errors=True)
        mock_service, _ = _mock_token_service(session_id=session_id)
        with patch(
            "streamarr.api.v1.stream.get_play_token_service",
            return_value=mock_service,
        ):
            resp = await client.get(f"/api/stream/{session_id}/trickplay?token=tok")

        assert resp.status_code == 200
        assert resp.json()["ready"] is False
        assert resp.json()["sprites"] == []


# ===========================================================================
# GET /{session_id}/check-position
# ===========================================================================
class TestCheckPosition:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get(
            "/api/stream/test-session/check-position?position=60&start_position=0"
        )
        assert resp.status_code == 401

    async def test_before_start(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get(
                "/api/stream/test-session/check-position?token=tok&position=5&start_position=10"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["reason"] == "before_start"

    async def test_available_segment(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = True
            mock_path_cls.return_value = mock_segment

            resp = await client.get(
                "/api/stream/test-session/check-position?token=tok&position=12&start_position=0&segment_duration=6"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is True
        assert data["segment_index"] == 2

    async def test_not_transcoded_no_db(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = False
            mock_path_cls.return_value = mock_segment

            resp = await client.get(
                "/api/stream/test-session/check-position?token=tok&position=60&start_position=0"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["reason"] == "not_transcoded"

    async def test_not_transcoded_transcoding_running(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = False
            mock_path_cls.return_value = mock_segment

            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(
                return_value=[{"status": "running", "task_id": "t1"}]
            )
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            # Need to pass db to trigger the db-based code path.
            # Since the endpoint has db: DatabaseSession = None, the route
            # will get a db session from the dependency override (not None).
            resp = await client.get(
                "/api/stream/test-session/check-position?token=tok&position=60&start_position=0"
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["available"] is False
        assert data["reason"] == "not_transcoded"


# ===========================================================================
# GET /file
# ===========================================================================
class TestStreamDirectFile:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/file")
        assert resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/file?token=bad")
        assert resp.status_code == 401

    async def test_success_mp4(self, client: AsyncClient, tmp_path):
        video_file = tmp_path / "test.mp4"
        video_file.write_bytes(b"\x00" * 100)

        mock_service, _ = _mock_token_service(file_path=str(video_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/file?token=tok")
        assert resp.status_code == 200
        assert "video/mp4" in resp.headers.get("content-type", "")
        assert resp.headers["accept-ranges"] == "bytes"
        mock_service.extend_ttl.assert_called_once()


# ===========================================================================
# GET /audio/file
# ===========================================================================
class TestStreamAudioFile:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/audio/file")
        assert resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/audio/file?token=bad")
        assert resp.status_code == 401

    async def test_no_file_path(self, client: AsyncClient):
        mock_service, mock_token = _mock_token_service()
        mock_token.file_path = None
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 404
        assert "No file path" in resp.json()["detail"]

    async def test_file_not_found(self, client: AsyncClient, tmp_path):
        missing_file = tmp_path / "missing.mp3"
        mock_service, mock_token = _mock_token_service(file_path=str(missing_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 404
        assert "File not found" in resp.json()["detail"]

    async def test_success_mp3(self, client: AsyncClient, tmp_path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"\x00" * 100)

        mock_service, _ = _mock_token_service(file_path=str(audio_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 200
        assert "audio/mpeg" in resp.headers.get("content-type", "")
        mock_service.extend_ttl.assert_called_once()

    async def test_success_ogg(self, client: AsyncClient, tmp_path):
        audio_file = tmp_path / "test.ogg"
        audio_file.write_bytes(b"\x00" * 100)

        mock_service, _ = _mock_token_service(file_path=str(audio_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 200
        assert "audio/ogg" in resp.headers.get("content-type", "")

    async def test_success_flac(self, client: AsyncClient, tmp_path):
        audio_file = tmp_path / "test.flac"
        audio_file.write_bytes(b"\x00" * 100)

        mock_service, _ = _mock_token_service(file_path=str(audio_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 200
        assert "audio/flac" in resp.headers.get("content-type", "")

    async def test_success_unknown_extension(self, client: AsyncClient, tmp_path):
        audio_file = tmp_path / "test.xyz"
        audio_file.write_bytes(b"\x00" * 100)

        mock_service, _ = _mock_token_service(file_path=str(audio_file))
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream._ALLOWED_MEDIA_ROOTS", (tmp_path,)),
        ):
            resp = await client.get("/api/stream/audio/file?token=tok")
        assert resp.status_code == 200
        assert "application/octet-stream" in resp.headers.get("content-type", "")


# ===========================================================================
# GET /{session_id}/{segment_file}
# ===========================================================================
class TestGetSegment:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.get("/api/stream/test-session/test-session_000.ts")
        assert resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get(
                "/api/stream/test-session/test-session_000.ts?token=bad"
            )
        assert resp.status_code == 401

    async def test_session_mismatch(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="other-session")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get(
                "/api/stream/test-session/test-session_000.ts?token=tok"
            )
        assert resp.status_code == 403

    async def test_path_traversal(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get(
                "/api/stream/test-session/../../etc/passwd.ts?token=tok"
            )
        # FastAPI may resolve the path differently, but the test exercises the route
        assert resp.status_code in (400, 404, 422)

    async def test_not_ts_file(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.get(
                "/api/stream/test-session/test-session.mp4?token=tok"
            )
        assert resp.status_code == 400
        assert "Invalid segment" in resp.json()["detail"]

    async def test_segment_not_found(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = False
            mock_path_cls.return_value = mock_segment

            resp = await client.get(
                "/api/stream/test-session/test-session_000.ts?token=tok"
            )
        assert resp.status_code == 404
        assert "Segment not found" in resp.json()["detail"]

    async def test_success(self, client: AsyncClient, tmp_path):
        import os

        # Create a real file for FileResponse to serve
        segment_file = tmp_path / "test-session_000.ts"
        segment_file.write_bytes(b"\x00" * 188)

        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = True
            # FileResponse needs a real path, so we use the tmp file
            mock_path_cls.return_value = segment_file

            resp = await client.get(
                "/api/stream/test-session/test-session_000.ts?token=tok"
            )
        assert resp.status_code == 200
        mock_service.extend_ttl.assert_called_once()

    async def test_token_from_header(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="test-session")
        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.Path") as mock_path_cls,
        ):
            mock_segment = MagicMock()
            mock_segment.exists.return_value = False
            mock_path_cls.return_value = mock_segment

            resp = await client.get(
                "/api/stream/test-session/test-session_000.ts",
                headers={"Authorization": "Bearer valid-token"},
            )
        # Should get 404 (segment not found) rather than 401, proving token was extracted
        assert resp.status_code == 404


# ===========================================================================
# DELETE /{session_id}
# ===========================================================================
class TestStopStream:
    async def test_no_token(self, client: AsyncClient):
        resp = await client.delete("/api/stream/test-session")
        assert resp.status_code == 401

    async def test_invalid_token(self, client: AsyncClient):
        mock_service = _mock_token_service_invalid()
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.delete("/api/stream/test-session?token=bad")
        assert resp.status_code == 401

    async def test_session_mismatch(self, client: AsyncClient):
        mock_service, _ = _mock_token_service(session_id="other")
        with patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service):
            resp = await client.delete("/api/stream/test-session?token=tok")
        assert resp.status_code == 403

    async def test_success_with_container(self, client: AsyncClient):
        mock_service, mock_token = _mock_token_service(session_id="test-session")
        mock_session_service = AsyncMock()
        mock_session = MagicMock()
        mock_session.content_id = "cid"
        mock_session.input_path = "/input.mkv"
        mock_session_service.get_session = AsyncMock(return_value=mock_session)
        mock_session_service.delete_session = AsyncMock()

        mock_cleanup = AsyncMock(return_value={"deleted_files": 3})

        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.get_transcoding_session_service", return_value=mock_session_service),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
            patch("streamarr.services.media.cleanup_stream_on_stop", mock_cleanup),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(
                return_value=[{"task_id": "task-1", "status": "running"}]
            )
            mock_ctx.terminate_task = AsyncMock()
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.delete("/api/stream/test-session?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["container_stopped"] is True
        assert data["session_id"] == "test-session"
        mock_service.delete_token.assert_called_once()

    async def test_success_without_container(self, client: AsyncClient):
        mock_service, mock_token = _mock_token_service(session_id="test-session")
        mock_session_service = AsyncMock()
        mock_session_service.get_session = AsyncMock(return_value=None)
        mock_session_service.delete_session = AsyncMock()

        mock_cleanup = AsyncMock(return_value={"deleted_files": 0})

        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.get_transcoding_session_service", return_value=mock_session_service),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
            patch("streamarr.services.media.cleanup_stream_on_stop", mock_cleanup),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(return_value=[])
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.delete("/api/stream/test-session?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["container_stopped"] is False

    async def test_success_fallback_to_play_token_info(self, client: AsyncClient):
        """When session is None, content_id/input_path come from play_token."""
        mock_service, mock_token = _mock_token_service(
            session_id="test-session", file_path="/fallback.mkv", content_id="fb-123"
        )
        mock_session_service = AsyncMock()
        mock_session_service.get_session = AsyncMock(return_value=None)

        mock_cleanup = AsyncMock(return_value={"deleted_files": 0})

        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.get_transcoding_session_service", return_value=mock_session_service),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
            patch("streamarr.services.media.cleanup_stream_on_stop", mock_cleanup),
        ):
            mock_ctx = AsyncMock()
            mock_ctx.get_tasks_by_label = AsyncMock(return_value=[])
            mock_cs.return_value.__aenter__ = AsyncMock(return_value=mock_ctx)
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.delete("/api/stream/test-session?token=tok")
        assert resp.status_code == 200
        # cleanup was called with the play_token fallback info
        mock_cleanup.assert_called_once()
        call_kwargs = mock_cleanup.call_args[1]
        assert call_kwargs["input_path"] == "/fallback.mkv"

    async def test_computing_service_exception(self, client: AsyncClient):
        """When ComputingService raises, stream should still stop successfully."""
        mock_service, mock_token = _mock_token_service(session_id="test-session")
        mock_session_service = AsyncMock()
        mock_session_service.get_session = AsyncMock(return_value=None)

        mock_cleanup = AsyncMock(return_value={"deleted_files": 0})

        with (
            patch("streamarr.api.v1.stream.get_play_token_service", return_value=mock_service),
            patch("streamarr.api.v1.stream.get_transcoding_session_service", return_value=mock_session_service),
            patch("streamarr.api.v1.stream.ComputingService") as mock_cs,
            patch("streamarr.services.media.cleanup_stream_on_stop", mock_cleanup),
        ):
            mock_cs.return_value.__aenter__ = AsyncMock(side_effect=Exception("docker error"))
            mock_cs.return_value.__aexit__ = AsyncMock(return_value=False)

            resp = await client.delete("/api/stream/test-session?token=tok")
        assert resp.status_code == 200
        data = resp.json()
        assert data["container_stopped"] is False
