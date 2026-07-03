"""Tests for lightrays API endpoints (/api/lightrays/*)."""

import json
import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.library import Library
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.user import User


@pytest.fixture
async def game_media(db_session: AsyncSession) -> MediaItem:
    _now = datetime.now(UTC)
    library = Library(
        guid=uuid.uuid4(),
        name="Games Library",
        type="GAMES",
        plugin_id="games",
        path="/library/games",
        enabled=True,
        created_at=_now,
        updated_at=_now,
    )
    db_session.add(library)
    await db_session.flush()

    media = MediaItem(
        guid=uuid.uuid4(),
        title="Test Game",
        media_type=MediaType.GAMES,
        library_guid=library.guid,
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)
    return media


@pytest.fixture
async def movie_media(db_session: AsyncSession) -> MediaItem:
    _now = datetime.now(UTC)
    library = Library(
        guid=uuid.uuid4(),
        name="Movies Library",
        type="MOVIES",
        plugin_id="movies",
        path="/library/movies",
        enabled=True,
        created_at=_now,
        updated_at=_now,
    )
    db_session.add(library)
    await db_session.flush()

    media = MediaItem(
        guid=uuid.uuid4(),
        title="Test Movie",
        media_type=MediaType.MOVIES,
        library_guid=library.guid,
    )
    db_session.add(media)
    await db_session.commit()
    await db_session.refresh(media)
    return media


# ---------------------------------------------------------------------------
# POST /api/lightrays/launch/{media_id}
# ---------------------------------------------------------------------------
class TestLightraysLaunch:
    async def test_launch_success(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        with patch(
            "pyrate.api.v1.lightrays.launch_session",
            new_callable=AsyncMock,
            return_value={
                "session_id": "sess-123",
                "websocket_url": "ws://localhost:8009/api/lightrays-ws/sess-123",
                "ws_ticket": "ws-ticket-abc",
                "ice_servers": [],
            },
        ):
            resp = await client.post(
                f"/api/lightrays/launch/{game_media.guid}",
                json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
                headers=user_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["session_id"] == "sess-123"
            assert data["websocket_url"] == "ws://localhost:8009/api/lightrays-ws/sess-123"
            assert data["ws_ticket"] == "ws-ticket-abc"

    async def test_launch_uses_game_docker_image(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        game_media.extra_data = json.dumps(
            {"lightrays": {"docker_image": "ghcr.io/example/game-runtime:latest"}}
        )
        db_session.add(game_media)
        await db_session.commit()
        await db_session.refresh(game_media)

        launch_mock = AsyncMock(
            return_value={
                "session_id": "sess-123",
                "websocket_url": "ws://localhost:8009/api/lightrays-ws/sess-123",
                "ws_ticket": "ws-ticket-abc",
                "ice_servers": [],
            }
        )
        with patch("pyrate.api.v1.lightrays.launch_session", launch_mock):
            resp = await client.post(
                f"/api/lightrays/launch/{game_media.guid}",
                json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
                headers=user_headers,
            )

        assert resp.status_code == 200
        assert launch_mock.await_args.kwargs["docker_image"] == (
            "ghcr.io/example/game-runtime:latest"
        )

    async def test_launch_rejects_invalid_game_docker_image(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        game_media.extra_data = json.dumps(
            {"lightrays": {"docker_image": "https://example.com/image"}}
        )
        db_session.add(game_media)
        await db_session.commit()
        await db_session.refresh(game_media)

        with patch(
            "pyrate.api.v1.lightrays.launch_session", new_callable=AsyncMock
        ) as launch_mock:
            resp = await client.post(
                f"/api/lightrays/launch/{game_media.guid}",
                json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
                headers=user_headers,
            )

        assert resp.status_code == 400
        assert "Docker image" in resp.json()["detail"]
        launch_mock.assert_not_awaited()

    async def test_launch_media_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        fake_id = uuid.uuid4()
        resp = await client.post(
            f"/api/lightrays/launch/{fake_id}",
            json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_launch_not_a_game(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        movie_media: MediaItem,
    ):
        resp = await client.post(
            f"/api/lightrays/launch/{movie_media.guid}",
            json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "only available for games" in resp.json()["detail"]

    async def test_launch_denies_disallowed_games_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        test_user.allowed_libraries = ["movies"]
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            f"/api/lightrays/launch/{game_media.guid}",
            json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_launch_denies_parental_blocked_game(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        test_user.parental_max_age = 12
        game_media.min_age = 18
        db_session.add_all([test_user, game_media])
        await db_session.commit()

        resp = await client.post(
            f"/api/lightrays/launch/{game_media.guid}",
            json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_launch_session_exception(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        game_media: MediaItem,
    ):
        with patch(
            "pyrate.api.v1.lightrays.launch_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Container failed"),
        ):
            resp = await client.post(
                f"/api/lightrays/launch/{game_media.guid}",
                json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
                headers=user_headers,
            )
            assert resp.status_code == 502
            assert "Lightrays running" in resp.json()["detail"]

    async def test_launch_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            f"/api/lightrays/launch/{uuid.uuid4()}",
            json={"width": 1920, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
        )
        assert resp.status_code in (401, 403)

    async def test_launch_rejects_invalid_dimensions(
        self, client: AsyncClient, test_user: User, user_headers, game_media: MediaItem
    ):
        resp = await client.post(
            f"/api/lightrays/launch/{game_media.guid}",
            json={"width": 32, "height": 1080, "fps": 60, "bitrate_kbps": 10000},
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/lightrays/stop
# ---------------------------------------------------------------------------
class TestLightraysStop:
    async def test_stop_success(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.stop_session",
            new_callable=AsyncMock,
            return_value={"status": "stopped"},
        ), patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(test_user.guid), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.post(
                "/api/lightrays/stop",
                json={"session_id": "sess-123"},
                headers=user_headers,
            )
            assert resp.status_code == 200

    async def test_stop_exception(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.stop_session",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Stop failed"),
        ), patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(test_user.guid), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.post(
                "/api/lightrays/stop",
                json={"session_id": "sess-123"},
                headers=user_headers,
            )
            assert resp.status_code == 502

    async def test_stop_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/lightrays/stop",
            json={"session_id": "sess-123"},
        )
        assert resp.status_code in (401, 403)

    async def test_stop_denies_other_user_session(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(uuid.uuid4()), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.post(
                "/api/lightrays/stop",
                json={"session_id": "sess-123"},
                headers=user_headers,
            )
            assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/lightrays/stats/{session_id}
# ---------------------------------------------------------------------------
class TestLightraysStats:
    async def test_stats_success(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.get_stats",
            new_callable=AsyncMock,
            return_value={"cpu": 50.0, "memory": 1024},
        ), patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(test_user.guid), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.get(
                "/api/lightrays/stats/sess-123",
                headers=user_headers,
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["cpu"] == 50.0

    async def test_stats_exception(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.get_stats",
            new_callable=AsyncMock,
            side_effect=RuntimeError("Stats failed"),
        ), patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(test_user.guid), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.get(
                "/api/lightrays/stats/sess-123",
                headers=user_headers,
            )
            assert resp.status_code == 502

    async def test_stats_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/lightrays/stats/sess-123")
        assert resp.status_code in (401, 403)

    async def test_stats_denies_other_user_session(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        with patch(
            "pyrate.api.v1.lightrays.get_session_record",
            new_callable=AsyncMock,
            return_value={"user_id": str(uuid.uuid4()), "media_id": str(uuid.uuid4())},
        ):
            resp = await client.get(
                "/api/lightrays/stats/sess-123",
                headers=user_headers,
            )
            assert resp.status_code == 403
