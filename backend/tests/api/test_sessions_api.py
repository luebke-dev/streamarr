"""Tests for the Sessions (transcoding) API endpoints (/api/sessions/*)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient

from streamarr.models.user import User
from streamarr.schemas.transcoding import TranscodingSession

from .conftest import auth_headers


def _make_session(
    user_guid: str | None = None,
    session_id: str | None = None,
    is_active: bool = True,
    runtime_type: str = "docker",
    job_name: str | None = None,
    container_id: str | None = None,
) -> TranscodingSession:
    """Create a TranscodingSession for testing."""
    return TranscodingSession(
        session_id=session_id or str(uuid.uuid4()),
        user_guid=user_guid or str(uuid.uuid4()),
        content_type="movie",
        content_id=str(uuid.uuid4()),
        content_title="Test Movie",
        container_id=container_id,
        job_name=job_name,
        runtime_type=runtime_type,
        is_active=is_active,
        started_at=datetime.now(UTC),
        last_accessed_at=datetime.now(UTC),
    )


@pytest.fixture(autouse=True)
def mock_session_service():
    """Mock the transcoding session service to avoid Redis dependency."""
    mock_service = AsyncMock()
    mock_service.get_sessions_response = AsyncMock(
        return_value={"sessions": [], "total": 0, "active_count": 0}
    )
    mock_service.get_user_sessions = AsyncMock(return_value=[])
    mock_service.get_session = AsyncMock(return_value=None)
    mock_service.terminate_session = AsyncMock(
        return_value={"session_id": "x", "status": "terminated"}
    )
    mock_service.get_session_logs = AsyncMock(return_value="session logs")
    mock_service.get_session_runtime_status = AsyncMock(return_value={})
    mock_service.cleanup_stale_sessions = AsyncMock(return_value=0)
    mock_service.get_all_sessions = AsyncMock(return_value=[])

    with patch(
        "streamarr.api.v1.sessions.get_transcoding_session_service",
        return_value=mock_service,
    ):
        yield mock_service


class TestListSessions:
    async def test_list_sessions_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/sessions")
        assert resp.status_code == 401

    async def test_list_sessions_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/sessions", headers=admin_headers)
        assert resp.status_code == 200


class TestMySessions:
    async def test_my_sessions(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/sessions/my", headers=user_headers)
        assert resp.status_code == 200


class TestSessionById:
    async def test_session_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/sessions/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_get_session_forbidden_other_user(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        mock_session_service,
    ):
        """Regular user cannot view another user's session."""
        session = _make_session(user_guid=str(uuid.uuid4()))  # different user
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_get_session_success_own(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_session_service,
    ):
        """Regular user can view their own session."""
        session = _make_session(user_guid=str(test_user.guid))
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["session_id"] == session.session_id

    async def test_get_session_success_superuser(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        """Superuser can view any session."""
        session = _make_session(user_guid=str(uuid.uuid4()))
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}", headers=admin_headers
        )
        assert resp.status_code == 200


