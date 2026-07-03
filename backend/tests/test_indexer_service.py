"""Tests for IndexerService (search across indexers, deduplication)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.indexer import Indexer, IndexerCategory
from pyrate.services.indexer import IndexerService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def indexer_with_categories(db_session: AsyncSession) -> Indexer:
    """Create an indexer with movie and show categories."""
    indexer = Indexer(
        guid=uuid.uuid4(),
        label="Test Indexer",
        host="https://indexer.example.com",
        api_key="test-api-key",
        type="newznab",
        ssl=True,
    )
    db_session.add(indexer)
    await db_session.flush()

    movie_cat = IndexerCategory(
        guid=uuid.uuid4(),
        indexer_guid=indexer.guid,
        label="Movies",
        category_type="movie",
        newznab_category_id=2000,
    )
    show_cat = IndexerCategory(
        guid=uuid.uuid4(),
        indexer_guid=indexer.guid,
        label="TV Shows",
        category_type="show",
        newznab_category_id=5000,
    )
    db_session.add_all([movie_cat, show_cat])
    await db_session.commit()
    await db_session.refresh(indexer)
    return indexer


# ---------------------------------------------------------------------------
# Deduplication (pure logic, no DB needed)
# ---------------------------------------------------------------------------

class TestDeduplicateReleases:
    def test_removes_duplicates(self):
        service = IndexerService.__new__(IndexerService)  # bypass __init__
        releases = [
            {"title": "Movie.2024.1080p.BluRay", "size": 5000},
            {"title": "Movie.2024.1080p.BluRay", "size": 5000},
            {"title": "Movie.2024.720p.WEB", "size": 2000},
        ]
        result = service.deduplicate_releases(releases)
        assert len(result) == 2

    def test_keeps_different_sizes(self):
        service = IndexerService.__new__(IndexerService)
        releases = [
            {"title": "Movie.2024.1080p.BluRay", "size": 5000},
            {"title": "Movie.2024.1080p.BluRay", "size": 6000},
        ]
        result = service.deduplicate_releases(releases)
        assert len(result) == 2

    def test_empty_list(self):
        service = IndexerService.__new__(IndexerService)
        result = service.deduplicate_releases([])
        assert result == []

    def test_case_insensitive(self):
        service = IndexerService.__new__(IndexerService)
        releases = [
            {"title": "movie.2024.1080p", "size": 5000},
            {"title": "Movie.2024.1080p", "size": 5000},
        ]
        result = service.deduplicate_releases(releases)
        assert len(result) == 1


# ---------------------------------------------------------------------------
# Category helpers (pure logic)
# ---------------------------------------------------------------------------

class TestCategoryHelpers:
    def test_get_category_ids_for_type(self, db_session: AsyncSession):
        service = IndexerService.__new__(IndexerService)

        # Create fake indexer with categories
        cat1 = MagicMock()
        cat1.category_type = "movie"
        cat1.newznab_category_id = 2000
        cat1.language = None
        cat1.resolution = None

        cat2 = MagicMock()
        cat2.category_type = "movie"
        cat2.newznab_category_id = 2040
        cat2.language = None
        cat2.resolution = None

        indexer = MagicMock()
        indexer.categories = [cat1, cat2]

        result = service._get_category_ids_for_type(indexer, "movie")
        assert result == "2000,2040"

    def test_get_category_ids_no_match(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.categories = []
        result = service._get_category_ids_for_type(indexer, "game")
        assert result is None

    def test_get_language_hints(self):
        service = IndexerService.__new__(IndexerService)
        cat = MagicMock()
        cat.category_type = "movie"
        cat.language = ["en", "de"]
        indexer = MagicMock()
        indexer.categories = [cat]

        result = service._get_language_hints_for_type(indexer, "movie")
        assert "en" in result
        assert "de" in result

    def test_get_resolution_hints(self):
        service = IndexerService.__new__(IndexerService)
        cat = MagicMock()
        cat.category_type = "movie"
        cat.resolution = ["1080p", "2160p"]
        indexer = MagicMock()
        indexer.categories = [cat]

        result = service._get_resolution_hints_for_type(indexer, "movie")
        assert "1080p" in result
        assert "2160p" in result


# ---------------------------------------------------------------------------
# Indexer client creation
# ---------------------------------------------------------------------------

class TestCreateIndexerClient:
    def test_creates_newznab(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "https://nzb.example.com"
        indexer.api_key = "key123"
        indexer.type = "newznab"
        indexer.ssl = True
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None

    def test_creates_torznab(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "https://torrent.example.com"
        indexer.api_key = "key123"
        indexer.type = "torznab"
        indexer.ssl = True
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None

    def test_unsupported_type_raises(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "https://example.com"
        indexer.api_key = "key"
        indexer.type = "unsupported"
        indexer.ssl = False

        with pytest.raises(ValueError, match="Unsupported indexer type"):
            service._create_indexer_client(indexer)

    def test_host_with_protocol_reuses(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "http://nzb.local"
        indexer.api_key = "key"
        indexer.type = "newznab"
        indexer.ssl = False
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None


# ---------------------------------------------------------------------------
# DB-backed search (mocked indexer clients)
# ---------------------------------------------------------------------------

class TestSearchAcrossIndexers:
    @pytest.mark.asyncio
    async def test_search_movies(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        service = IndexerService(db_session)

        mock_client = AsyncMock()
        mock_client.search_movie = AsyncMock(
            return_value=[{"title": "Test Movie", "size": 5000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_movies(query="Test")

        assert len(results) >= 1
        assert results[0]["title"] == "Test Movie"

    @pytest.mark.asyncio
    async def test_search_returns_empty_when_no_indexers(
        self, db_session: AsyncSession
    ):
        service = IndexerService(db_session)
        results = await service.search_movies(query="Nothing")
        assert results == []

    @pytest.mark.asyncio
    async def test_search_handles_indexer_error(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        service = IndexerService(db_session)

        mock_client = AsyncMock()
        mock_client.search_movie = AsyncMock(side_effect=Exception("Connection failed"))

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_movies(query="Test")

        # Should return empty instead of crashing
        assert results == []

    @pytest.mark.asyncio
    async def test_exception_propagated_in_gather(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        """Covers the isinstance(result, Exception) branch in _search_across_indexers."""
        service = IndexerService(db_session)

        async def raising_search(*args, **kwargs):
            raise RuntimeError("Unexpected failure")

        with patch.object(service, "_search_single_indexer", side_effect=raising_search):
            results = await service.search_movies(query="Test")

        assert results == []

    @pytest.mark.asyncio
    async def test_search_show_content_type(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        """Covers the 'show' branch inside _search_single_indexer."""
        service = IndexerService(db_session)

        mock_client = AsyncMock()
        mock_client.search_show = AsyncMock(
            return_value=[{"title": "Breaking Bad S01E01", "size": 800}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_shows(
                query="Breaking Bad", tvdb_id="81189", season="1", episode="1"
            )

        assert len(results) >= 1
        assert results[0]["title"] == "Breaking Bad S01E01"

    @pytest.mark.asyncio
    async def test_search_game_content_type(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        """Covers the 'game' branch inside _search_single_indexer.
        indexer_with_categories has no game categories, so search_games falls back
        to get_active_indexers() which loads the indexer with selectinload.
        """
        service = IndexerService(db_session)

        mock_client = AsyncMock()
        mock_client.search_game = AsyncMock(
            return_value=[{"title": "Some Game", "size": 10000}]
        )

        # No need to mock get_indexers_by_category: it returns [] for "game"
        # so the fallback to get_active_indexers (with selectinload) fires.
        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_games(query="Some Game")

        assert len(results) >= 1

    @pytest.mark.asyncio
    async def test_unknown_content_type_returns_empty(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        """Covers the else/raise-ValueError branch in _search_single_indexer."""
        service = IndexerService(db_session)
        mock_client = AsyncMock()

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service._search_single_indexer(
                indexer_with_categories, "unknown_type"
            )

        assert results == []

    @pytest.mark.asyncio
    async def test_search_with_lang_and_res_hints(
        self, db_session: AsyncSession
    ):
        """Covers the _category_lang_hints / _category_res_hints annotation block."""
        indexer = Indexer(
            guid=uuid.uuid4(),
            label="Hints Indexer",
            host="https://hints.example.com",
            api_key="hints-key",
            type="newznab",
            ssl=True,
        )
        db_session.add(indexer)
        await db_session.flush()

        movie_cat = IndexerCategory(
            guid=uuid.uuid4(),
            indexer_guid=indexer.guid,
            label="Movies EN 1080p",
            category_type="movie",
            newznab_category_id=2000,
            language=["en"],
            resolution=["1080p"],
        )
        db_session.add(movie_cat)
        await db_session.commit()
        await db_session.refresh(indexer)

        service = IndexerService(db_session)
        mock_client = AsyncMock()
        mock_client.search_movie = AsyncMock(
            return_value=[{"title": "Hinted Movie", "size": 5000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_movies(query="Hinted Movie")

        assert len(results) >= 1
        assert results[0].get("_category_lang_hints") == ["en"]
        assert results[0].get("_category_res_hints") == ["1080p"]


# ---------------------------------------------------------------------------
# _create_indexer_client - additional branches
# ---------------------------------------------------------------------------

class TestCreateIndexerClientAdditional:
    def test_no_protocol_ssl_false_uses_http(self):
        """Covers the else branch when host has no protocol and ssl=False."""
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "nzb.example.com"
        indexer.api_key = "key"
        indexer.type = "newznab"
        indexer.ssl = False
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None

    def test_no_protocol_ssl_true_uses_https(self):
        """Covers the else branch when host has no protocol and ssl=True."""
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "nzb.example.com"
        indexer.api_key = "key"
        indexer.type = "newznab"
        indexer.ssl = True
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None

    def test_string_type_creates_newznab(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "https://nzb.example.com"
        indexer.api_key = "key"
        indexer.type = "string"
        indexer.ssl = True
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None

    def test_empty_type_creates_newznab(self):
        service = IndexerService.__new__(IndexerService)
        indexer = MagicMock()
        indexer.host = "https://nzb.example.com"
        indexer.api_key = "key"
        indexer.type = ""
        indexer.ssl = True
        indexer.guid = uuid.uuid4()

        client = service._create_indexer_client(indexer)
        assert client is not None


# ---------------------------------------------------------------------------
# search_shows / search_games / search_across_all_indexers
# ---------------------------------------------------------------------------

class TestSearchShows:
    async def test_search_shows_no_indexers_returns_empty(self, db_session: AsyncSession):
        """No indexers → fallback to get_active_indexers → still empty → returns []."""
        service = IndexerService(db_session)
        results = await service.search_shows(query="Breaking Bad")
        assert results == []

    async def test_search_shows_no_show_indexers_falls_back_to_all(
        self, db_session: AsyncSession
    ):
        """Covers the fallback path: indexer has no show categories → falls back to
        get_active_indexers() which uses selectinload for safe attribute access.
        """
        # Create an indexer with only movie categories (no show)
        indexer = Indexer(
            guid=uuid.uuid4(),
            label="Movie Only Indexer",
            host="https://movie-only.example.com",
            api_key="key",
            type="newznab",
            ssl=True,
        )
        db_session.add(indexer)
        await db_session.flush()
        cat = IndexerCategory(
            guid=uuid.uuid4(),
            indexer_guid=indexer.guid,
            label="Movies",
            category_type="movie",
            newznab_category_id=2000,
        )
        db_session.add(cat)
        await db_session.commit()

        service = IndexerService(db_session)
        mock_client = AsyncMock()
        mock_client.search_show = AsyncMock(
            return_value=[{"title": "Fallback Show", "size": 500}]
        )

        # No show-specific indexers → falls back to get_active_indexers (selectinload)
        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_shows(query="Show")

        assert len(results) >= 1


class TestSearchGames:
    async def test_search_games_no_indexers_returns_empty(self, db_session: AsyncSession):
        service = IndexerService(db_session)
        results = await service.search_games(query="Some Game")
        assert results == []

    async def test_search_games_no_game_indexers_falls_back_to_all(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        """Covers the fallback path: no game categories → falls back to get_active_indexers
        (which uses selectinload for safe attribute access).
        """
        service = IndexerService(db_session)
        mock_client = AsyncMock()
        mock_client.search_game = AsyncMock(
            return_value=[{"title": "Fallback Game", "size": 9000}]
        )

        # No need to mock: indexer_with_categories has no "game" category,
        # so get_indexers_by_category("game") returns [] and the fallback fires.
        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_games(query="Game")

        assert len(results) >= 1


class TestSearchAcrossAllIndexers:
    async def test_search_across_all_no_indexers_returns_empty(
        self, db_session: AsyncSession
    ):
        service = IndexerService(db_session)
        results = await service.search_across_all_indexers("audiobook", query="test")
        assert results == []

    async def test_search_across_all_with_indexer(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        service = IndexerService(db_session)
        mock_client = AsyncMock()
        mock_client.search_movie = AsyncMock(
            return_value=[{"title": "All Indexers Result", "size": 2000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_across_all_indexers(
                "movie", query="All Indexers"
            )

        assert len(results) >= 1


# ---------------------------------------------------------------------------
# process_and_score_releases
# ---------------------------------------------------------------------------

class TestProcessAndScoreReleases:
    async def test_scores_releases(self, db_session: AsyncSession):
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.9)
        service = IndexerService(db_session, release_service=mock_release_svc)

        raw = [
            {"title": "Movie.2024.1080p.BluRay", "size": 5000},
            {"title": "Movie.2024.720p.WEB", "size": 2000},
        ]
        scored = await service.process_and_score_releases(raw, "movie")

        assert len(scored) == 2
        assert scored[0][1] == 0.9

    async def test_score_error_defaults_to_zero(self, db_session: AsyncSession):
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(side_effect=Exception("Scoring failed"))
        service = IndexerService(db_session, release_service=mock_release_svc)

        raw = [{"title": "Bad Release", "size": 100}]
        scored = await service.process_and_score_releases(raw, "movie")

        assert len(scored) == 1
        assert scored[0][1] == 0.0

    async def test_results_sorted_by_score_desc(self, db_session: AsyncSession):
        scores = iter([0.3, 0.9, 0.6])
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(side_effect=lambda r, t: scores.__next__())
        service = IndexerService(db_session, release_service=mock_release_svc)

        raw = [
            {"title": "Low", "size": 1},
            {"title": "High", "size": 2},
            {"title": "Mid", "size": 3},
        ]
        scored = await service.process_and_score_releases(raw, "movie")

        assert scored[0][1] >= scored[1][1] >= scored[2][1]


# ---------------------------------------------------------------------------
# search_and_process (full pipeline)
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def indexer_with_movie_category(db_session: AsyncSession) -> Indexer:
    """Indexer with only movie categories (no show/game)."""
    indexer = Indexer(
        guid=uuid.uuid4(),
        label="Movie Indexer",
        host="https://movie-indexer.example.com",
        api_key="movie-key",
        type="newznab",
        ssl=True,
    )
    db_session.add(indexer)
    await db_session.flush()
    cat = IndexerCategory(
        guid=uuid.uuid4(),
        indexer_guid=indexer.guid,
        label="Movies",
        category_type="movie",
        newznab_category_id=2000,
    )
    db_session.add(cat)
    await db_session.commit()
    await db_session.refresh(indexer)
    return indexer


class TestSearchAndProcess:
    async def test_search_and_process_movie(
        self, db_session: AsyncSession, indexer_with_movie_category: Indexer
    ):
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.8)
        service = IndexerService(db_session, release_service=mock_release_svc)

        mock_client = AsyncMock()
        mock_client.search_movie = AsyncMock(
            return_value=[{"title": "Pipeline Movie", "size": 5000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_and_process("movie", query="Pipeline")

        assert len(results) == 1
        assert results[0][0]["title"] == "Pipeline Movie"
        assert results[0][1] == 0.8

    async def test_search_and_process_show(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.7)
        service = IndexerService(db_session, release_service=mock_release_svc)

        mock_client = AsyncMock()
        mock_client.search_show = AsyncMock(
            return_value=[{"title": "Pipeline Show S01", "size": 1000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_and_process("show", query="Pipeline Show")

        assert len(results) == 1
        assert results[0][1] == 0.7

    async def test_search_and_process_game(
        self, db_session: AsyncSession, indexer_with_categories: Indexer
    ):
        # indexer_with_categories has no game categories, so get_indexers_by_category
        # returns [] and falls back to get_active_indexers() (uses selectinload safely).
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.5)
        service = IndexerService(db_session, release_service=mock_release_svc)

        mock_client = AsyncMock()
        mock_client.search_game = AsyncMock(
            return_value=[{"title": "Pipeline Game", "size": 8000}]
        )

        with patch.object(service, "_create_indexer_client", return_value=mock_client):
            results = await service.search_and_process("game", query="Pipeline Game")

        assert len(results) == 1

    async def test_search_and_process_no_dedup(
        self, db_session: AsyncSession, indexer_with_movie_category: Indexer
    ):
        """deduplicate=False keeps duplicate releases."""
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.5)
        service = IndexerService(db_session, release_service=mock_release_svc)

        raw_results = [
            {"title": "Dup Movie", "size": 5000},
            {"title": "Dup Movie", "size": 5000},
        ]

        with patch.object(service, "search_movies", new=AsyncMock(return_value=raw_results)):
            results = await service.search_and_process(
                "movie", deduplicate=False, query="Dup"
            )

        assert len(results) == 2

    async def test_search_and_process_other_type_uses_all_indexers(
        self, db_session: AsyncSession, indexer_with_movie_category: Indexer
    ):
        """Content types other than movie/show/game go through search_across_all_indexers."""
        mock_release_svc = AsyncMock()
        mock_release_svc.score_release = AsyncMock(return_value=0.4)
        service = IndexerService(db_session, release_service=mock_release_svc)

        expected_raw = [{"title": "Audiobook Title", "size": 200}]

        with patch.object(
            service,
            "search_across_all_indexers",
            AsyncMock(return_value=expected_raw),
        ):
            results = await service.search_and_process("audiobook", query="Audiobook")

        assert len(results) == 1
        assert results[0][0]["title"] == "Audiobook Title"
