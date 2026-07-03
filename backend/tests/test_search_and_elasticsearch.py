"""Tests for SearchService and ElasticsearchService (extended coverage)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio

from pyrate.schemas.search import SearchRequest, SearchType
from pyrate.services.elasticsearch import ElasticsearchService


# ==========================================================================
# ElasticsearchService - extended coverage
# ==========================================================================


def _make_es_service(with_client: bool = True) -> ElasticsearchService:
    svc = ElasticsearchService()
    svc.index_prefix = "test_pyrate"
    if with_client:
        client = AsyncMock()
        client.ping = AsyncMock(return_value=True)
        client.close = AsyncMock()
        client.indices = AsyncMock()
        client.indices.exists = AsyncMock(return_value=False)
        client.indices.create = AsyncMock()
        client.index = AsyncMock(return_value={"result": "created"})
        client.delete = AsyncMock()
        client.bulk = AsyncMock(
            return_value={
                "items": [
                    {"index": {"status": 201}},
                    {"index": {"status": 201}},
                ]
            }
        )
        svc.client = client
    else:
        svc.client = None
    return svc


def _make_search_response(hits=None, total=0):
    if hits is None:
        hits = []
    return {
        "hits": {
            "total": {"value": total},
            "hits": hits,
        }
    }


def _make_hit(title="Test", score=5.0, has_highlight=False, has_id=True):
    hit = {
        "_id": str(uuid.uuid4()),
        "_score": score,
        "_source": {"title": title},
        "_index": "test_pyrate_movies",
    }
    if has_id:
        hit["_source"]["id"] = str(uuid.uuid4())
    if has_highlight:
        hit["highlight"] = {"title": [f"<em>{title}</em>"]}
    return hit


def _make_movie_mock(**overrides):
    movie = MagicMock()
    movie.guid = overrides.get("guid", uuid.uuid4())
    movie.title = overrides.get("title", "Test Movie")
    movie.original_title = overrides.get("original_title", "Test Movie")
    movie.description = overrides.get("description", "A test movie")
    movie.tagline = overrides.get("tagline", None)
    movie.release_date = overrides.get("release_date", datetime(2020, 1, 1, tzinfo=UTC))
    movie.poster_path = overrides.get("poster_path", "/poster.jpg")
    movie.backdrop_path = overrides.get("backdrop_path", "/backdrop.jpg")
    movie.availability_status = overrides.get("availability_status", "available")
    movie.genres = overrides.get("genres", [])
    movie.external_ids = overrides.get("external_ids", [])
    movie.created_at = overrides.get("created_at", datetime.now(UTC))
    movie.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return movie


def _make_show_mock(**overrides):
    show = MagicMock()
    show.guid = overrides.get("guid", uuid.uuid4())
    show.title = overrides.get("title", "Test Show")
    show.original_title = overrides.get("original_title", "Test Show")
    show.description = overrides.get("description", "A test show")
    show.tagline = overrides.get("tagline", None)
    show.first_air_date = overrides.get("first_air_date", datetime(2020, 1, 1, tzinfo=UTC))
    show.last_air_date = overrides.get("last_air_date", datetime(2021, 6, 1, tzinfo=UTC))
    show.status = overrides.get("status", "Ended")
    show.poster_path = overrides.get("poster_path", "/poster.jpg")
    show.backdrop_path = overrides.get("backdrop_path", "/backdrop.jpg")
    show.genres = overrides.get("genres", [])
    show.external_ids = overrides.get("external_ids", [])
    show.created_at = overrides.get("created_at", datetime.now(UTC))
    show.updated_at = overrides.get("updated_at", datetime.now(UTC))
    return show


# ---------------------------------------------------------------------------
# Elasticsearch: Initialize / Close
# ---------------------------------------------------------------------------


class TestElasticsearchLifecycle:
    @pytest.mark.asyncio
    async def test_initialize_success(self):
        svc = ElasticsearchService()
        svc.index_prefix = "test"
        with patch(
            "pyrate.services.elasticsearch.AsyncElasticsearch"
        ) as MockES:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=True)
            mock_client.indices = AsyncMock()
            mock_client.indices.exists = AsyncMock(return_value=True)
            MockES.return_value = mock_client

            await svc.initialize()

            assert svc.client is not None
            mock_client.ping.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_initialize_ping_fails(self):
        svc = ElasticsearchService()
        svc.index_prefix = "test"
        with patch(
            "pyrate.services.elasticsearch.AsyncElasticsearch"
        ) as MockES:
            mock_client = AsyncMock()
            mock_client.ping = AsyncMock(return_value=False)
            MockES.return_value = mock_client

            await svc.initialize()
            # Ping failures disable ES so callers reliably fall back to local DB.
            assert svc.client is None

    @pytest.mark.asyncio
    async def test_initialize_connection_error(self):
        from elasticsearch.exceptions import ConnectionError as ESConnectionError

        svc = ElasticsearchService()
        svc.index_prefix = "test"
        with patch(
            "pyrate.services.elasticsearch.AsyncElasticsearch"
        ) as MockES:
            MockES.side_effect = ESConnectionError("connection refused")
            await svc.initialize()
            assert svc.client is None

    @pytest.mark.asyncio
    async def test_close_with_client(self):
        svc = _make_es_service(with_client=True)
        await svc.close()
        svc.client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_without_client(self):
        svc = _make_es_service(with_client=False)
        await svc.close()  # Should not raise


# ---------------------------------------------------------------------------
# Elasticsearch: _create_indices
# ---------------------------------------------------------------------------


class TestCreateIndices:
    @pytest.mark.asyncio
    async def test_creates_both_indices(self):
        svc = _make_es_service()
        svc.client.indices.exists = AsyncMock(return_value=False)
        await svc._create_indices()
        assert svc.client.indices.create.await_count == 3

    @pytest.mark.asyncio
    async def test_skips_existing_indices(self):
        svc = _make_es_service()
        svc.client.indices.exists = AsyncMock(return_value=True)
        await svc._create_indices()
        svc.client.indices.create.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_create_indices_exception(self):
        svc = _make_es_service()
        svc.client.indices.exists = AsyncMock(side_effect=Exception("boom"))
        # Should not raise, just log error
        await svc._create_indices()


# ---------------------------------------------------------------------------
# Elasticsearch: Indexing
# ---------------------------------------------------------------------------


class TestElasticsearchIndexing:
    @pytest.mark.asyncio
    async def test_index_movie_with_genres_and_external_ids(self):
        svc = _make_es_service()
        genre = MagicMock()
        genre.id = 1
        genre.name = "Action"
        ext = MagicMock()
        ext.source = "tmdb"
        ext.external_id = "12345"
        ext2 = MagicMock()
        ext2.source = "imdb"
        ext2.external_id = "tt12345"
        movie = _make_movie_mock(genres=[genre], external_ids=[ext, ext2])

        result = await svc.index_movie(movie)
        assert result is True
        svc.client.index.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_movie_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.index_movie(_make_movie_mock())
        assert result is False

    @pytest.mark.asyncio
    async def test_index_movie_no_release_date(self):
        svc = _make_es_service()
        movie = _make_movie_mock(release_date=None, created_at=None, updated_at=None)
        result = await svc.index_movie(movie)
        assert result is True

    @pytest.mark.asyncio
    async def test_index_movie_exception(self):
        svc = _make_es_service()
        svc.client.index = AsyncMock(side_effect=Exception("index failed"))
        result = await svc.index_movie(_make_movie_mock())
        assert result is False

    @pytest.mark.asyncio
    async def test_index_show_success(self):
        svc = _make_es_service()
        show = _make_show_mock()
        result = await svc.index_show(show)
        assert result is True
        svc.client.index.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_show_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.index_show(_make_show_mock())
        assert result is False

    @pytest.mark.asyncio
    async def test_index_show_no_dates(self):
        svc = _make_es_service()
        show = _make_show_mock(
            first_air_date=None, last_air_date=None,
            created_at=None, updated_at=None,
        )
        result = await svc.index_show(show)
        assert result is True

    @pytest.mark.asyncio
    async def test_index_show_exception(self):
        svc = _make_es_service()
        svc.client.index = AsyncMock(side_effect=Exception("index failed"))
        result = await svc.index_show(_make_show_mock())
        assert result is False


# ---------------------------------------------------------------------------
# Elasticsearch: Search (movies, shows, all)
# ---------------------------------------------------------------------------


class TestElasticsearchSearch:
    @pytest.mark.asyncio
    async def test_search_movies_basic(self):
        svc = _make_es_service()
        hit = _make_hit("Inception", score=8.5, has_highlight=True)
        svc.client.search = AsyncMock(
            return_value=_make_search_response([hit], total=1)
        )
        req = SearchRequest(query="Inception", search_type=SearchType.MOVIES)
        result = await svc.search_movies(req)
        assert result["total"] == 1
        assert len(result["hits"]) == 1
        assert result["hits"][0]["guid"] is not None
        assert "highlight" in result["hits"][0]

    @pytest.mark.asyncio
    async def test_search_movies_no_client(self):
        svc = _make_es_service(with_client=False)
        req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        result = await svc.search_movies(req)
        assert result["total"] == 0
        assert result["hits"] == []
        assert result["took"] == 0

    @pytest.mark.asyncio
    async def test_search_movies_with_fuzzy(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(query="Incpetion", search_type=SearchType.MOVIES, fuzzy=True)
        result = await svc.search_movies(req)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_movies_with_genres_filter(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(
            query="Test", search_type=SearchType.MOVIES,
            genres=["Action", "Drama"],
        )
        result = await svc.search_movies(req)
        assert result["total"] == 0
        # Verify query was sent to ES
        call_args = svc.client.search.call_args
        body = call_args.kwargs.get("body") or call_args[1].get("body")
        assert "filter" in body["query"]["bool"]

    @pytest.mark.asyncio
    async def test_search_movies_with_year_filters(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(
            query="Test", search_type=SearchType.MOVIES,
            year_from=2000, year_to=2020,
        )
        result = await svc.search_movies(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_movies_sort_by_title(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        from pyrate.schemas.search import SearchSortBy, SortOrder
        req = SearchRequest(
            query="Test", search_type=SearchType.MOVIES,
            sort_by=SearchSortBy.TITLE, sort_order=SortOrder.ASC,
        )
        result = await svc.search_movies(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_movies_sort_by_release_date(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        from pyrate.schemas.search import SearchSortBy
        req = SearchRequest(
            query="Test", search_type=SearchType.MOVIES,
            sort_by=SearchSortBy.RELEASE_DATE,
        )
        result = await svc.search_movies(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_movies_exception(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(side_effect=Exception("search failed"))
        req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        result = await svc.search_movies(req)
        assert result["total"] == 0
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_shows_basic(self):
        svc = _make_es_service()
        hit = _make_hit("Breaking Bad", score=9.0)
        svc.client.search = AsyncMock(
            return_value=_make_search_response([hit], total=1)
        )
        req = SearchRequest(query="Breaking", search_type=SearchType.SHOWS)
        result = await svc.search_shows(req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_shows_no_client(self):
        svc = _make_es_service(with_client=False)
        req = SearchRequest(query="Test", search_type=SearchType.SHOWS)
        result = await svc.search_shows(req)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_shows_with_fuzzy_and_filters(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(
            query="Brekking", search_type=SearchType.SHOWS,
            fuzzy=True, genres=["Crime"], year_from=2008,
        )
        result = await svc.search_shows(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_shows_exception(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(side_effect=Exception("search failed"))
        req = SearchRequest(query="Test", search_type=SearchType.SHOWS)
        result = await svc.search_shows(req)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_all_no_client(self):
        svc = _make_es_service(with_client=False)
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc.search_all(req)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_all_delegates_to_movies(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        result = await svc.search_all(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_all_delegates_to_shows(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(query="Test", search_type=SearchType.SHOWS)
        result = await svc.search_all(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_all_multi_index(self):
        svc = _make_es_service()
        hit1 = _make_hit("Movie", score=8.0, has_highlight=True)
        hit2 = _make_hit("Show", score=7.0)
        svc.client.search = AsyncMock(
            return_value=_make_search_response([hit1, hit2], total=2)
        )
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc.search_all(req)
        assert result["total"] == 2
        assert len(result["hits"]) == 2

    @pytest.mark.asyncio
    async def test_search_all_with_fuzzy_and_filters(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        req = SearchRequest(
            query="Test", search_type=SearchType.ALL,
            fuzzy=True, genres=["Action"],
            year_from=2000, year_to=2020,
        )
        result = await svc.search_all(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_all_sort_by_release_date(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        from pyrate.schemas.search import SearchSortBy
        req = SearchRequest(
            query="Test", search_type=SearchType.ALL,
            sort_by=SearchSortBy.RELEASE_DATE,
        )
        result = await svc.search_all(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_all_sort_by_created_at(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        from pyrate.schemas.search import SearchSortBy
        req = SearchRequest(
            query="Test", search_type=SearchType.ALL,
            sort_by=SearchSortBy.CREATED_AT,
        )
        result = await svc.search_all(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_all_exception(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(side_effect=Exception("search failed"))
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc.search_all(req)
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_shows_sort_by_release_date(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=0)
        )
        from pyrate.schemas.search import SearchSortBy
        req = SearchRequest(
            query="Test", search_type=SearchType.SHOWS,
            sort_by=SearchSortBy.RELEASE_DATE,
        )
        result = await svc.search_shows(req)
        assert result is not None

    @pytest.mark.asyncio
    async def test_search_movies_hit_without_id(self):
        svc = _make_es_service()
        hit = _make_hit("Movie", has_id=False)
        svc.client.search = AsyncMock(
            return_value=_make_search_response([hit], total=1)
        )
        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc.search_movies(req)
        assert result["total"] == 1
        assert "guid" not in result["hits"][0]

    @pytest.mark.asyncio
    async def test_search_movies_pagination(self):
        svc = _make_es_service()
        svc.client.search = AsyncMock(
            return_value=_make_search_response([], total=50)
        )
        req = SearchRequest(
            query="Test", search_type=SearchType.MOVIES,
            page=3, per_page=10,
        )
        result = await svc.search_movies(req)
        assert result["page"] == 3
        assert result["per_page"] == 10
        assert result["total_pages"] == 5


# ---------------------------------------------------------------------------
# Elasticsearch: Delete
# ---------------------------------------------------------------------------


class TestElasticsearchDelete:
    @pytest.mark.asyncio
    async def test_delete_movie_success(self):
        svc = _make_es_service()
        result = await svc.delete_movie(uuid.uuid4())
        assert result is True
        svc.client.delete.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_movie_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.delete_movie(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_movie_not_found(self):
        from elasticsearch.exceptions import NotFoundError

        svc = _make_es_service()
        svc.client.delete = AsyncMock(
            side_effect=NotFoundError(404, "not found", {})
        )
        result = await svc.delete_movie(uuid.uuid4())
        assert result is True  # Not found is considered OK

    @pytest.mark.asyncio
    async def test_delete_movie_exception(self):
        svc = _make_es_service()
        svc.client.delete = AsyncMock(side_effect=Exception("error"))
        result = await svc.delete_movie(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_show_success(self):
        svc = _make_es_service()
        result = await svc.delete_show(uuid.uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_show_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.delete_show(uuid.uuid4())
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_show_not_found(self):
        from elasticsearch.exceptions import NotFoundError

        svc = _make_es_service()
        svc.client.delete = AsyncMock(
            side_effect=NotFoundError(404, "not found", {})
        )
        result = await svc.delete_show(uuid.uuid4())
        assert result is True

    @pytest.mark.asyncio
    async def test_delete_show_exception(self):
        svc = _make_es_service()
        svc.client.delete = AsyncMock(side_effect=Exception("error"))
        result = await svc.delete_show(uuid.uuid4())
        assert result is False


# ---------------------------------------------------------------------------
# Elasticsearch: Bulk Index
# ---------------------------------------------------------------------------


class TestElasticsearchBulkIndex:
    @pytest.mark.asyncio
    async def test_bulk_index_movies_success(self):
        svc = _make_es_service()
        movies = [_make_movie_mock(title=f"Movie {i}") for i in range(3)]
        svc.client.bulk = AsyncMock(
            return_value={
                "items": [
                    {"index": {"status": 201}},
                    {"index": {"status": 200}},
                    {"index": {"status": 201}},
                ]
            }
        )
        result = await svc.bulk_index_movies(movies)
        assert result["success"] == 3
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_index_movies_partial_failure(self):
        svc = _make_es_service()
        movies = [_make_movie_mock(title=f"Movie {i}") for i in range(2)]
        svc.client.bulk = AsyncMock(
            return_value={
                "items": [
                    {"index": {"status": 201}},
                    {"index": {"status": 500, "error": "something"}},
                ]
            }
        )
        result = await svc.bulk_index_movies(movies)
        assert result["success"] == 1
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_bulk_index_movies_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.bulk_index_movies([_make_movie_mock()])
        assert result == {"success": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_bulk_index_movies_empty_list(self):
        svc = _make_es_service()
        result = await svc.bulk_index_movies([])
        assert result == {"success": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_bulk_index_movies_exception(self):
        svc = _make_es_service()
        svc.client.bulk = AsyncMock(side_effect=Exception("bulk failed"))
        movies = [_make_movie_mock()]
        result = await svc.bulk_index_movies(movies)
        assert result["success"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_bulk_index_shows_success(self):
        svc = _make_es_service()
        shows = [_make_show_mock(title=f"Show {i}") for i in range(2)]
        svc.client.bulk = AsyncMock(
            return_value={
                "items": [
                    {"index": {"status": 201}},
                    {"index": {"status": 200}},
                ]
            }
        )
        result = await svc.bulk_index_shows(shows)
        assert result["success"] == 2
        assert result["failed"] == 0

    @pytest.mark.asyncio
    async def test_bulk_index_shows_no_client(self):
        svc = _make_es_service(with_client=False)
        result = await svc.bulk_index_shows([_make_show_mock()])
        assert result == {"success": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_bulk_index_shows_empty_list(self):
        svc = _make_es_service()
        result = await svc.bulk_index_shows([])
        assert result == {"success": 0, "failed": 0}

    @pytest.mark.asyncio
    async def test_bulk_index_shows_exception(self):
        svc = _make_es_service()
        svc.client.bulk = AsyncMock(side_effect=Exception("bulk failed"))
        shows = [_make_show_mock()]
        result = await svc.bulk_index_shows(shows)
        assert result["success"] == 0
        assert result["failed"] == 1

    @pytest.mark.asyncio
    async def test_bulk_index_movies_no_dates(self):
        svc = _make_es_service()
        movie = _make_movie_mock(
            release_date=None, created_at=None, updated_at=None,
        )
        svc.client.bulk = AsyncMock(
            return_value={"items": [{"index": {"status": 201}}]}
        )
        result = await svc.bulk_index_movies([movie])
        assert result["success"] == 1


# ==========================================================================
# SearchService
# ==========================================================================


def _make_search_service():
    """Create a SearchService with mocked dependencies."""
    db = AsyncMock()
    with patch("pyrate.services.search.SettingsService"):
        from pyrate.services.search import SearchService
        svc = SearchService(db)
    svc._settings_service = AsyncMock()
    return svc


class TestSearchServiceInit:
    def test_init(self):
        db = AsyncMock()
        with patch("pyrate.services.search.SettingsService"):
            from pyrate.services.search import SearchService
            svc = SearchService(db)
        assert svc.db is db
        assert svc._tmdb is None
        assert svc._igdb is None
        assert svc._spotify is None
        assert svc._active_library_types is None
        assert svc._redis is None


class TestSearchServiceGetRedis:
    @pytest.mark.asyncio
    async def test_get_redis_creates_connection(self):
        svc = _make_search_service()
        with patch("pyrate.services.search.aioredis") as mock_redis:
            mock_conn = AsyncMock()
            mock_redis.from_url.return_value = mock_conn
            result = await svc._get_redis()
            assert result is mock_conn
            mock_redis.from_url.assert_called_once()

    @pytest.mark.asyncio
    async def test_get_redis_returns_cached(self):
        svc = _make_search_service()
        mock_conn = AsyncMock()
        svc._redis = mock_conn
        result = await svc._get_redis()
        assert result is mock_conn


class TestSearchServiceAcquireImportLock:
    @pytest.mark.asyncio
    async def test_acquire_lock_success(self):
        svc = _make_search_service()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=True)
        svc._redis = mock_redis
        result = await svc._acquire_import_lock("MOVIES", 12345)
        assert result is True

    @pytest.mark.asyncio
    async def test_acquire_lock_already_exists(self):
        svc = _make_search_service()
        mock_redis = AsyncMock()
        mock_redis.set = AsyncMock(return_value=None)
        svc._redis = mock_redis
        result = await svc._acquire_import_lock("MOVIES", 12345)
        assert result is False


class TestSearchServiceGetClients:
    @pytest.mark.asyncio
    async def test_get_tmdb_client_no_key(self):
        svc = _make_search_service()
        svc._settings_service.get_tmdb_api_key = AsyncMock(return_value=None)
        result = await svc._get_tmdb_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_tmdb_client_with_key(self):
        svc = _make_search_service()
        svc._settings_service.get_tmdb_api_key = AsyncMock(
            return_value="test-api-key-12345678"
        )
        with patch("pyrate.services.search.TMDB") as MockTMDB:
            mock_tmdb = MagicMock()
            MockTMDB.return_value = mock_tmdb
            result = await svc._get_tmdb_client()
            assert result is mock_tmdb
            MockTMDB.assert_called_once_with(api_key="test-api-key-12345678")

    @pytest.mark.asyncio
    async def test_get_tmdb_client_cached(self):
        svc = _make_search_service()
        mock_tmdb = MagicMock()
        svc._tmdb = mock_tmdb
        result = await svc._get_tmdb_client()
        assert result is mock_tmdb

    @pytest.mark.asyncio
    async def test_get_igdb_client_no_credentials(self):
        svc = _make_search_service()
        svc._settings_service.get_igdb_credentials = AsyncMock(
            return_value=(None, None)
        )
        result = await svc._get_igdb_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_igdb_client_with_credentials(self):
        svc = _make_search_service()
        svc._settings_service.get_igdb_credentials = AsyncMock(
            return_value=("client_id", "client_secret")
        )
        with patch("pyrate.services.search.IGDB") as MockIGDB:
            mock_igdb = MagicMock()
            MockIGDB.return_value = mock_igdb
            result = await svc._get_igdb_client()
            assert result is mock_igdb

    @pytest.mark.asyncio
    async def test_get_igdb_client_cached(self):
        svc = _make_search_service()
        mock_igdb = MagicMock()
        svc._igdb = mock_igdb
        result = await svc._get_igdb_client()
        assert result is mock_igdb

    @pytest.mark.asyncio
    async def test_get_spotify_client_no_credentials(self):
        svc = _make_search_service()
        svc._settings_service.get_spotify_credentials = AsyncMock(
            return_value=(None, None)
        )
        result = await svc._get_spotify_client()
        assert result is None

    @pytest.mark.asyncio
    async def test_get_spotify_client_with_credentials(self):
        svc = _make_search_service()
        svc._settings_service.get_spotify_credentials = AsyncMock(
            return_value=("client_id", "client_secret")
        )
        with patch("pyrate.services.search.Spotify") as MockSpotify:
            mock_spotify = MagicMock()
            MockSpotify.return_value = mock_spotify
            result = await svc._get_spotify_client()
            assert result is mock_spotify

    @pytest.mark.asyncio
    async def test_get_spotify_client_cached(self):
        svc = _make_search_service()
        mock_spotify = MagicMock()
        svc._spotify = mock_spotify
        result = await svc._get_spotify_client()
        assert result is mock_spotify


class TestSearchServiceActiveLibraryTypes:
    @pytest.mark.asyncio
    async def test_get_active_library_types(self):
        svc = _make_search_service()
        mock_result = MagicMock()
        mock_result.fetchall.return_value = [("movies",), ("shows",)]
        svc.db.execute = AsyncMock(return_value=mock_result)
        result = await svc._get_active_library_types()
        assert result == {"MOVIES", "SHOWS"}

    @pytest.mark.asyncio
    async def test_get_active_library_types_cached(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES"}
        result = await svc._get_active_library_types()
        assert result == {"MOVIES"}
        svc.db.execute.assert_not_awaited()


class TestSearchServiceShouldSearch:
    @pytest.mark.asyncio
    async def test_should_search_movies_yes(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES", "SHOWS"}
        assert await svc._should_search_movies(SearchType.ALL) is True
        assert await svc._should_search_movies(SearchType.MOVIES) is True

    @pytest.mark.asyncio
    async def test_should_search_movies_no_for_other_types(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES"}
        assert await svc._should_search_movies(SearchType.SHOWS) is False
        assert await svc._should_search_movies(SearchType.GAMES) is False
        assert await svc._should_search_movies(SearchType.MUSIC) is False

    @pytest.mark.asyncio
    async def test_should_search_movies_no_library(self):
        svc = _make_search_service()
        svc._active_library_types = {"SHOWS"}
        assert await svc._should_search_movies(SearchType.ALL) is False

    @pytest.mark.asyncio
    async def test_should_search_shows(self):
        svc = _make_search_service()
        svc._active_library_types = {"SHOWS"}
        assert await svc._should_search_shows(SearchType.ALL) is True
        assert await svc._should_search_shows(SearchType.SHOWS) is True
        assert await svc._should_search_shows(SearchType.MOVIES) is False
        assert await svc._should_search_shows(SearchType.GAMES) is False

    @pytest.mark.asyncio
    async def test_should_search_games(self):
        svc = _make_search_service()
        svc._active_library_types = {"GAMES"}
        assert await svc._should_search_games(SearchType.ALL) is True
        assert await svc._should_search_games(SearchType.GAMES) is True
        assert await svc._should_search_games(SearchType.MOVIES) is False
        assert await svc._should_search_games(SearchType.SHOWS) is False

    @pytest.mark.asyncio
    async def test_should_search_music(self):
        svc = _make_search_service()
        svc._active_library_types = {"MUSIC"}
        assert await svc._should_search_music(SearchType.ALL) is True
        assert await svc._should_search_music(SearchType.MUSIC) is True
        assert await svc._should_search_music(SearchType.MOVIES) is False


class TestSearchServiceClose:
    @pytest.mark.asyncio
    async def test_close_all_clients(self):
        svc = _make_search_service()
        svc._tmdb = AsyncMock()
        svc._igdb = AsyncMock()
        svc._spotify = AsyncMock()
        svc._redis = AsyncMock()
        await svc.close()
        svc._tmdb is None
        svc._igdb is None
        svc._spotify is None
        svc._redis is None

    @pytest.mark.asyncio
    async def test_close_no_clients(self):
        svc = _make_search_service()
        await svc.close()  # Should not raise


class TestSearchServiceTransformers:
    def test_transform_tmdb_movie(self):
        svc = _make_search_service()
        movie = {
            "id": 123,
            "title": "Test Movie",
            "original_title": "Test Movie",
            "overview": "A test",
            "poster_path": "/test.jpg",
            "backdrop_path": "/backdrop.jpg",
            "release_date": "2020-01-15",
            "genre_ids": [28, 12],
            "popularity": 150.0,
            "vote_average": 7.5,
            "vote_count": 1000,
        }
        result = svc._transform_tmdb_movie(movie, 0)
        assert result["tmdb_id"] == 123
        assert result["title"] == "Test Movie"
        assert result["type"] == SearchType.MOVIES
        assert result["source"] == "tmdb"
        assert result["score"] > 0
        assert result["in_library"] is False

    def test_transform_tmdb_movie_high_index_lower_score(self):
        svc = _make_search_service()
        movie = {"id": 1, "title": "Movie", "popularity": 50.0}
        result0 = svc._transform_tmdb_movie(movie, 0)
        result10 = svc._transform_tmdb_movie(movie, 10)
        assert result0["score"] > result10["score"]

    def test_transform_tmdb_show(self):
        svc = _make_search_service()
        show = {
            "id": 456,
            "name": "Test Show",
            "original_name": "Test Show Original",
            "overview": "A test show",
            "poster_path": "/poster.jpg",
            "backdrop_path": "/backdrop.jpg",
            "first_air_date": "2020-03-15",
            "genre_ids": [18],
            "popularity": 100.0,
            "vote_average": 8.0,
            "vote_count": 500,
        }
        result = svc._transform_tmdb_show(show, 0)
        assert result["tmdb_id"] == 456
        assert result["title"] == "Test Show"
        assert result["type"] == SearchType.SHOWS
        assert result["first_air_date"] == "2020-03-15"

    def test_transform_igdb_game(self):
        svc = _make_search_service()
        game = {
            "id": 789,
            "name": "Test Game",
            "summary": "A test game",
            "rating": 85.0,
            "rating_count": 200,
            "cover": {"image_id": "abc123"},
            "first_release_date": 1577836800,  # 2020-01-01
            "genres": [{"name": "Action"}, {"name": "RPG"}],
        }
        result = svc._transform_igdb_game(game, 0)
        assert result["igdb_id"] == 789
        assert result["type"] == SearchType.GAMES
        assert result["genres"] == ["Action", "RPG"]
        assert result["poster_path"] is not None
        assert "abc123" in result["poster_path"]

    def test_transform_igdb_game_no_cover(self):
        svc = _make_search_service()
        game = {"id": 1, "name": "Game", "rating": 50.0}
        result = svc._transform_igdb_game(game, 0)
        assert result["poster_path"] is None

    def test_transform_spotify_album(self):
        svc = _make_search_service()
        album = {
            "id": "album123",
            "name": "Test Album",
            "popularity": 80,
            "images": [{"url": "https://example.com/image.jpg"}],
            "artists": [{"name": "Artist 1"}],
            "release_date": "2020-05-01",
            "album_type": "album",
            "total_tracks": 12,
        }
        result = svc._transform_spotify_album(album, 0)
        assert result["spotify_id"] == "album123"
        assert result["type"] == SearchType.MUSIC
        assert result["description"] == "Artist 1"
        assert result["poster_path"] == "https://example.com/image.jpg"

    def test_transform_spotify_artist(self):
        svc = _make_search_service()
        artist = {
            "id": "artist123",
            "name": "Test Artist",
            "popularity": 90,
            "images": [{"url": "https://example.com/artist.jpg"}],
            "genres": ["pop", "rock"],
        }
        result = svc._transform_spotify_artist(artist, 0)
        assert result["spotify_id"] == "artist123"
        assert result["genres"] == ["pop", "rock"]
        assert result["music_type"] == "artist"

    def test_transform_spotify_track(self):
        svc = _make_search_service()
        track = {
            "id": "track123",
            "name": "Test Track",
            "popularity": 70,
            "artists": [{"name": "Artist 1"}, {"name": "Artist 2"}],
            "album": {
                "id": "album456",
                "images": [{"url": "https://example.com/album.jpg"}],
                "release_date": "2020-05-01",
            },
        }
        result = svc._transform_spotify_track(track, 0)
        assert result["spotify_id"] == "track123"
        assert result["album_spotify_id"] == "album456"
        assert result["music_type"] == "track"
        assert result["description"] == "Artist 1, Artist 2"


class TestSearchServiceSearchMethods:
    @pytest.mark.asyncio
    async def test_search_tmdb_movies(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(
            return_value={
                "results": [
                    {"id": 1, "title": "Movie 1", "popularity": 100},
                    {"id": 2, "title": "Movie 2", "popularity": 80},
                ],
                "total_results": 2,
            }
        )
        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc._search_tmdb_movies(mock_tmdb, req)
        assert result["total"] == 2
        assert len(result["hits"]) == 2

    @pytest.mark.asyncio
    async def test_search_tmdb_movies_with_year(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(
            return_value={"results": [], "total_results": 0}
        )
        req = SearchRequest(
            query="Movie", search_type=SearchType.MOVIES,
            year_from=2020, year_to=2020,
        )
        result = await svc._search_tmdb_movies(mock_tmdb, req)
        mock_tmdb.search_movies.assert_awaited_once_with("Movie", year=2020)

    @pytest.mark.asyncio
    async def test_search_tmdb_movies_no_results_key(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(return_value={})
        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc._search_tmdb_movies(mock_tmdb, req)
        assert result["hits"] == []
        assert result["total"] == 0

    @pytest.mark.asyncio
    async def test_search_tmdb_movies_exception(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb.search_movies = AsyncMock(side_effect=ConnectionError("API error"))
        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc._search_tmdb_movies(mock_tmdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_tmdb_shows(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb._request = AsyncMock(
            return_value={
                "results": [{"id": 1, "name": "Show 1", "popularity": 80}],
                "total_results": 1,
            }
        )
        req = SearchRequest(query="Show", search_type=SearchType.SHOWS)
        result = await svc._search_tmdb_shows(mock_tmdb, req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_tmdb_shows_no_results(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb._request = AsyncMock(return_value=None)
        req = SearchRequest(query="Show", search_type=SearchType.SHOWS)
        result = await svc._search_tmdb_shows(mock_tmdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_tmdb_shows_exception(self):
        svc = _make_search_service()
        mock_tmdb = AsyncMock()
        mock_tmdb._request = AsyncMock(side_effect=ConnectionError("API error"))
        req = SearchRequest(query="Show", search_type=SearchType.SHOWS)
        result = await svc._search_tmdb_shows(mock_tmdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_igdb_games(self):
        svc = _make_search_service()
        mock_igdb = AsyncMock()
        mock_igdb.search_games = AsyncMock(
            return_value=[
                {"id": 1, "name": "Game 1", "rating": 80},
                {"id": 2, "name": "Game 2", "rating": 70},
            ]
        )
        req = SearchRequest(query="Game", search_type=SearchType.GAMES)
        result = await svc._search_igdb_games(mock_igdb, req)
        assert result["total"] == 2

    @pytest.mark.asyncio
    async def test_search_igdb_games_empty(self):
        svc = _make_search_service()
        mock_igdb = AsyncMock()
        mock_igdb.search_games = AsyncMock(return_value=[])
        req = SearchRequest(query="Game", search_type=SearchType.GAMES)
        result = await svc._search_igdb_games(mock_igdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_igdb_games_exception(self):
        svc = _make_search_service()
        mock_igdb = AsyncMock()
        mock_igdb.search_games = AsyncMock(side_effect=ConnectionError("API error"))
        req = SearchRequest(query="Game", search_type=SearchType.GAMES)
        result = await svc._search_igdb_games(mock_igdb, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_spotify_albums(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_albums = AsyncMock(
            return_value=[
                {"id": "a1", "name": "Album 1", "popularity": 80, "images": [], "artists": []},
            ]
        )
        req = SearchRequest(query="Album", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_albums(mock_spotify, req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_spotify_albums_empty(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_albums = AsyncMock(return_value=[])
        req = SearchRequest(query="Album", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_albums(mock_spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_spotify_artists(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_artists = AsyncMock(
            return_value=[
                {"id": "ar1", "name": "Artist 1", "popularity": 90, "images": [], "genres": []},
            ]
        )
        req = SearchRequest(query="Artist", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_artists(mock_spotify, req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_spotify_tracks(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_tracks = AsyncMock(
            return_value=[
                {
                    "id": "t1", "name": "Track 1", "popularity": 70,
                    "artists": [], "album": {"id": "a1", "images": []},
                },
            ]
        )
        req = SearchRequest(query="Track", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_tracks(mock_spotify, req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_spotify_tracks_empty(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_tracks = AsyncMock(return_value=None)
        req = SearchRequest(query="Track", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_tracks(mock_spotify, req)
        assert result["hits"] == []

    @pytest.mark.asyncio
    async def test_search_spotify_tracks_exception(self):
        svc = _make_search_service()
        mock_spotify = AsyncMock()
        mock_spotify.search_tracks = AsyncMock(side_effect=ConnectionError("API error"))
        req = SearchRequest(query="Track", search_type=SearchType.MUSIC)
        result = await svc._search_spotify_tracks(mock_spotify, req)
        assert result["hits"] == []


class TestSearchServiceMainSearch:
    @pytest.mark.asyncio
    async def test_search_returns_provider_results(self):
        svc = _make_search_service()
        provider_result = {
            "hits": [{"title": "Movie 1", "tmdb_id": 1, "type": SearchType.MOVIES}],
            "total": 1,
            "page": 1,
            "per_page": 20,
            "total_pages": 1,
            "query": "Movie",
            "search_type": SearchType.MOVIES,
        }
        svc._search_provider = AsyncMock(return_value=provider_result)
        svc._queue_imports = AsyncMock()

        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc.search(req)
        assert result["total"] == 1
        svc._queue_imports.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_no_queue_import(self):
        svc = _make_search_service()
        provider_result = {
            "hits": [{"title": "Movie 1"}],
            "total": 1,
        }
        svc._search_provider = AsyncMock(return_value=provider_result)
        svc._queue_imports = AsyncMock()

        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc.search(req, queue_import=False)
        svc._queue_imports.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_search_falls_back_to_local(self):
        svc = _make_search_service()
        svc._search_provider = AsyncMock(return_value=None)
        local_result = {
            "hits": [], "total": 0, "page": 1, "per_page": 20,
            "total_pages": 0, "query": "Movie", "search_type": SearchType.MOVIES,
        }
        svc._search_local = AsyncMock(return_value=local_result)

        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc.search(req)
        svc._search_local.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_provider_exception_falls_back(self):
        svc = _make_search_service()
        svc._search_provider = AsyncMock(side_effect=ConnectionError("Provider down"))
        local_result = {
            "hits": [], "total": 0, "page": 1, "per_page": 20,
            "total_pages": 0, "query": "Movie", "search_type": SearchType.MOVIES,
        }
        svc._search_local = AsyncMock(return_value=local_result)

        req = SearchRequest(query="Movie", search_type=SearchType.MOVIES)
        result = await svc.search(req)
        svc._search_local.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_provider_empty_hits(self):
        svc = _make_search_service()
        svc._search_provider = AsyncMock(return_value={"hits": [], "total": 0})
        local_result = {
            "hits": [], "total": 0, "page": 1, "per_page": 20,
            "total_pages": 0, "query": "Test", "search_type": SearchType.ALL,
        }
        svc._search_local = AsyncMock(return_value=local_result)

        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc.search(req)
        svc._search_local.assert_awaited_once()


class TestSearchServiceSearchLocal:
    @pytest.mark.asyncio
    async def test_search_local_movies(self):
        svc = _make_search_service()
        mock_es = AsyncMock()
        mock_es.search_movies = AsyncMock(
            return_value={"hits": [], "total": 0}
        )
        with patch("pyrate.services.search.elasticsearch_service", mock_es):
            req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
            result = await svc._search_local(req)
        assert result["source"] == "local"
        assert result["provider"] == "elasticsearch"

    @pytest.mark.asyncio
    async def test_search_local_shows(self):
        svc = _make_search_service()
        mock_es = AsyncMock()
        mock_es.search_shows = AsyncMock(
            return_value={"hits": [], "total": 0}
        )
        with patch("pyrate.services.search.elasticsearch_service", mock_es):
            req = SearchRequest(query="Test", search_type=SearchType.SHOWS)
            result = await svc._search_local(req)
        assert result["source"] == "local"

    @pytest.mark.asyncio
    async def test_search_local_all(self):
        svc = _make_search_service()
        mock_es = AsyncMock()
        mock_es.search_all = AsyncMock(
            return_value={"hits": [], "total": 0}
        )
        with patch("pyrate.services.search.elasticsearch_service", mock_es):
            req = SearchRequest(query="Test", search_type=SearchType.ALL)
            result = await svc._search_local(req)
        assert result["source"] == "local"

    @pytest.mark.asyncio
    async def test_search_local_exception(self):
        svc = _make_search_service()
        mock_es = AsyncMock()
        mock_es.search_all = AsyncMock(side_effect=ConnectionError("ES down"))
        with patch("pyrate.services.search.elasticsearch_service", mock_es):
            req = SearchRequest(query="Test", search_type=SearchType.ALL)
            result = await svc._search_local(req)
        assert result["total"] == 0
        assert result["source"] == "local"
        assert "error" in result


class TestSearchServiceSearchProvider:
    @pytest.mark.asyncio
    async def test_search_provider_no_active_libraries(self):
        svc = _make_search_service()
        svc._active_library_types = set()
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc._search_provider(req)
        assert result["total"] == 0
        assert result["message"] is not None

    @pytest.mark.asyncio
    async def test_search_provider_movies_and_shows(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES", "SHOWS"}
        mock_tmdb = AsyncMock()
        svc._get_tmdb_client = AsyncMock(return_value=mock_tmdb)
        svc._search_tmdb_movies = AsyncMock(
            return_value={"hits": [{"title": "M1", "score": 5}], "total": 1}
        )
        svc._search_tmdb_shows = AsyncMock(
            return_value={"hits": [{"title": "S1", "score": 4}], "total": 1}
        )
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc._search_provider(req)
        assert result["total"] == 2
        assert len(result["hits"]) == 2

    @pytest.mark.asyncio
    async def test_search_provider_games(self):
        svc = _make_search_service()
        svc._active_library_types = {"GAMES"}
        mock_igdb = AsyncMock()
        svc._get_igdb_client = AsyncMock(return_value=mock_igdb)
        svc._search_igdb_games = AsyncMock(
            return_value={"hits": [{"title": "G1"}], "total": 1}
        )
        req = SearchRequest(query="Game", search_type=SearchType.GAMES)
        result = await svc._search_provider(req)
        assert result["total"] == 1

    @pytest.mark.asyncio
    async def test_search_provider_music(self):
        """Music search returns only artists."""
        svc = _make_search_service()
        svc._active_library_types = {"MUSIC"}
        mock_spotify = AsyncMock()
        svc._get_spotify_client = AsyncMock(return_value=mock_spotify)
        svc._search_spotify_artists = AsyncMock(
            return_value={"hits": [{"title": "A1"}], "total": 1}
        )
        req = SearchRequest(query="Music", search_type=SearchType.MUSIC)
        result = await svc._search_provider(req)
        assert result["total"] == 1
        assert result["hits"][0]["title"] == "A1"

    @pytest.mark.asyncio
    async def test_search_provider_no_clients_available(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES"}
        svc._get_tmdb_client = AsyncMock(return_value=None)
        req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        result = await svc._search_provider(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_search_provider_exception(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES"}
        svc._get_tmdb_client = AsyncMock(side_effect=ConnectionError("Error"))
        req = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        result = await svc._search_provider(req)
        assert result is None

    @pytest.mark.asyncio
    async def test_search_provider_sorts_all_by_score(self):
        svc = _make_search_service()
        svc._active_library_types = {"MOVIES", "SHOWS"}
        mock_tmdb = AsyncMock()
        svc._get_tmdb_client = AsyncMock(return_value=mock_tmdb)
        svc._search_tmdb_movies = AsyncMock(
            return_value={"hits": [{"title": "M1", "score": 3}], "total": 1}
        )
        svc._search_tmdb_shows = AsyncMock(
            return_value={"hits": [{"title": "S1", "score": 8}], "total": 1}
        )
        req = SearchRequest(query="Test", search_type=SearchType.ALL)
        result = await svc._search_provider(req)
        assert result["hits"][0]["title"] == "S1"
