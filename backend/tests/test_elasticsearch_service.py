"""Tests for ElasticsearchService (mocked AsyncElasticsearch client)."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch, PropertyMock

import pytest
import pytest_asyncio

from pyrate.services.elasticsearch import ElasticsearchService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def service() -> ElasticsearchService:
    svc = ElasticsearchService()
    svc.index_prefix = "test_pyrate"

    mock_client = AsyncMock()
    mock_client.ping = AsyncMock(return_value=True)
    mock_client.close = AsyncMock()

    # Index operations
    mock_indices = AsyncMock()
    mock_indices.exists = AsyncMock(return_value=False)
    mock_indices.create = AsyncMock()
    mock_client.indices = mock_indices

    # Document operations
    mock_client.index = AsyncMock(return_value={"result": "created"})
    mock_client.search = AsyncMock(
        return_value={
            "hits": {
                "total": {"value": 1},
                "hits": [
                    {
                        "_id": "abc123",
                        "_source": {
                            "id": "abc123",
                            "title": "Test Movie",
                            "description": "A test movie",
                        },
                    }
                ],
            }
        }
    )

    svc.client = mock_client
    return svc


# ---------------------------------------------------------------------------
# Initialize and close
# ---------------------------------------------------------------------------

class TestLifecycle:
    @pytest.mark.asyncio
    async def test_close(self, service: ElasticsearchService):
        await service.close()
        service.client.close.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_close_no_client(self):
        svc = ElasticsearchService()
        svc.client = None
        await svc.close()  # Should not raise


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

class TestIndexing:
    @pytest.mark.asyncio
    async def test_index_movie(self, service: ElasticsearchService):
        movie = MagicMock()
        movie.guid = uuid.uuid4()
        movie.title = "Inception"
        movie.original_title = "Inception"
        movie.description = "A mind-bending thriller"
        movie.tagline = "Your mind is the scene of the crime"
        movie.release_date = datetime(2010, 7, 16, tzinfo=UTC)
        movie.poster_path = "/poster.jpg"
        movie.backdrop_path = "/backdrop.jpg"
        movie.availability_status = "available"
        movie.genres = []
        movie.external_ids = []
        movie.created_at = datetime.now(UTC)
        movie.updated_at = datetime.now(UTC)

        result = await service.index_movie(movie)
        assert result is True
        service.client.index.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_index_movie_no_client(self):
        svc = ElasticsearchService()
        svc.client = None
        movie = MagicMock()
        result = await svc.index_movie(movie)
        assert result is False

    @pytest.mark.asyncio
    async def test_index_show(self, service: ElasticsearchService):
        show = MagicMock()
        show.guid = uuid.uuid4()
        show.title = "Breaking Bad"
        show.original_title = "Breaking Bad"
        show.description = "A chemistry teacher turns to crime"
        show.tagline = None
        show.release_date = datetime(2008, 1, 20, tzinfo=UTC)
        show.poster_path = "/poster.jpg"
        show.backdrop_path = "/backdrop.jpg"
        show.availability_status = "available"
        show.genres = []
        show.external_ids = []
        show.extra_data = None
        show.created_at = datetime.now(UTC)
        show.updated_at = datetime.now(UTC)

        result = await service.index_show(show)
        assert result is True
        service.client.index.assert_awaited_once()


# ---------------------------------------------------------------------------
# Search
# ---------------------------------------------------------------------------

class TestSearch:
    @pytest.mark.asyncio
    async def test_search_movies(self, service: ElasticsearchService):
        from pyrate.schemas.search import SearchRequest, SearchType

        request = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        results = await service.search_movies(request)
        assert results is not None
        service.client.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_shows(self, service: ElasticsearchService):
        from pyrate.schemas.search import SearchRequest, SearchType

        request = SearchRequest(query="Breaking", search_type=SearchType.SHOWS)
        results = await service.search_shows(request)
        assert results is not None
        service.client.search.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_search_no_client(self):
        svc = ElasticsearchService()
        svc.client = None
        from pyrate.schemas.search import SearchRequest, SearchType

        request = SearchRequest(query="Test", search_type=SearchType.MOVIES)
        results = await svc.search_movies(request)
        assert isinstance(results, dict)
        assert results["hits"] == []
        assert results["total"] == 0
