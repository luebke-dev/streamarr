"""Tests for TranscodingSessionService (Redis-backed session management)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import fakeredis.aioredis
import pytest
import pytest_asyncio

from pyrate.schemas.transcoding import TranscodingSession, TranscodingSessionCreate
from pyrate.services.transcoding_session import TranscodingSessionService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _create_session_data(
    session_id: str = "sess_001",
    user_guid: str | None = None,
    content_type: str = "movie",
) -> TranscodingSessionCreate:
    return TranscodingSessionCreate(
        session_id=session_id,
        user_guid=uuid.uuid4() if user_guid is None else uuid.UUID(user_guid),
        user_name="Test User",
        content_type=content_type,
        content_id=uuid.uuid4(),
        content_title="Test Movie",
        video_codec="h264",
        audio_codec="aac",
    )


@pytest_asyncio.fixture
async def service() -> TranscodingSessionService:
    svc = TranscodingSessionService()
    svc._redis = fakeredis.aioredis.FakeRedis(decode_responses=True)
    return svc


# ---------------------------------------------------------------------------
# create / get
# ---------------------------------------------------------------------------

class TestSessionCRUD:
    @pytest.mark.asyncio
    async def test_create_session(self, service: TranscodingSessionService):
        data = _create_session_data()
        session = await service.create_session(data)

        assert session.session_id == "sess_001"
        assert session.content_type == "movie"
        assert session.is_active is True
        assert session.status == "active"

    @pytest.mark.asyncio
    async def test_get_session(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        result = await service.get_session("sess_001")
        assert result is not None
        assert result.session_id == "sess_001"

    @pytest.mark.asyncio
    async def test_get_session_not_found(self, service: TranscodingSessionService):
        result = await service.get_session("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_session(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        result = await service.delete_session("sess_001")
        assert result is True

        session = await service.get_session("sess_001")
        assert session is None


# ---------------------------------------------------------------------------
# Update operations
# ---------------------------------------------------------------------------

class TestSessionUpdates:
    @pytest.mark.asyncio
    async def test_update_session_access(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        result = await service.update_session_access("sess_001")
        assert result is True

    @pytest.mark.asyncio
    async def test_update_session_access_not_found(self, service: TranscodingSessionService):
        result = await service.update_session_access("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_update_session_container(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        result = await service.update_session_container("sess_001", "container_abc")
        assert result is True

        session = await service.get_session("sess_001")
        assert session.container_id == "container_abc"

    @pytest.mark.asyncio
    async def test_update_session_container_not_found(self, service: TranscodingSessionService):
        result = await service.update_session_container("nonexistent", "cont")
        assert result is False


# ---------------------------------------------------------------------------
# State transitions
# ---------------------------------------------------------------------------

class TestSessionStates:
    @pytest.mark.asyncio
    async def test_increment_retry(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        count = await service.increment_retry("sess_001")
        assert count == 1

        count = await service.increment_retry("sess_001")
        assert count == 2

        session = await service.get_session("sess_001")
        assert session.status == "restarting"
        assert session.retry_count == 2

    @pytest.mark.asyncio
    async def test_increment_retry_not_found(self, service: TranscodingSessionService):
        count = await service.increment_retry("nonexistent")
        assert count == -1

    @pytest.mark.asyncio
    async def test_mark_failed(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)

        result = await service.mark_failed("sess_001")
        assert result is True

        session = await service.get_session("sess_001")
        assert session.status == "failed"
        assert session.is_active is False

    @pytest.mark.asyncio
    async def test_mark_failed_not_found(self, service: TranscodingSessionService):
        result = await service.mark_failed("nonexistent")
        assert result is False

    @pytest.mark.asyncio
    async def test_mark_active(self, service: TranscodingSessionService):
        data = _create_session_data()
        await service.create_session(data)
        await service.mark_failed("sess_001")

        result = await service.mark_active("sess_001", container_id="new_container")
        assert result is True

        session = await service.get_session("sess_001")
        assert session.status == "active"
        assert session.is_active is True
        assert session.container_id == "new_container"


# ---------------------------------------------------------------------------
# Listing sessions
# ---------------------------------------------------------------------------

class TestSessionListing:
    @pytest.mark.asyncio
    async def test_get_all_sessions(self, service: TranscodingSessionService):
        await service.create_session(_create_session_data("sess_001"))
        await service.create_session(_create_session_data("sess_002"))

        sessions = await service.get_all_sessions()
        assert len(sessions) == 2

    @pytest.mark.asyncio
    async def test_get_all_sessions_active_only(self, service: TranscodingSessionService):
        await service.create_session(_create_session_data("sess_001"))
        await service.create_session(_create_session_data("sess_002"))
        await service.mark_failed("sess_002")

        active = await service.get_all_sessions(active_only=True)
        assert len(active) == 1
        assert active[0].session_id == "sess_001"

    @pytest.mark.asyncio
    async def test_get_user_sessions(self, service: TranscodingSessionService):
        user_guid = str(uuid.uuid4())
        data = _create_session_data("sess_001", user_guid=user_guid)
        await service.create_session(data)
        await service.create_session(_create_session_data("sess_002"))

        user_sessions = await service.get_user_sessions(user_guid)
        assert len(user_sessions) == 1

    @pytest.mark.asyncio
    async def test_terminate_session(self, service: TranscodingSessionService):
        data = _create_session_data("sess_001")
        await service.create_session(data)

        # Terminate without a container (no Docker call)
        result = await service.terminate_session("sess_001")
        assert result["success"] is True

        session = await service.get_session("sess_001")
        assert session is None

    @pytest.mark.asyncio
    async def test_terminate_session_not_found(self, service: TranscodingSessionService):
        result = await service.terminate_session("nonexistent")
        assert result["success"] is False


class TestSessionLogs:
    @pytest.mark.asyncio
    async def test_get_session_logs_kubernetes(self, service: TranscodingSessionService):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="kubernetes",
            job_name="ffmpeg-job",
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        mock_k8s = MagicMock()
        mock_k8s.get_job_logs = AsyncMock(return_value="k8s logs")
        mock_module = MagicMock()
        mock_module.get_kubernetes_transcoding_service = MagicMock(return_value=mock_k8s)

        with patch.dict(
            "sys.modules",
            {"pyrate.services.kubernetes": mock_module},
        ):
            logs = await service.get_session_logs(session, tail_lines=25)

        assert logs == "k8s logs"
        mock_k8s.get_job_logs.assert_awaited_once_with("ffmpeg-job", tail_lines=25)

    @pytest.mark.asyncio
    async def test_get_session_logs_docker_by_label(self, service: TranscodingSessionService):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="docker",
            container_id="container-1",
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        mock_container = AsyncMock()
        mock_container.log = AsyncMock(return_value=["line1\n", "line2\n"])
        mock_docker = AsyncMock()
        mock_docker.containers.list = AsyncMock(return_value=[mock_container])
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            logs = await service.get_session_logs(session, tail_lines=10)

        assert logs == "line1\nline2\n"
        mock_container.log.assert_awaited_once_with(stdout=True, stderr=True, tail="10")

    @pytest.mark.asyncio
    async def test_get_session_logs_docker_missing_container(
        self,
        service: TranscodingSessionService,
    ):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="docker",
            container_id=None,
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        mock_docker = AsyncMock()
        mock_docker.containers.list = AsyncMock(return_value=[])
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            logs = await service.get_session_logs(session)

        assert logs == "No container found for this session"


class TestSessionRuntimeStatus:
    @pytest.mark.asyncio
    async def test_get_session_runtime_status_kubernetes(
        self,
        service: TranscodingSessionService,
    ):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="kubernetes",
            job_name="ffmpeg-job",
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        mock_k8s = MagicMock()
        mock_k8s.get_job_status = AsyncMock(return_value={"active": 1})
        mock_module = MagicMock()
        mock_module.get_kubernetes_transcoding_service = MagicMock(return_value=mock_k8s)

        with patch.dict(
            "sys.modules",
            {"pyrate.services.kubernetes": mock_module},
        ):
            status = await service.get_session_runtime_status(session)

        assert status == {"kubernetes": {"active": 1}}
        mock_k8s.get_job_status.assert_awaited_once_with("ffmpeg-job")

    @pytest.mark.asyncio
    async def test_get_session_runtime_status_docker(
        self,
        service: TranscodingSessionService,
    ):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="docker",
            container_id="container-1",
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )
        mock_container = AsyncMock()
        mock_container.show = AsyncMock(
            return_value={
                "State": {
                    "Status": "running",
                    "Running": True,
                    "StartedAt": "2026-01-01T00:00:00Z",
                    "FinishedAt": "0001-01-01T00:00:00Z",
                    "ExitCode": 0,
                }
            }
        )
        mock_docker = AsyncMock()
        mock_docker.containers.get = AsyncMock(return_value=mock_container)
        mock_docker.__aenter__ = AsyncMock(return_value=mock_docker)
        mock_docker.__aexit__ = AsyncMock(return_value=False)

        with patch("pyrate.services.transcoding_session.Docker", return_value=mock_docker):
            status = await service.get_session_runtime_status(session)

        assert status == {
            "docker": {
                "container_id": "container-1",
                "state": "running",
                "running": True,
                "started_at": "2026-01-01T00:00:00Z",
                "finished_at": "0001-01-01T00:00:00Z",
                "exit_code": 0,
            }
        }
        mock_docker.containers.get.assert_awaited_once_with("container-1")

    @pytest.mark.asyncio
    async def test_get_session_runtime_status_without_runtime_target(
        self,
        service: TranscodingSessionService,
    ):
        session = TranscodingSession(
            session_id="sess_001",
            user_guid=str(uuid.uuid4()),
            content_type="movie",
            content_id=str(uuid.uuid4()),
            content_title="Movie",
            runtime_type="docker",
            container_id=None,
            job_name=None,
            is_active=True,
            started_at=datetime.now(UTC),
            last_accessed_at=datetime.now(UTC),
        )

        assert await service.get_session_runtime_status(session) == {}
