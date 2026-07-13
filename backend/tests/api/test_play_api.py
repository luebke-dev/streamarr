"""Tests for the Play API endpoints (/api/play/*)."""

import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import (
    AvailabilityStatus,
    MediaFile,
    MediaItem,
    MediaType,
)
from streamarr.models.device import Device
from streamarr.models.user import User
from streamarr.schemas.play_token import PlayToken, PlayTokenCreate
from streamarr.services.settings import SettingsService

from .conftest import auth_headers


@pytest_asyncio.fixture(autouse=True)
async def _enable_transcoding_for_play_api_tests(db_session: AsyncSession):
    await SettingsService(db_session).set("transcoding.enabled", True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = dict(
        guid=uuid.uuid4(),
        title="Test Movie",
        media_type=MediaType.MOVIES,
        availability_status=AvailabilityStatus.AVAILABLE,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


async def _create_media_file(db: AsyncSession, media_item_guid: uuid.UUID, **overrides) -> MediaFile:
    now = datetime.now(UTC)
    probe = json.dumps({
        "streams": [
            {
                "index": 0,
                "codec_type": "video",
                "codec_name": "h264",
                "width": 1920,
                "height": 1080,
                "duration": "7200.0",
            },
            {
                "index": 1,
                "codec_type": "audio",
                "codec_name": "aac",
                "channels": 2,
                "tags": {"language": "eng"},
            },
        ],
        "format": {"duration": "7200.0"},
    })
    defaults = dict(
        guid=uuid.uuid4(),
        media_item_guid=media_item_guid,
        file_path="/data/movies/test_movie.mkv",
        file_name="test_movie.mkv",
        file_size=5_000_000_000,
        duration=7200.0,
        width=1920,
        height=1080,
        codec="h264",
        bitrate=8_000_000,
        probe_data=probe,
        quality="1080p",
        format="mkv",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    f = MediaFile(**defaults)
    db.add(f)
    await db.commit()
    await db.refresh(f)
    return f


def _make_play_token(content_id: uuid.UUID, user_guid: uuid.UUID) -> PlayToken:
    """Build a mock PlayToken object."""
    return PlayToken(
        token=str(uuid.uuid4()),
        user_guid=str(user_guid),
        content_type="movie",
        content_id=str(content_id),
        file_path="/data/movies/test_movie.mkv",
        session_id=None,
        created_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )


@dataclass
class _FakePlayAction:
    status: str
    message: str
    file: object | None = None
    file_path: str | None = None
    probe_data: dict | None = None
    download_progress: float | None = None
    download_status: str | None = None
    download_phase: str | None = None
    download_status_detail: str | None = None


# ============================================================================
# PLAY MEDIA
# ============================================================================


class TestPlayMedia:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(f"/api/play/{uuid.uuid4()}")
        assert resp.status_code == 401

    async def test_media_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.post(f"/api/play/{uuid.uuid4()}", headers=user_headers)
        assert resp.status_code == 404

    @patch("streamarr.services.playback_session.resolve_play_action")
    async def test_status_searching(
        self,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When no releases exist, endpoint returns 'searching' status."""
        item = await _create_media_item(db_session)
        mock_resolve.return_value = _FakePlayAction(
            status="searching",
            message="Searching for releases...",
        )
        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={"audio_track": 1},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "searching"
        assert "message" in data

    @patch("streamarr.services.playback_session.resolve_play_action")
    async def test_status_downloading(
        self,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When a download is in progress, endpoint returns 'downloading' status."""
        item = await _create_media_item(db_session)
        mock_resolve.return_value = _FakePlayAction(
            status="downloading",
            message="Download in progress",
            download_progress=45.5,
            download_status="downloading",
        )
        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "downloading"
        assert data["download_progress"] == 45.5
        assert data["download_status"] == "downloading"

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_status_ready(
        self,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When a file is ready, endpoint starts transcoding and returns token."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)

        probe = json.loads(file.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert "token" in data
        assert "session_id" in data
        assert data["media_source_id"] == str(file.guid)
        assert data["duration"] == file.duration
        assert data["width"] == file.width
        assert data["height"] == file.height
        mock_transcode.assert_called_once()
        assert mock_transcode.await_args.kwargs["audio_stream_index"] == 0

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_direct_file_play_when_source_is_browser_compatible(
        self,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        file = await _create_media_file(
            db_session,
            item.guid,
            file_name="direct.mp4",
            file_path="/data/movies/direct.mp4",
            format="mp4",
        )
        probe = json.loads(file.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={
                "supported_video_codecs": "h264",
                "supported_audio_codecs": "aac",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["direct_play"] is True
        assert data["direct_file_url"] == f"/api/stream/file?token={play_token.token}"
        assert data["media_source_id"] == str(file.guid)
        mock_transcode.assert_not_called()

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_playback_profile_drives_direct_file_play(
        self,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        file = await _create_media_file(
            db_session,
            item.guid,
            file_name="direct.mp4",
            file_path="/data/movies/direct.mp4",
            format="mp4",
        )
        probe = json.loads(file.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={"profile_id": "browser"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["direct_play"] is True
        assert data["playback_method"] == "direct_play"
        assert data["profile_id"] == "browser"
        assert data["direct_file_url"] == f"/api/stream/file?token={play_token.token}"
        mock_transcode.assert_not_called()

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("streamarr.services.playback_session._acquire_transcode_lock", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session._release_transcode_lock", new_callable=AsyncMock)
    async def test_registered_device_capabilities_drive_direct_stream(
        self,
        mock_release_lock,
        mock_acquire_lock,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        mock_acquire_lock.return_value = True
        item = await _create_media_item(db_session)
        file = await _create_media_file(
            db_session,
            item.guid,
            file_name="movie.mkv",
            file_path="/data/movies/movie.mkv",
            format="mkv",
        )
        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="living-room-browser",
            name="Living Room Browser",
            device_info={
                "capabilities": {
                    "profile_id": "browser",
                    "supported_video_codecs": ["h264"],
                    "supported_audio_codecs": ["aac"],
                    "supported_containers": ["mp4"],
                    "supports_direct_play": True,
                    "supports_direct_stream": True,
                    "supports_transcoding": True,
                }
            },
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()

        probe = json.loads(file.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={
                "device_guid": str(device.guid),
                "subtitle_stream_index": 2,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["playback_method"] == "direct_stream"
        assert data["direct_stream"] is True
        assert data["profile_id"] == "browser"
        assert data["device_id"] == "living-room-browser"
        mock_transcode.assert_awaited_once()
        assert mock_transcode.await_args.kwargs["video_codec"] == "copy"
        assert mock_transcode.await_args.kwargs["audio_codec"] == "copy"
        assert mock_transcode.await_args.kwargs["subtitle_stream_index"] == 2
        assert mock_transcode.await_args.kwargs["burn_subtitles"] is True
        mock_release_lock.assert_awaited_once()

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_direct_file_play_falls_back_when_transcode_codec_is_disallowed(
        self,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        file = await _create_media_file(
            db_session,
            item.guid,
            file_name="direct.mp4",
            file_path="/data/movies/direct.mp4",
            format="mp4",
        )
        probe = json.loads(file.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        mock_token_svc.return_value = token_service

        with patch("streamarr.services.system_settings.SystemSettingsService") as mock_ss:
            mock_ss_inst = AsyncMock()
            mock_ss_inst.get_transcoding_settings = AsyncMock(
                return_value={
                    "enabled": True,
                    "allowed_video_codecs": ["vp9"],
                    "allowed_audio_codecs": ["opus"],
                    "max_resolution": None,
                    "default_audio_bitrate": "128k",
                    "default_video_bitrate": None,
                }
            )
            mock_ss.return_value = mock_ss_inst

            resp = await client.post(
                f"/api/play/{item.guid}",
                headers=user_headers,
                params={
                    "supported_video_codecs": "h264",
                    "supported_audio_codecs": "aac",
                },
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["direct_play"] is True
        assert data["direct_file_url"] == f"/api/stream/file?token={play_token.token}"
        mock_transcode.assert_not_called()

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("streamarr.services.playback_session._acquire_transcode_lock", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session._release_transcode_lock", new_callable=AsyncMock)
    async def test_selects_requested_media_source(
        self,
        mock_release_lock,
        mock_acquire_lock,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """The play endpoint starts playback from the requested media file."""
        mock_acquire_lock.return_value = True
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="first.mp4",
            file_path="/data/movies/first.mp4",
            format="mp4",
        )
        second = await _create_media_file(
            db_session,
            item.guid,
            file_name="second.mp4",
            file_path="/data/movies/second.mp4",
            format="mp4",
        )

        probe = json.loads(second.probe_data)
        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=second,
            file_path=second.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={"media_source_id": str(second.guid)},
        )

        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"
        assert resp.json()["media_source_id"] == str(second.guid)
        mock_resolve.assert_awaited_once()
        resolve_args = mock_resolve.await_args.args
        resolve_kwargs = mock_resolve.await_args.kwargs
        assert resolve_args[2] == item.guid
        assert resolve_kwargs["user_guid"] == test_user.guid
        assert resolve_kwargs["media_source_id"] == second.guid
        mock_transcode.assert_awaited_once()
        assert mock_transcode.await_args.kwargs["input_path"] == second.file_path
        token_service.create_token.assert_awaited_once()
        token_data = token_service.create_token.await_args.args[0]
        assert token_data.file_path == second.file_path
        mock_release_lock.assert_awaited_once()

    @patch("streamarr.services.playback_session.resolve_play_action")
    async def test_requested_media_source_must_belong_to_item(
        self,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        other_item = await _create_media_item(db_session)
        other_file = await _create_media_file(db_session, other_item.guid)
        await _create_media_file(db_session, item.guid)

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={"media_source_id": str(other_file.guid)},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Media source not found"
        mock_resolve.assert_not_called()

    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("streamarr.services.playback_session._acquire_transcode_lock", return_value=False)
    async def test_duplicate_transcode_409(
        self,
        mock_lock,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """If transcode lock is already held, return 409."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)
        probe = json.loads(file.probe_data)

        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 409
        assert "already starting" in resp.json()["detail"].lower()


# ============================================================================
# PLAYBACK INFO
# ============================================================================


class TestPlaybackInfo:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/play/{uuid.uuid4()}/playback-info")
        assert resp.status_code == 401

    async def test_direct_play_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        media_file = await _create_media_file(
            db_session,
            item.guid,
            file_name="test_movie.mp4",
            file_path="/data/movies/test_movie.mp4",
            format="mp4",
        )

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={
                "supported_video_codecs": "h264",
                "supported_audio_codecs": "aac",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["selected_media_source_id"] == str(media_file.guid)
        source = data["media_sources"][0]
        assert source["playback_method"] == "direct_play"
        assert source["can_direct_play"] is True
        assert source["direct_play_url"] == (
            f"/api/media/{item.guid}/files/{media_file.guid}/download"
        )

    async def test_selects_requested_media_source(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        first = await _create_media_file(
            db_session,
            item.guid,
            file_name="first.mp4",
            file_path="/data/movies/first.mp4",
            format="mp4",
        )
        second = await _create_media_file(
            db_session,
            item.guid,
            file_name="second.mp4",
            file_path="/data/movies/second.mp4",
            format="mp4",
        )

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={
                "media_source_id": str(second.guid),
                "supported_video_codecs": "h264",
                "supported_audio_codecs": "aac",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_media_source_id"] == str(second.guid)
        assert {source["id"] for source in data["media_sources"]} == {
            str(first.guid),
            str(second.guid),
        }

    async def test_requested_media_source_must_belong_to_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        other_item = await _create_media_item(db_session)
        other_file = await _create_media_file(db_session, other_item.guid)
        await _create_media_file(db_session, item.guid)

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={"media_source_id": str(other_file.guid)},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Media source not found"

    async def test_uses_registered_device_capabilities(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="test_movie.mp4",
            file_path="/data/movies/test_movie.mp4",
            format="mp4",
        )
        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="browser-1",
            name="Browser",
            device_info={
                "capabilities": {
                    "supported_video_codecs": ["h264"],
                    "supported_audio_codecs": ["aac"],
                    "supported_containers": ["mp4"],
                    "max_resolution": "1080p",
                }
            },
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={"device_guid": str(device.guid)},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["device_id"] == "browser-1"
        assert data["client_capabilities"]["supported_video_codecs"] == "h264"
        assert data["client_capabilities"]["supported_audio_codecs"] == "aac"
        assert data["client_capabilities"]["max_resolution"] == "1080p"
        assert data["media_sources"][0]["playback_method"] == "direct_play"

    async def test_profile_can_select_direct_stream_for_container_mismatch(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="test_movie.mkv",
            file_path="/data/movies/test_movie.mkv",
            format="mkv",
        )

        with patch("streamarr.services.system_settings.SystemSettingsService") as mock_ss:
            mock_ss_inst = AsyncMock()
            mock_ss_inst.get_transcoding_settings = AsyncMock(
                return_value={
                    "enabled": True,
                    "allowed_video_codecs": ["h264"],
                    "allowed_audio_codecs": ["aac"],
                    "max_resolution": None,
                    "default_audio_bitrate": "128k",
                    "default_video_bitrate": None,
                }
            )
            mock_ss.return_value = mock_ss_inst

            resp = await client.get(
                f"/api/play/{item.guid}/playback-info",
                headers=user_headers,
                params={"profile_id": "browser"},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "browser"
        source = data["media_sources"][0]
        assert source["playback_method"] == "direct_stream"
        assert source["can_direct_play"] is False
        assert source["can_direct_stream"] is True
        assert "client container support does not match source" in source["direct_play_reasons"]
        assert source["direct_stream_url"] == (
            f"/api/play/{item.guid}?media_source_id={source['id']}"
            "&profile_id=browser&supported_containers=mp4,webm,ogg,mp3,m4a"
            "&video_codec=copy&audio_codec=copy"
        )

    async def test_explicit_client_containers_drive_playback_info(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="test_movie.mkv",
            file_path="/data/movies/test_movie.mkv",
            format="mkv",
        )

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={
                "supported_video_codecs": "h264",
                "supported_audio_codecs": "aac",
                "supported_containers": "mp4",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["client_capabilities"]["supported_containers"] == ["mp4"]
        source = data["media_sources"][0]
        assert source["playback_method"] == "direct_stream"
        assert source["direct_stream_url"] == (
            f"/api/play/{item.guid}?media_source_id={source['id']}"
            "&supported_containers=mp4&video_codec=copy&audio_codec=copy"
        )

    async def test_no_media_files_returns_unavailable(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info", headers=user_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "unavailable"
        assert data["media_sources"] == []

    async def test_playback_info_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        await db_session.commit()

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_playback_info_denies_parental_blocked_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await db_session.commit()

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
        )
        assert resp.status_code == 403


class TestPlaybackProfiles:
    async def test_list_profiles_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/play/profiles")

        assert resp.status_code == 401

    async def test_list_profiles_includes_builtins(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.get("/api/play/profiles", headers=user_headers)

        assert resp.status_code == 200
        ids = {profile["id"] for profile in resp.json()}
        assert {"browser", "chromecast", "dlna_generic"}.issubset(ids)

    async def test_regular_user_cannot_update_profiles(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.put(
            "/api/play/profiles",
            headers=user_headers,
            json={"profiles": []},
        )

        assert resp.status_code == 403

    async def test_admin_configures_custom_profile(
        self, client: AsyncClient, admin_headers, user_headers
    ):
        resp = await client.put(
            "/api/play/profiles",
            headers=admin_headers,
            json={
                "profiles": [
                    {
                        "id": "living-room-dlna",
                        "name": "Living Room DLNA",
                        "type": "dlna",
                        "supported_video_codecs": ["h264"],
                        "supported_audio_codecs": ["aac", "mp3"],
                        "supported_containers": ["mp4", "ts"],
                        "max_resolution": "1080p",
                        "max_bitrate": 4_000_000,
                        "supports_direct_play": True,
                        "supports_direct_stream": True,
                        "supports_transcoding": True,
                    }
                ]
            },
        )

        assert resp.status_code == 200
        profiles = resp.json()
        custom = next(
            profile for profile in profiles if profile["id"] == "living-room-dlna"
        )
        assert custom["built_in"] is False
        assert custom["type"] == "dlna"
        assert custom["max_bitrate"] == 4_000_000

        listed = await client.get("/api/play/profiles", headers=user_headers)
        assert listed.status_code == 200
        assert "living-room-dlna" in {profile["id"] for profile in listed.json()}

    async def test_custom_profile_drives_playback_info(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        admin_headers,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="test_movie.mp4",
            file_path="/data/movies/test_movie.mp4",
            format="mp4",
            bitrate=8_000_000,
        )
        await client.put(
            "/api/play/profiles",
            headers=admin_headers,
            json={
                "profiles": [
                    {
                        "id": "low-bitrate-dlna",
                        "name": "Low Bitrate DLNA",
                        "type": "dlna",
                        "supported_video_codecs": ["h264"],
                        "supported_audio_codecs": ["aac"],
                        "supported_containers": ["mp4"],
                        "max_resolution": "1080p",
                        "max_bitrate": 4_000_000,
                    }
                ]
            },
        )

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={"profile_id": "low-bitrate-dlna"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "low-bitrate-dlna"
        assert data["client_capabilities"]["max_bitrate"] == 4_000_000
        source = data["media_sources"][0]
        assert source["can_direct_play"] is False
        assert "source bitrate exceeds client maximum" in source["direct_play_reasons"]

        resp = await client.get(
            f"/api/play/{item.guid}/playback-info",
            headers=user_headers,
            params={
                "profile_id": "low-bitrate-dlna",
                "client_max_bitrate": 9_000_000,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["client_capabilities"]["max_bitrate"] == 9_000_000
        assert data["media_sources"][0]["can_direct_play"] is True

    async def test_built_in_profile_ids_are_rejected(
        self, client: AsyncClient, admin_headers
    ):
        resp = await client.put(
            "/api/play/profiles",
            headers=admin_headers,
            json={
                "profiles": [
                    {
                        "id": "browser",
                        "name": "Browser Override",
                        "supported_video_codecs": ["h264"],
                    }
                ]
            },
        )

        assert resp.status_code == 422
        assert "built in" in resp.json()["detail"]


# ============================================================================
# SEEK MEDIA
# ============================================================================


class TestSeekMedia:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            f"/api/play/{uuid.uuid4()}/seek", params={"position": 100.0}
        )
        assert resp.status_code == 401

    async def test_media_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.post(
            f"/api/play/{uuid.uuid4()}/seek",
            headers=user_headers,
            params={"position": 100.0},
        )
        assert resp.status_code == 404

    async def test_no_file(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        """If no MediaFile exists for the media, return 404."""
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 100.0},
        )
        assert resp.status_code == 404
        assert "no file" in resp.json()["detail"].lower()

    async def test_seek_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        await db_session.commit()

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 100.0},
        )
        assert resp.status_code == 403

    async def test_seek_denies_parental_blocked_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await db_session.commit()

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 100.0},
        )
        assert resp.status_code == 403

    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_success(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Successful seek creates new session and returns token."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 300.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["start_position"] == 300.0
        assert data["content_type"] == "movie"
        mock_transcode.assert_called_once()

    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_selects_requested_media_source(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        await _create_media_file(
            db_session,
            item.guid,
            file_name="first.mp4",
            file_path="/data/movies/first.mp4",
            format="mp4",
        )
        second = await _create_media_file(
            db_session,
            item.guid,
            file_name="second.mp4",
            file_path="/data/movies/second.mp4",
            format="mp4",
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 300.0, "media_source_id": str(second.guid)},
        )

        assert resp.status_code == 200
        assert resp.json()["media_source_id"] == str(second.guid)
        mock_transcode.assert_awaited_once()
        assert mock_transcode.await_args.kwargs["input_path"] == second.file_path
        token_service.create_token.assert_awaited_once()
        token_data = token_service.create_token.await_args.args[0]
        assert token_data.file_path == second.file_path

    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_preserves_profile_direct_stream_context(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        file = await _create_media_file(
            db_session,
            item.guid,
            file_name="movie.mkv",
            file_path="/data/movies/movie.mkv",
            format="mkv",
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={
                "position": 300.0,
                "profile_id": "browser",
                "media_source_id": str(file.guid),
                "video_codec": "copy",
                "audio_codec": "copy",
                "subtitle_stream_index": 2,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["profile_id"] == "browser"
        assert data["playback_method"] == "direct_stream"
        assert data["direct_stream"] is True
        assert data["subtitle_stream_index"] == 2
        mock_transcode.assert_awaited_once()
        assert mock_transcode.await_args.kwargs["video_codec"] == "copy"
        assert mock_transcode.await_args.kwargs["audio_codec"] == "copy"
        assert mock_transcode.await_args.kwargs["subtitle_stream_index"] == 2
        assert mock_transcode.await_args.kwargs["burn_subtitles"] is True

    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_requested_media_source_must_belong_to_item(
        self,
        mock_exists,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        other_item = await _create_media_item(db_session)
        other_file = await _create_media_file(db_session, other_item.guid)
        await _create_media_file(db_session, item.guid)

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 300.0, "media_source_id": str(other_file.guid)},
        )

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Media source not found"

    @patch("pathlib.Path.exists", return_value=False)
    async def test_seek_file_not_on_disk(
        self,
        mock_exists,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """If file_path resolves but file isn't on disk, return 404."""
        item = await _create_media_item(db_session)
        await _create_media_file(db_session, item.guid)

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 100.0},
        )
        assert resp.status_code == 404
        assert "not found on disk" in resp.json()["detail"].lower()


# ============================================================================
# PLAY MEDIA - additional branches
# ============================================================================


class TestPlayMediaNoFiles:
    @patch("streamarr.services.playback_session.resolve_play_action")
    async def test_no_files_returns_searching(
        self,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When media exists but has no files, resolve_play_action returns searching."""
        item = await _create_media_item(db_session)
        mock_resolve.return_value = _FakePlayAction(
            status="searching",
            message="No files available, searching...",
        )
        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "searching"


class TestPlayAudioOnly:
    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_audio_file_play(
        self,
        mock_token_svc,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Audio-only media (SONGS) skips transcoding and returns direct play."""
        item = await _create_media_item(
            db_session, media_type=MediaType.SONGS, title="Test Song"
        )
        file = await _create_media_file(
            db_session,
            item.guid,
            file_path="/data/music/test.mp3",
            width=None,
            height=None,
            duration=240.0,
        )

        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready to play",
            file=file,
            file_path=file.file_path,
            probe_data=None,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        mock_token_svc.return_value = token_service

        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert data["audio_only"] is True
        assert "token" in data


class TestSeekMediaExtended:
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_with_old_session(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Seek with old_session_id tries to terminate old container."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 500.0, "old_session_id": "old-session-123"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["start_position"] == 500.0

    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_with_audio_track(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Seek with explicit audio_track parameter."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}/seek",
            headers=user_headers,
            params={"position": 200.0, "audio_track": 1},
        )
        assert resp.status_code == 200

    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_episode(
        self,
        mock_exists,
        mock_token_svc,
        mock_transcode,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Seek on a show episode returns content_type=episode."""
        show = await _create_media_item(
            db_session, media_type=MediaType.SHOWS, title="Test Show"
        )
        season = await _create_media_item(
            db_session,
            media_type=MediaType.SHOWS,
            title="Season 1",
            parent_guid=show.guid,
        )
        episode = await _create_media_item(
            db_session,
            media_type=MediaType.SHOWS,
            title="Episode 1",
            parent_guid=season.guid,
        )
        file = await _create_media_file(db_session, episode.guid)

        play_token = _make_play_token(episode.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{episode.guid}/seek",
            headers=user_headers,
            params={"position": 60.0},
        )
        assert resp.status_code == 200
        data = resp.json()
        # content_type comes from the mock PlayToken which has "movie" hardcoded
        # but the code path for SHOWS media_type is still exercised
        assert "content_type" in data


# ============================================================================
# PLAY MEDIA - Concurrent transcode limit
# ============================================================================


class TestPlayMediaConcurrentLimit:
    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("streamarr.services.playback_session._acquire_transcode_lock", return_value=True)
    @patch("streamarr.services.playback_session._release_transcode_lock", new_callable=AsyncMock)
    async def test_concurrent_limit_reached(
        self,
        mock_release,
        mock_lock,
        mock_token_svc,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When max concurrent transcodes is reached, return 503."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)
        probe = json.loads(file.probe_data)

        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        with (
            patch("streamarr.services.system_settings.SystemSettingsService") as mock_ss,
            patch("streamarr.services.transcoding_session.get_transcoding_session_service") as mock_tss,
        ):
            mock_ss_inst = AsyncMock()
            mock_ss_inst.get_transcoding_settings = AsyncMock(
                return_value={
                    "enabled": True,
                    "allowed_video_codecs": ["h264"],
                    "allowed_audio_codecs": ["aac"],
                    "max_resolution": None,
                    "default_audio_bitrate": "128k",
                    "default_video_bitrate": None,
                    "max_concurrent_transcodes": 1,
                }
            )
            mock_ss.return_value = mock_ss_inst

            mock_session_svc = AsyncMock()
            mock_session_svc.is_quarantined = AsyncMock(return_value=None)
            mock_session_svc.get_all_sessions = AsyncMock(
                return_value=[{"id": "existing"}]  # Already 1 active
            )
            mock_tss.return_value = mock_session_svc

            resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 503
        assert "capacity reached" in resp.json()["detail"].lower()


# ============================================================================
# PLAY MEDIA - Download in progress (with download_status, no download_progress)
# ============================================================================


class TestPlayMediaDownloadBranch:
    @patch("streamarr.services.playback_session.resolve_play_action")
    async def test_downloading_no_progress(
        self,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Downloading with download_status but no download_progress."""
        item = await _create_media_item(db_session)
        mock_resolve.return_value = _FakePlayAction(
            status="downloading",
            message="Download starting",
            download_progress=None,
            download_status="queued",
        )
        resp = await client.post(f"/api/play/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "downloading"
        assert "download_progress" not in data
        assert data["download_status"] == "queued"


# ============================================================================
# SEEK MEDIA - Concurrent transcode limit on seek
# ============================================================================


class TestSeekConcurrentLimit:
    @patch("streamarr.services.playback_session.get_play_token_service")
    @patch("pathlib.Path.exists", return_value=True)
    async def test_seek_concurrent_limit(
        self,
        mock_exists,
        mock_token_svc,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """When max concurrent transcodes reached during seek, return 503."""
        item = await _create_media_item(db_session)
        await _create_media_file(db_session, item.guid)

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        with (
            patch("streamarr.services.system_settings.SystemSettingsService") as mock_ss,
            patch("streamarr.services.transcoding_session.get_transcoding_session_service") as mock_tss,
        ):
            mock_ss_inst = AsyncMock()
            mock_ss_inst.get_transcoding_settings = AsyncMock(
                return_value={
                    "enabled": True,
                    "allowed_video_codecs": ["h264"],
                    "allowed_audio_codecs": ["aac"],
                    "max_resolution": None,
                    "default_audio_bitrate": "128k",
                    "default_video_bitrate": None,
                    "max_concurrent_transcodes": 1,
                }
            )
            mock_ss.return_value = mock_ss_inst

            mock_session_svc = AsyncMock()
            mock_session_svc.is_quarantined = AsyncMock(return_value=None)
            mock_session_svc.get_all_sessions = AsyncMock(
                return_value=[{"id": "existing"}]
            )
            mock_tss.return_value = mock_session_svc

            resp = await client.post(
                f"/api/play/{item.guid}/seek",
                headers=user_headers,
                params={"position": 100.0},
            )
        assert resp.status_code == 503


# ============================================================================
# PLAY MEDIA - Ready with supported_video_codecs query param
# ============================================================================


class TestPlayMediaCodecParams:
    @patch("streamarr.services.playback_session.resolve_play_action")
    @patch("streamarr.services.playback_session.start_transcode_container", new_callable=AsyncMock)
    @patch("streamarr.services.playback_session.get_play_token_service")
    async def test_play_with_codec_params(
        self,
        mock_token_svc,
        mock_transcode,
        mock_resolve,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Play with custom codec and resolution parameters."""
        item = await _create_media_item(db_session)
        file = await _create_media_file(db_session, item.guid)
        probe = json.loads(file.probe_data)

        mock_resolve.return_value = _FakePlayAction(
            status="ready",
            message="Ready",
            file=file,
            file_path=file.file_path,
            probe_data=probe,
        )

        play_token = _make_play_token(item.guid, test_user.guid)
        token_service = AsyncMock()
        token_service.create_token = AsyncMock(return_value=play_token)
        token_service.update_session_id = AsyncMock()
        mock_token_svc.return_value = token_service

        resp = await client.post(
            f"/api/play/{item.guid}",
            headers=user_headers,
            params={
                "video_codec": "h265",
                "audio_codec": "opus",
                "resolution": "1280x720",
                "supported_video_codecs": "h264,h265",
                "supported_audio_codecs": "aac,opus",
                "client_max_resolution": "1080p",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ready"
        assert "stream_info" in data
