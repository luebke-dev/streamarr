"""Tests for the Tasks API endpoints (/api/tasks/*)."""

from unittest.mock import AsyncMock, MagicMock, patch

from httpx import AsyncClient

from pyrate.models.activity_log import ActivityLog
from pyrate.models.user import User


class TestListTasks:
    async def test_list_tasks_success(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/tasks", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        assert len(data) >= 10
        task_ids = {t["id"] for t in data}
        assert "refresh_downloads" in task_ids
        assert "reindex_all" in task_ids
        assert "cleanup_storage" in task_ids

    async def test_list_tasks_unauthorized(self, client: AsyncClient):
        resp = await client.get("/api/tasks")
        assert resp.status_code == 401

    async def test_list_tasks_forbidden_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/tasks", headers=user_headers)
        assert resp.status_code == 403


class TestTaskHistory:
    async def test_history_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/tasks/history")
        assert resp.status_code == 401

    async def test_history_forbidden_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/tasks/history", headers=user_headers)
        assert resp.status_code == 403

    async def test_history_records_queued_task(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch("pyrate.worker.refresh_downloads", mock_task, create=True):
            run_resp = await client.post(
                "/api/tasks/refresh_downloads/run", headers=admin_headers
            )
        assert run_resp.status_code == 200

        history_resp = await client.get("/api/tasks/history", headers=admin_headers)
        assert history_resp.status_code == 200
        data = history_resp.json()
        assert data["total"] >= 1
        assert data["items"][0]["event_type"] == "task.queued"
        assert data["items"][0]["entity_type"] == "task"
        assert "Refresh Downloads" in data["items"][0]["message"]
        assert "run_id" in data["items"][0]["extra_data"]

    async def test_history_filters_by_status(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("pyrate.worker.refresh_downloads", mock_task, create=True):
            run_resp = await client.post(
                "/api/tasks/refresh_downloads/run", headers=admin_headers
            )
        assert run_resp.status_code == 500

        failed_resp = await client.get(
            "/api/tasks/history?status=failed", headers=admin_headers
        )
        assert failed_resp.status_code == 200
        data = failed_resp.json()
        assert data["total"] >= 1
        assert data["items"][0]["event_type"] == "task.failed"
        assert "redis down" in data["items"][0]["extra_data"]

    async def test_history_invalid_status(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            "/api/tasks/history?status=unknown", headers=admin_headers
        )
        assert resp.status_code == 400

    async def test_get_task_run_history(
        self, client: AsyncClient, db_session, test_superuser: User, admin_headers
    ):
        run_id = "run-123"
        db_session.add_all(
            [
                ActivityLog(
                    event_type="task.queued",
                    message="Queued task",
                    entity_type="task",
                    extra_data=(
                        '{"category":"metadata","run_id":"run-123",'
                        '"status":"queued","task_id":"import_trending_movies"}'
                    ),
                ),
                ActivityLog(
                    event_type="task.completed",
                    message="Completed task",
                    entity_type="task",
                    extra_data=(
                        '{"category":"metadata","run_id":"run-123",'
                        '"status":"completed","task_id":"import_trending_movies"}'
                    ),
                ),
                ActivityLog(
                    event_type="task.failed",
                    message="Other task failed",
                    entity_type="task",
                    extra_data=(
                        '{"category":"metadata","run_id":"other",'
                        '"status":"failed","task_id":"import_trending_movies"}'
                    ),
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get(f"/api/tasks/history/{run_id}", headers=admin_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_id"] == run_id
        assert data["task_id"] == "import_trending_movies"
        assert data["category"] == "metadata"
        assert data["status"] == "completed"
        assert data["queued_at"] is not None
        assert data["completed_at"] is not None
        assert data["failed_at"] is None
        assert data["latest_message"] == "Completed task"
        assert [event["event_type"] for event in data["events"]] == [
            "task.completed",
            "task.queued",
        ]

    async def test_get_task_run_history_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/tasks/history/missing", headers=admin_headers)

        assert resp.status_code == 404


class TestRunTask:
    async def test_task_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/tasks/nonexistent_task/run", headers=admin_headers
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]

    async def test_run_refresh_downloads(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch(
            "pyrate.api.v1.tasks.refresh_downloads", mock_task, create=True
        ), patch("pyrate.worker.refresh_downloads", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/refresh_downloads/run", headers=admin_headers
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["task_id"] == "refresh_downloads"
        assert data["run_id"]
        assert "queued successfully" in data["message"]

    async def test_run_import_trending_movies(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch("pyrate.worker.import_trending_movies", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/import_trending_movies/run", headers=admin_headers
            )

        assert resp.status_code == 200
        assert resp.json()["task_id"] == "import_trending_movies"

    async def test_run_import_trending_shows(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch("pyrate.worker.import_trending_shows", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/import_trending_shows/run", headers=admin_headers
            )

        assert resp.status_code == 200
        assert resp.json()["task_id"] == "import_trending_shows"

    async def test_run_import_trending_games(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch("pyrate.worker.import_trending_games", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/import_trending_games/run", headers=admin_headers
            )

        assert resp.status_code == 200
        assert resp.json()["task_id"] == "import_trending_games"

    async def test_run_cleanup_orphaned_temp_files(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch(
            "pyrate.worker.cleanup_orphaned_temp_files", mock_task, create=True
        ):
            resp = await client.post(
                "/api/tasks/cleanup_orphaned_temp_files/run",
                headers=admin_headers,
            )

        assert resp.status_code == 200

    async def test_run_cleanup_stale_transcoding_sessions(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch(
            "pyrate.worker.cleanup_stale_transcoding_sessions",
            mock_task,
            create=True,
        ):
            resp = await client.post(
                "/api/tasks/cleanup_stale_transcoding_sessions/run",
                headers=admin_headers,
            )

        assert resp.status_code == 200

    async def test_run_cleanup_storage(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        mock_task = AsyncMock()
        mock_task.kiq = AsyncMock()

        with patch("pyrate.worker.cleanup_storage", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/cleanup_storage/run", headers=admin_headers
            )

        assert resp.status_code == 200

    async def test_run_reindex_all(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """Test reindex_all task endpoint directly (bypassing ASGI)."""
        from pyrate.api.v1.tasks import run_task

        mock_user = MagicMock()

        with patch("pyrate.api.v1.tasks._spawn_background") as spawn_background:
            result = await run_task("reindex_all", mock_user)

        assert result.task_id == "reindex_all"
        assert "queued successfully" in result.message
        spawn_background.assert_called_once()
        spawn_background.call_args.args[0].close()

    async def test_run_reindex_movies(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        from pyrate.api.v1.tasks import run_task

        mock_user = MagicMock()

        with patch("pyrate.api.v1.tasks._spawn_background") as spawn_background:
            result = await run_task("reindex_movies", mock_user)

        assert result.task_id == "reindex_movies"
        spawn_background.assert_called_once()
        spawn_background.call_args.args[0].close()

    async def test_run_reindex_shows(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        from pyrate.api.v1.tasks import run_task

        mock_user = MagicMock()

        with patch("pyrate.api.v1.tasks._spawn_background") as spawn_background:
            result = await run_task("reindex_shows", mock_user)

        assert result.task_id == "reindex_shows"
        spawn_background.assert_called_once()
        spawn_background.call_args.args[0].close()

    async def test_run_task_worker_exception(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """Worker task raises exception -> 500."""
        mock_task = MagicMock()
        mock_task.kiq = AsyncMock(side_effect=RuntimeError("redis down"))

        with patch("pyrate.worker.refresh_downloads", mock_task, create=True):
            resp = await client.post(
                "/api/tasks/refresh_downloads/run", headers=admin_headers
            )

        assert resp.status_code == 500
        assert "Failed to start task" in resp.json()["detail"]

    async def test_run_task_unauthorized(self, client: AsyncClient):
        resp = await client.post("/api/tasks/refresh_downloads/run")
        assert resp.status_code == 401

    async def test_run_task_forbidden_regular_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/tasks/refresh_downloads/run", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_run_task_http_exception_reraise(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """HTTPException from task lookup is re-raised (not wrapped in 500)."""
        resp = await client.post(
            "/api/tasks/nonexistent_task/run", headers=admin_headers
        )
        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]
