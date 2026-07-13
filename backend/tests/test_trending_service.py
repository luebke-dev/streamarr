"""Tests for TrendingService – discovery helpers and list management."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from sqlalchemy import select

from streamarr.models.list import List, ListItem, ListType, ListVisibility
from streamarr.models.media import MediaExternalId, MediaItem, MediaRelease, MediaReleaseLink, MediaType
from streamarr.models.user import User
from streamarr.services.trending import TrendingService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def service(db_session):
    return TrendingService(db_session)


@pytest_asyncio.fixture
async def owner(db_session):
    """Create a user to own trending lists."""
    from streamarr.auth.jwt_handler import jwt_handler

    user = User(
        email="trending@example.com",
        first_name="Trending",
        last_name="Owner",
        hashed_password=jwt_handler.get_password_hash("pw"),
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


# ---------------------------------------------------------------------------
# Discovery – get_new_trending_*_ids
# ---------------------------------------------------------------------------

class TestDiscovery:
    @pytest.mark.asyncio
    async def test_get_new_trending_movie_ids(self, service: TrendingService):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(
            return_value={
                "results": [
                    {"id": 100},
                    {"id": 200},
                ]
            }
        )
        service._tmdb = mock_tmdb

        ids = await service.get_new_trending_movie_ids()
        # No movies exist in DB so both should be new
        assert 100 in ids
        assert 200 in ids

    @pytest.mark.asyncio
    async def test_get_new_trending_show_ids(self, service: TrendingService):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_shows = AsyncMock(
            return_value={
                "results": [
                    {"id": 300},
                ]
            }
        )
        service._tmdb = mock_tmdb

        ids = await service.get_new_trending_show_ids()
        assert ids == [300]

    @pytest.mark.asyncio
    async def test_get_new_trending_game_ids(self, service: TrendingService):
        mock_igdb = AsyncMock()
        mock_igdb.get_trending_games = AsyncMock(
            return_value=[
                {"id": 500},
                {"id": 600},
            ]
        )
        service._igdb = mock_igdb

        ids = await service.get_new_trending_game_ids()
        assert 500 in ids
        assert 600 in ids


# ---------------------------------------------------------------------------
# List management
# ---------------------------------------------------------------------------

class TestListManagement:
    @pytest.mark.asyncio
    async def test_update_trending_movies_list_creates_list(
        self, service: TrendingService, owner, db_session
    ):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(return_value={"results": []})
        service._tmdb = mock_tmdb

        await service.update_trending_movies_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_movies")
        )
        lst = result.scalar_one_or_none()
        assert lst is not None
        assert lst.name == "Trending Movies"
        assert lst.list_type == ListType.SYSTEM

    @pytest.mark.asyncio
    async def test_update_trending_movies_list_no_user(self, db_session):
        """System lists should be created without an owner."""
        svc = TrendingService(db_session)
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(return_value={"results": []})
        svc._tmdb = mock_tmdb

        await svc.update_trending_movies_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_movies")
        )
        lst = result.scalar_one_or_none()
        assert lst is not None
        assert lst.owner_guid is None

    @pytest.mark.asyncio
    async def test_update_trending_shows_list_creates_list(
        self, service: TrendingService, owner, db_session
    ):
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_shows = AsyncMock(return_value={"results": []})
        service._tmdb = mock_tmdb

        await service.update_trending_shows_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_shows")
        )
        lst = result.scalar_one_or_none()
        assert lst is not None
        assert lst.name == "Trending TV Shows"

    @pytest.mark.asyncio
    async def test_update_trending_games_list_creates_list(
        self, service: TrendingService, owner, db_session
    ):
        mock_igdb = AsyncMock()
        mock_igdb.get_trending_games = AsyncMock(return_value=[])
        service._igdb = mock_igdb

        await service.update_trending_games_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_games")
        )
        lst = result.scalar_one_or_none()
        assert lst is not None
        assert lst.name == "Trending Games"

    @pytest.mark.asyncio
    async def test_update_trending_movies_list_adds_items(
        self, service: TrendingService, owner, db_session
    ):
        trending_ids = [100, 101, 102]
        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(
            return_value={"results": [{"id": tmdb_id} for tmdb_id in trending_ids]}
        )
        service._tmdb = mock_tmdb

        # Create movies with matching TMDB external IDs.
        for i in range(3):
            mi = MediaItem(
                title=f"Movie {i}",
                media_type=MediaType.MOVIES,
            )
            db_session.add(mi)
            await db_session.flush()
            db_session.add(
                MediaExternalId(
                    media_item_guid=mi.guid,
                    provider="tmdb",
                    external_id=str(trending_ids[i]),
                )
            )
            release = MediaRelease(
                media_item_guid=mi.guid,
                title=f"Movie.{i}.1080p.WEB-DL",
            )
            db_session.add(release)
            await db_session.flush()
            db_session.add(MediaReleaseLink(
                media_release_guid=release.guid,
                link=f"http://example.com/movie{i}.nzb",
                link_type="nzb",
            ))
        await db_session.commit()

        with patch("streamarr.worker.search_media_item_releases", new=AsyncMock()):
            await service.update_trending_movies_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_movies")
        )
        lst = result.scalar_one()
        assert lst.item_count == 3

        items = await db_session.execute(
            select(ListItem).where(ListItem.list_guid == lst.guid)
        )
        assert len(items.scalars().all()) == 3

    @pytest.mark.asyncio
    async def test_update_replaces_old_items(
        self, service: TrendingService, owner, db_session
    ):
        async def _add_movie_with_release(title, tmdb_id):
            mi = MediaItem(title=title, media_type=MediaType.MOVIES)
            db_session.add(mi)
            await db_session.flush()
            db_session.add(
                MediaExternalId(
                    media_item_guid=mi.guid,
                    provider="tmdb",
                    external_id=str(tmdb_id),
                )
            )
            rel = MediaRelease(media_item_guid=mi.guid, title=f"{title}.1080p")
            db_session.add(rel)
            await db_session.flush()
            db_session.add(MediaReleaseLink(
                media_release_guid=rel.guid, link="http://x.com/a.nzb", link_type="nzb"
            ))
            return mi

        for i in range(2):
            await _add_movie_with_release(f"M{i}", 100 + i)
        await db_session.commit()

        mock_tmdb = AsyncMock()
        mock_tmdb.get_trending_movies = AsyncMock(
            return_value={"results": [{"id": 100}, {"id": 101}]}
        )
        service._tmdb = mock_tmdb
        with patch("streamarr.worker.search_media_item_releases", new=AsyncMock()):
            await service.update_trending_movies_list()

        new_movie = await _add_movie_with_release("M_new", 102)
        await db_session.commit()

        mock_tmdb.get_trending_movies = AsyncMock(
            return_value={"results": [{"id": 102}]}
        )
        with patch("streamarr.worker.search_media_item_releases", new=AsyncMock()):
            await service.update_trending_movies_list()

        result = await db_session.execute(
            select(List).where(List.update_source == "trending_movies")
        )
        lst = result.scalar_one()
        assert lst.item_count == 1

        items = await db_session.execute(
            select(ListItem).where(ListItem.list_guid == lst.guid)
        )
        item = items.scalar_one()
        assert item.item_guid == new_movie.guid


class TestGetOrCreate:
    @pytest.mark.asyncio
    async def test_get_or_create_trending_movies_list(
        self, service: TrendingService, owner, db_session
    ):
        result = await service.get_or_create_trending_movies_list()

        assert result.name == "Trending Movies"
        assert result.update_source == "trending_movies"
        assert result.list_type == ListType.SYSTEM
        assert result.owner_guid is None

    @pytest.mark.asyncio
    async def test_get_or_create_trending_shows_list(
        self, service: TrendingService, owner, db_session
    ):
        result = await service.get_or_create_trending_shows_list()

        assert result.name == "Trending TV Shows"
        assert result.update_source == "trending_shows"
        assert result.list_type == ListType.SYSTEM
        assert result.owner_guid is None
