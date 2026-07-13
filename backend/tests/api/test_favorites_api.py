"""Tests for the Favorites API endpoints (/api/favorites/*)."""

import uuid
from types import SimpleNamespace

import pytest
from fastapi import BackgroundTasks
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.api.v1 import favorites as favorites_api
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.user import User
from streamarr.schemas.favorite import FavoriteStatusResponse


@pytest.fixture
async def movie(db_session: AsyncSession) -> MediaItem:
    """Create a movie for favorite tests."""
    item = MediaItem(
        title="Fav Movie",
        media_type=MediaType.MOVIES,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest.fixture
async def show(db_session: AsyncSession) -> MediaItem:
    """Create a show for favorite tests."""
    item = MediaItem(
        title="Fav Show",
        media_type=MediaType.SHOWS,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest.fixture
async def season(db_session: AsyncSession, show: MediaItem) -> MediaItem:
    """Create a season (child of show) for favorite tests."""
    item = MediaItem(
        title="Season 1",
        media_type=MediaType.SHOWS,
        parent_guid=show.guid,
        sequence_number=1,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest.fixture
async def episode(db_session: AsyncSession, season: MediaItem) -> MediaItem:
    """Create an episode (child of season, grandchild of show) for favorite tests."""
    item = MediaItem(
        title="Episode 1",
        media_type=MediaType.SHOWS,
        parent_guid=season.guid,
        sequence_number=1,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


class TestFavoriteStatus:
    async def test_status_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/favorites/movies/{uuid.uuid4()}/status")
        assert resp.status_code == 401

    async def test_status_not_favorited(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.get(
            f"/api/favorites/movies/{movie.guid}/status", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is False

    async def test_status_is_favorited(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """After toggling on, status should be True."""
        await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        resp = await client.get(
            f"/api/favorites/movies/{movie.guid}/status", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

    async def test_unknown_media_type(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/favorites/unknown/{uuid.uuid4()}/status", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_nonexistent_media_item(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/favorites/movies/{uuid.uuid4()}/status", headers=user_headers
        )
        assert resp.status_code == 404


class TestToggleFavorite:
    async def test_toggle_schedules_cache_clear_after_response(self, monkeypatch):
        """Cache invalidation must not block the favorite toggle response."""
        item_guid = uuid.uuid4()
        user_guid = uuid.uuid4()
        calls = []

        class StubFavoriteService:
            def __init__(self, db):
                self.db = db

            async def toggle(self, type_prefix, media_guid, current_user_guid):
                calls.append((type_prefix, media_guid, current_user_guid))
                return FavoriteStatusResponse(is_favorited=True, monitored=False)

        async def fail_if_called_inline(reason):
            raise AssertionError(
                f"cache invalidation ran before response for {reason}"
            )

        monkeypatch.setattr(favorites_api, "FavoriteService", StubFavoriteService)
        monkeypatch.setattr(
            favorites_api,
            "clear_rendered_layout_cache",
            fail_if_called_inline,
        )

        background_tasks = BackgroundTasks()
        result = await favorites_api.toggle_favorite(
            "shows",
            item_guid,
            background_tasks,
            object(),
            SimpleNamespace(guid=user_guid),
        )

        assert result.is_favorited is True
        assert calls == [("shows", item_guid, user_guid)]
        assert len(background_tasks.tasks) == 1
        task = background_tasks.tasks[0]
        assert task.func is fail_if_called_inline
        assert task.args == ("favorites_changed",)

    async def test_toggle_on(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

    async def test_toggle_off(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Toggle on
        await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        # Toggle off
        resp = await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is False

    async def test_toggle_on_unknown_type(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/favorites/unknown/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_toggle_on_nonexistent_item(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/favorites/movies/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_toggle_on_unauthenticated(self, client: AsyncClient, movie):
        resp = await client.post(f"/api/favorites/movies/{movie.guid}")
        assert resp.status_code == 401

    async def test_toggle_on_off_on_cycle(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """Full on → off → on cycle works correctly."""
        resp = await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

        resp = await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        assert resp.json()["is_favorited"] is False

        resp = await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

class TestHierarchyRedirect:
    """Favoriting a season or episode must target the root show."""

    async def test_toggle_season_favorites_show(
        self, client: AsyncClient, test_user: User, user_headers, show, season
    ):
        """Toggling a season favorite stores it under the parent show."""
        resp = await client.post(
            f"/api/favorites/shows/{season.guid}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

        # The show should now appear as favorited
        resp = await client.get(
            f"/api/favorites/shows/{show.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

    async def test_toggle_episode_favorites_show(
        self, client: AsyncClient, test_user: User, user_headers, show, season, episode
    ):
        """Toggling an episode favorite stores it under the root show."""
        resp = await client.post(
            f"/api/favorites/shows/{episode.guid}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

        # The show should now appear as favorited
        resp = await client.get(
            f"/api/favorites/shows/{show.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

    async def test_status_season_reflects_show(
        self, client: AsyncClient, test_user: User, user_headers, show, season
    ):
        """Status check for a season reflects the show's favorite state."""
        # Not favorited yet
        resp = await client.get(
            f"/api/favorites/shows/{season.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is False

        # Favorite the show directly
        await client.post(f"/api/favorites/shows/{show.guid}", headers=user_headers)

        # Status via season should now be True
        resp = await client.get(
            f"/api/favorites/shows/{season.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

    async def test_status_episode_reflects_show(
        self, client: AsyncClient, test_user: User, user_headers, show, season, episode
    ):
        """Status check for an episode reflects the show's favorite state."""
        # Not favorited yet
        resp = await client.get(
            f"/api/favorites/shows/{episode.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is False

        # Favorite via episode
        await client.post(f"/api/favorites/shows/{episode.guid}", headers=user_headers)

        # Status via show should be True
        resp = await client.get(
            f"/api/favorites/shows/{show.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True

    async def test_toggle_season_off_unfavorites_show(
        self, client: AsyncClient, test_user: User, user_headers, show, season
    ):
        """Toggling season favorite twice removes the show favorite."""
        await client.post(f"/api/favorites/shows/{season.guid}", headers=user_headers)
        resp = await client.post(
            f"/api/favorites/shows/{season.guid}", headers=user_headers
        )
        assert resp.json()["is_favorited"] is False

        resp = await client.get(
            f"/api/favorites/shows/{show.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is False

    async def test_orphaned_parent_guid_treated_as_root(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        db_session: AsyncSession,
    ):
        """An item whose parent_guid points to a non-existent item is treated as root."""
        orphan = MediaItem(
            title="Orphan Item",
            media_type=MediaType.SHOWS,
            parent_guid=uuid.uuid4(),  # points to nothing
        )
        db_session.add(orphan)
        await db_session.commit()
        await db_session.refresh(orphan)

        resp = await client.post(
            f"/api/favorites/shows/{orphan.guid}", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["is_favorited"] is True

        # The orphan itself should be the favorited item
        resp = await client.get(
            f"/api/favorites/shows/{orphan.guid}/status", headers=user_headers
        )
        assert resp.json()["is_favorited"] is True


class TestListFavorites:
    async def test_list_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/favorites", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_favorite(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Add favorite
        await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )

        resp = await client.get("/api/favorites", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        item = data["items"][0]
        assert item["title"] == "Fav Movie"
        assert "media_type" in item
        assert "poster_url" in item

    async def test_list_filter_by_type(
        self, client: AsyncClient, test_user: User, user_headers, movie, show
    ):
        """Filter favorites by type_prefix."""
        await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        await client.post(
            f"/api/favorites/shows/{show.guid}", headers=user_headers
        )

        # Only movies
        resp = await client.get(
            "/api/favorites?type_prefix=movies", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["media_type"] == "MOVIES"

        # Only shows
        resp = await client.get(
            "/api/favorites?type_prefix=shows", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        for item in data["items"]:
            assert item["media_type"] == "SHOWS"

    async def test_list_filter_by_unknown_type(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Filtering by an unknown type returns 400."""
        resp = await client.get(
            "/api/favorites?type_prefix=unknown", headers=user_headers
        )
        assert resp.status_code == 400

    async def test_list_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/favorites")
        assert resp.status_code == 401

    async def test_list_multiple_favorites(
        self, client: AsyncClient, test_user: User, user_headers, movie, show
    ):
        """Multiple favorites are returned correctly."""
        await client.post(
            f"/api/favorites/movies/{movie.guid}", headers=user_headers
        )
        await client.post(
            f"/api/favorites/shows/{show.guid}", headers=user_headers
        )

        resp = await client.get("/api/favorites", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 2
        guids = {item["media_item_guid"] for item in data["items"]}
        assert str(movie.guid) in guids
        assert str(show.guid) in guids