class TestDeleteSession:
    async def test_delete_nonexistent(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.delete(
            f"/api/sessions/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_delete_forbidden_other_user(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        mock_session_service,
    ):
        """Regular user cannot terminate another user's session."""
        session = _make_session(user_guid=str(uuid.uuid4()))
        mock_session_service.get_session.return_value = session

        resp = await client.delete(
            f"/api/sessions/{session.session_id}", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_delete_success_own(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_session_service,
    ):
        """Regular user can terminate their own session."""
        session = _make_session(user_guid=str(test_user.guid))
        mock_session_service.get_session.return_value = session
        mock_session_service.terminate_session.return_value = {
            "session_id": session.session_id,
            "status": "terminated",
        }

        resp = await client.delete(
            f"/api/sessions/{session.session_id}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["message"] == "Session terminated"

    async def test_delete_success_superuser(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        """Superuser can terminate any session."""
        session = _make_session(user_guid=str(uuid.uuid4()))
        mock_session_service.get_session.return_value = session
        mock_session_service.terminate_session.return_value = {
            "session_id": session.session_id,
            "status": "terminated",
        }

        resp = await client.delete(
            f"/api/sessions/{session.session_id}", headers=admin_headers
        )
        assert resp.status_code == 200


class TestCleanupSessions:
    async def test_cleanup_success(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        mock_session_service.cleanup_stale_sessions.return_value = 3

        resp = await client.post("/api/sessions/cleanup", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["stale_sessions_cleaned"] == 3
        assert "temp_cleanup" in data

    async def test_cleanup_forbidden_regular_user(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        resp = await client.post("/api/sessions/cleanup", headers=user_headers)
        assert resp.status_code == 403


class TestTerminateAllSessions:
    async def test_terminate_all_no_active(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        mock_session_service.get_all_sessions.return_value = []

        resp = await client.delete("/api/sessions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminated_count"] == 0
        assert data["errors"] is None

    async def test_terminate_all_with_sessions(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        s1 = _make_session()
        s2 = _make_session()
        mock_session_service.get_all_sessions.return_value = [s1, s2]

        resp = await client.delete("/api/sessions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminated_count"] == 2

    async def test_terminate_all_with_errors(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        s1 = _make_session()
        s2 = _make_session()
        mock_session_service.get_all_sessions.return_value = [s1, s2]
        mock_session_service.terminate_session.side_effect = [
            None,  # s1 succeeds
            RuntimeError("container stuck"),  # s2 fails
        ]

        resp = await client.delete("/api/sessions", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["terminated_count"] == 1
        assert len(data["errors"]) == 1
        assert data["errors"][0]["session_id"] == s2.session_id

    async def test_terminate_all_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.delete("/api/sessions", headers=user_headers)
        assert resp.status_code == 403


class TestSessionLogs:
    async def test_logs_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/sessions/{uuid.uuid4()}/logs", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_logs_forbidden(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        mock_session_service,
    ):
        session = _make_session(user_guid=str(uuid.uuid4()))
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_logs_kubernetes_success(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="kubernetes", job_name="ffmpeg-job-123"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_logs.return_value = "ffmpeg output here"

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["logs"] == "ffmpeg output here"
        assert data["runtime_type"] == "kubernetes"
        mock_session_service.get_session_logs.assert_awaited_once_with(
            session,
            tail_lines=100,
        )

    async def test_logs_kubernetes_error(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="kubernetes", job_name="ffmpeg-job-123"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_logs.return_value = (
            "Error retrieving Kubernetes logs: k8s unreachable"
        )

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert "Error retrieving Kubernetes logs" in resp.json()["logs"]

    async def test_logs_docker_success(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="docker", container_id="abc123"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_logs.return_value = "line1\nline2\n"

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json()["logs"] == "line1\nline2\n"

    async def test_logs_docker_error(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="docker", container_id="abc123"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_logs.return_value = (
            "Error retrieving Docker logs: docker socket error"
        )

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert "Error retrieving Docker logs" in resp.json()["logs"]

    async def test_logs_no_container(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="docker", container_id=None, job_name=None
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_logs.return_value = (
            "No container found for this session"
        )

        resp = await client.get(
            f"/api/sessions/{session.session_id}/logs",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["logs"] == "No container found for this session"


class TestSessionStatus:
    async def test_status_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/sessions/{uuid.uuid4()}/status", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_status_forbidden(
        self,
        client: AsyncClient,
        test_user: User,
        test_superuser: User,
        user_headers,
        mock_session_service,
    ):
        session = _make_session(user_guid=str(uuid.uuid4()))
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_status_kubernetes(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="kubernetes", job_name="job-xyz"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_runtime_status.return_value = {
            "kubernetes": {"active": 1, "succeeded": 0}
        }

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["kubernetes"]["active"] == 1
        mock_session_service.get_session_runtime_status.assert_awaited_once_with(session)

    async def test_status_kubernetes_error(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="kubernetes", job_name="job-xyz"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_runtime_status.return_value = {
            "kubernetes_error": "k8s down"
        }

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert "k8s down" in resp.json()["kubernetes_error"]

    async def test_status_docker(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="docker", container_id="container-abc"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_runtime_status.return_value = {
            "docker": {
                "container_id": "container-abc",
                "state": "running",
                "running": True,
                "started_at": "2025-01-01T00:00:00Z",
                "finished_at": "0001-01-01T00:00:00Z",
                "exit_code": 0,
            }
        }

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["docker"]["running"] is True
        assert data["docker"]["container_id"] == "container-abc"

    async def test_status_docker_error(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        session = _make_session(
            runtime_type="docker", container_id="container-abc"
        )
        mock_session_service.get_session.return_value = session
        mock_session_service.get_session_runtime_status.return_value = {
            "docker_error": "no docker"
        }

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert "no docker" in resp.json()["docker_error"]

    async def test_status_no_container_no_job(
        self,
        client: AsyncClient,
        test_superuser: User,
        admin_headers,
        mock_session_service,
    ):
        """Session with no container_id and no job_name returns basic status."""
        session = _make_session(
            runtime_type="docker", container_id=None, job_name=None
        )
        mock_session_service.get_session.return_value = session

        resp = await client.get(
            f"/api/sessions/{session.session_id}/status",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "docker" not in data
        assert "kubernetes" not in data
        assert data["is_active"] is True
