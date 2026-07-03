"""Tests for the Search API endpoints (/api/search/*)."""

from unittest.mock import AsyncMock, patch
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.user import User


def _search_response(**overrides):
    """Build a minimal valid SearchResponse dict."""
    base = {
        "hits": [],
        "total": 0,
        "page": 1,
        "per_page": 20,
        "total_pages": 0,
        "query": None,
        "search_type": "all",
        "took": 0,
        "facets": None,
        "source": "provider",
        "provider": "tmdb",
    }
    base.update(overrides)
    return base


@pytest.fixture(autouse=True)
def mock_search_service():
    """Mock SearchService to avoid DB/ES/provider dependencies."""
    mock_svc = AsyncMock()
    mock_svc.search = AsyncMock(return_value=_search_response())
    mock_svc.browse_local = AsyncMock(return_value=_search_response())
    mock_svc.enrich_with_library_status = AsyncMock(return_value=[])
    mock_svc.get_or_import_item = AsyncMock(return_value=None)
    mock_svc.close = AsyncMock()

    with patch("pyrate.api.v1.search.SearchService", return_value=mock_svc) as cls:
        cls._instance = mock_svc
        yield mock_svc


# ---------------------------------------------------------------------------
# POST /api/search/ - search all content
# ---------------------------------------------------------------------------


class TestSearchAll:
    async def test_search_with_query(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        mock_search_service.search.return_value = _search_response(
            hits=[{"title": "Test Movie", "type": "movies", "score": 1.0}],
            total=1,
        )
        mock_search_service.enrich_with_library_status.return_value = [
            {"title": "Test Movie", "type": "movies", "score": 1.0, "in_library": True}
        ]

        resp = await client.post(
            "/api/search/",
            json={"query": "test"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        mock_search_service.search.assert_awaited_once()
        assert (
            "movies"
            in mock_search_service.search.call_args.kwargs["allowed_libraries"]
        )
        mock_search_service.close.assert_awaited_once()

    async def test_search_with_query_denies_disallowed_search_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Query searches respect explicit library type permissions."""
        test_user.allowed_libraries = ["music"]
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            "/api/search/",
            json={"query": "matrix", "search_type": "movies"},
            headers=user_headers,
        )
        assert resp.status_code == 403
        mock_search_service.search.assert_not_awaited()

    async def test_browse_local_no_query_with_filters(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """No query but filters present -> browse_local path."""
        mock_search_service.browse_local.return_value = _search_response(
            total=5, source="local"
        )

        resp = await client.post(
            "/api/search/",
            json={"genre_id": 28},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()
        mock_search_service.close.assert_awaited_once()

    async def test_browse_local_passes_parental_limit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Filter-only browse applies the current user's parental age gate."""
        test_user.parental_max_age = 12
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            "/api/search/",
            json={"genre_id": 28},
            headers=user_headers,
        )
        assert resp.status_code == 200

        args = mock_search_service.browse_local.call_args.args
        kwargs = mock_search_service.browse_local.call_args.kwargs
        assert args[1] == test_user.guid
        assert kwargs["max_age"] == 12
        assert "movies" in kwargs["allowed_libraries"]

    async def test_browse_local_denies_disallowed_media_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Explicit browse media types respect library permissions."""
        test_user.allowed_libraries = ["music"]
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            "/api/search/",
            json={"media_type": "MOVIES"},
            headers=user_headers,
        )
        assert resp.status_code == 403
        mock_search_service.browse_local.assert_not_awaited()

    async def test_search_with_media_type_filter(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """No query but media_type filter -> browse_local."""
        resp = await client.post(
            "/api/search/",
            json={"media_type": "MOVIES"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()

    @pytest.mark.parametrize(
        "payload",
        [
            {"studio_name": "Studio Ghibli"},
            {"container": "mkv"},
            {"content_rating": "PG-13"},
            {"genre_ids": [28, 12]},
            {"genres": ["Action", "Adventure"]},
            {"exclude_genre_ids": [10749]},
            {"exclude_genres": ["Romance"]},
            {"platform_ids": [6, 48]},
            {"exclude_platform_ids": [130]},
            {"years": [1999, 2003]},
            {"exclude_years": [2024]},
            {"exclude_containers": ["avi"]},
            {"exclude_content_ratings": ["NC-17"]},
            {"exclude_person_guid": str(uuid.uuid4())},
            {"exclude_person_name": "Unwanted Actor"},
            {"has_backdrop": True},
            {"is_favorite": True},
            {"is_played": False},
            {"person_guid": str(uuid.uuid4())},
            {"person_name": "Keanu Reeves"},
            {"sort_by": "title.keyword"},
            {"sort_order": "asc"},
            {"year_from": 1990},
            {"year_to": 2020},
        ],
    )
    async def test_search_with_browse_only_filters(
        self,
        payload,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """No query but compatible browse filters -> browse_local."""
        resp = await client.post(
            "/api/search/",
            json=payload,
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()

    async def test_search_enriches_hits(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Hits get enriched with library status."""
        hits = [{"title": "A", "type": "movies", "score": 1.0}]
        mock_search_service.search.return_value = _search_response(
            hits=hits, total=1
        )
        enriched = [{"title": "A", "type": "movies", "score": 1.0, "in_library": True}]
        mock_search_service.enrich_with_library_status.return_value = enriched

        resp = await client.post(
            "/api/search/",
            json={"query": "A"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.enrich_with_library_status.assert_awaited_once()

    async def test_search_no_hits_skips_enrich(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """When no hits, enrich is not called."""
        mock_search_service.search.return_value = _search_response(
            hits=[], total=0
        )

        resp = await client.post(
            "/api/search/",
            json={"query": "nonexistent"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.enrich_with_library_status.assert_not_awaited()

    async def test_search_exception(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Exception during search -> 500."""
        mock_search_service.search.side_effect = RuntimeError("provider down")

        resp = await client.post(
            "/api/search/",
            json={"query": "test"},
            headers=user_headers,
        )
        assert resp.status_code == 500
        mock_search_service.close.assert_awaited_once()

    async def test_search_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/search/", json={"query": "test"})
        assert resp.status_code == 401

    async def test_search_no_query_no_filters_validation(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
    ):
        """SearchRequest requires query or filters."""
        resp = await client.post(
            "/api/search/",
            json={},
            headers=user_headers,
        )
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# POST /api/search/local
# ---------------------------------------------------------------------------


class TestSearchLocal:
    async def test_search_local_movies(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        mock_search_service.browse_local.return_value = _search_response(
            total=3, source="local", provider="database"
        )

        resp = await client.post(
            "/api/search/local",
            json={"query": "test", "search_type": "movies"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()
        assert mock_search_service.browse_local.call_args.kwargs["max_age"] is None

    async def test_search_local_shows(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        mock_search_service.browse_local.return_value = _search_response(
            total=2, source="local", provider="database"
        )

        resp = await client.post(
            "/api/search/local",
            json={"query": "test", "search_type": "shows"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()

    async def test_search_local_all(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        mock_search_service.browse_local.return_value = _search_response(
            total=10, source="local", provider="database"
        )

        resp = await client.post(
            "/api/search/local",
            json={"query": "test", "search_type": "all"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()

    async def test_search_local_default_type(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Default search_type is 'all'."""
        resp = await client.post(
            "/api/search/local",
            json={"query": "test"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        mock_search_service.browse_local.assert_awaited_once()

    async def test_search_local_adds_source(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        """Result dict gets source/provider fields added."""
        mock_search_service.browse_local.return_value = _search_response(
            source="local",
            provider="database",
        )

        resp = await client.post(
            "/api/search/local",
            json={"query": "test"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["source"] == "local"
        assert data["provider"] == "database"

    async def test_search_local_exception(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        mock_search_service.browse_local.side_effect = RuntimeError("DB down")

        resp = await client.post(
            "/api/search/local",
            json={"query": "test"},
            headers=user_headers,
        )
        assert resp.status_code == 500

    async def test_search_local_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        mock_search_service,
    ):
        test_user.allowed_libraries = ["music"]
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.post(
            "/api/search/local",
            json={"query": "matrix", "search_type": "movies"},
            headers=user_headers,
        )
        assert resp.status_code == 403
        mock_search_service.browse_local.assert_not_awaited()

    async def test_search_local_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/search/local", json={"query": "test"})
        assert resp.status_code == 401


# ---------------------------------------------------------------------------
# POST /api/search/get-or-import
# ---------------------------------------------------------------------------


class TestGetOrImport:
    async def test_invalid_media_type(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "INVALID", "tmdb_id": 123},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "media_type" in resp.json()["detail"]

    async def test_games_without_igdb_id(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "GAMES"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "igdb_id" in resp.json()["detail"]

    async def test_music_without_spotify_id(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MUSIC"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "spotify_id" in resp.json()["detail"]

    async def test_artists_without_spotify_id(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "ARTISTS"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "spotify_id" in resp.json()["detail"]

    async def test_movies_without_tmdb_id(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MOVIES"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "tmdb_id" in resp.json()["detail"]

    async def test_shows_without_tmdb_id(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "SHOWS"},
            headers=admin_headers,
        )
        assert resp.status_code == 400
        assert "tmdb_id" in resp.json()["detail"]

    async def test_success_movie(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
        mock_search_service,
    ):
        mock_search_service.get_or_import_item.return_value = {
            "guid": "abc-123",
            "library_guid": "lib-456",
        }

        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MOVIES", "tmdb_id": 550},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["guid"] == "abc-123"
        assert data["library_guid"] == "lib-456"
        mock_search_service.close.assert_awaited_once()

    async def test_success_game(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
        mock_search_service,
    ):
        mock_search_service.get_or_import_item.return_value = {
            "guid": "game-1",
            "library_guid": None,
        }

        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "GAMES", "igdb_id": 999},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["guid"] == "game-1"

    async def test_success_music(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
        mock_search_service,
    ):
        mock_search_service.get_or_import_item.return_value = {
            "guid": "music-1",
            "library_guid": "lib-m",
        }

        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MUSIC", "spotify_id": "spotify:track:abc"},
            headers=admin_headers,
        )
        assert resp.status_code == 200

    async def test_import_failed_returns_404(
        self,
        client: AsyncClient,
        test_user: User,
        admin_headers,
        mock_search_service,
    ):
        mock_search_service.get_or_import_item.return_value = None

        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MOVIES", "tmdb_id": 999999},
            headers=admin_headers,
        )
        assert resp.status_code == 404
        mock_search_service.close.assert_awaited_once()

    async def test_regular_user_forbidden(
        self,
        client: AsyncClient,
        user_headers,
        mock_search_service,
    ):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MOVIES", "tmdb_id": 1},
            headers=user_headers,
        )
        assert resp.status_code == 403
        mock_search_service.get_or_import_item.assert_not_awaited()

    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/search/get-or-import",
            json={"media_type": "MOVIES", "tmdb_id": 1},
        )
        assert resp.status_code == 401
