"""Tests for genres API endpoints (/api/genres/*)."""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.genre import Genre
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.user import User


# ---------------------------------------------------------------------------
# GET /api/genres/with-items
# ---------------------------------------------------------------------------
class TestListGenresWithItems:
    async def test_list_genres_with_items_empty(self, client: AsyncClient, user_headers):
        """With no genres in the DB the endpoint returns an empty list."""
        resp = await client.get("/api/genres/with-items", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_genres_with_items(
        self, client: AsyncClient, db_session: AsyncSession, user_headers
    ):
        """Genres with media items are included in the response."""
        genre = Genre(id=28, name="Action")
        db_session.add(genre)
        await db_session.flush()

        movie = MediaItem(title="Action Hero", media_type=MediaType.MOVIES)
        db_session.add(movie)
        await db_session.flush()
        await db_session.refresh(movie)

        movie.genres.append(genre)
        await db_session.commit()

        resp = await client.get("/api/genres/with-items", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["id"] == 28
        assert data[0]["name"] == "Action"
        assert len(data[0]["items"]) == 1
        assert data[0]["items"][0]["title"] == "Action Hero"

    async def test_list_genres_with_items_excludes_empty_genres(
        self, client: AsyncClient, db_session: AsyncSession, user_headers
    ):
        """Genres with no media items are excluded from the result."""
        genre_with = Genre(id=28, name="Action")
        genre_without = Genre(id=35, name="Comedy")
        db_session.add_all([genre_with, genre_without])
        await db_session.flush()

        movie = MediaItem(title="An Action Film", media_type=MediaType.MOVIES)
        db_session.add(movie)
        await db_session.flush()
        await db_session.refresh(movie)

        movie.genres.append(genre_with)
        await db_session.commit()

        resp = await client.get("/api/genres/with-items", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        # Only the genre that has items should appear
        assert len(data) == 1
        assert data[0]["id"] == 28

    async def test_list_genres_with_items_max_items_per_genre(
        self, client: AsyncClient, db_session: AsyncSession, user_headers
    ):
        """max_items_per_genre limits the items returned per genre."""
        genre = Genre(id=28, name="Action")
        db_session.add(genre)
        await db_session.flush()

        for i in range(5):
            m = MediaItem(title=f"Movie {i}", media_type=MediaType.MOVIES)
            db_session.add(m)
            await db_session.flush()
            await db_session.refresh(m)
            m.genres.append(genre)

        await db_session.commit()

        resp = await client.get(
            "/api/genres/with-items?max_items_per_genre=2", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert len(data[0]["items"]) == 2

    async def test_list_genres_with_items_filters_disallowed_libraries(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Genre media summaries respect the user's library permissions."""
        test_user.allowed_libraries = ["music"]
        db_session.add(test_user)
        genre = Genre(id=28, name="Action")
        movie = MediaItem(title="Hidden Movie", media_type=MediaType.MOVIES)
        db_session.add_all([genre, movie])
        await db_session.flush()
        movie.genres.append(genre)
        await db_session.commit()

        resp = await client.get("/api/genres/with-items", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_genres_with_items_filters_parental_limit(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        """Genre media summaries respect parental-control limits."""
        test_user.parental_max_age = 12
        db_session.add(test_user)
        genre = Genre(id=28, name="Action")
        movie = MediaItem(
            title="Rated Movie",
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        db_session.add_all([genre, movie])
        await db_session.flush()
        movie.genres.append(genre)
        await db_session.commit()

        resp = await client.get("/api/genres/with-items", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_genres_with_items_denies_explicit_media_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        db_session.add(test_user)
        await db_session.commit()

        resp = await client.get(
            "/api/genres/with-items?media_type=MOVIES",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_list_genres_with_items_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/genres/with-items")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/genres
# ---------------------------------------------------------------------------
    async def test_list_genres_empty(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/genres", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_genres(self, client: AsyncClient, db_session: AsyncSession, user_headers):
        g1 = Genre(id=28, name="Action")
        g2 = Genre(id=35, name="Comedy")
        db_session.add_all([g1, g2])
        await db_session.commit()

        resp = await client.get("/api/genres", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        names = {g["name"] for g in data}
        assert names == {"Action", "Comedy"}

    async def test_list_genres_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/genres")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/genres/{genre_id}
# ---------------------------------------------------------------------------
class TestGetGenre:
    async def test_get_genre(self, client: AsyncClient, db_session: AsyncSession, user_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.get("/api/genres/28", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["name"] == "Action"
        assert resp.json()["id"] == 28

    async def test_get_genre_not_found(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/genres/9999", headers=user_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# POST /api/genres
# ---------------------------------------------------------------------------
class TestCreateGenre:
    async def test_create_genre_admin(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/genres",
            json={"id": 28, "name": "Action"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == 28
        assert data["name"] == "Action"

    async def test_create_genre_duplicate(self, client: AsyncClient, db_session: AsyncSession, admin_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.post(
            "/api/genres",
            json={"id": 28, "name": "Action"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_create_genre_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.post(
            "/api/genres",
            json={"id": 28, "name": "Action"},
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_create_genre_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/genres", json={"id": 28, "name": "Action"})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# PUT /api/genres/{genre_id}
# ---------------------------------------------------------------------------
class TestUpdateGenre:
    async def test_update_genre_admin(self, client: AsyncClient, db_session: AsyncSession, admin_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.put(
            "/api/genres/28",
            json={"name": "Action/Adventure"},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Action/Adventure"

    async def test_update_genre_not_found(self, client: AsyncClient, admin_headers):
        resp = await client.put(
            "/api/genres/9999",
            json={"name": "Updated"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_update_genre_regular_user_forbidden(self, client: AsyncClient, db_session: AsyncSession, user_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.put(
            "/api/genres/28",
            json={"name": "Updated"},
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# DELETE /api/genres/{genre_id}
# ---------------------------------------------------------------------------
class TestDeleteGenre:
    async def test_delete_genre_admin(self, client: AsyncClient, db_session: AsyncSession, admin_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.delete("/api/genres/28", headers=admin_headers)
        assert resp.status_code == 204

        # Verify deletion
        resp2 = await client.get("/api/genres/28", headers=admin_headers)
        assert resp2.status_code == 404

    async def test_delete_genre_not_found(self, client: AsyncClient, admin_headers):
        resp = await client.delete("/api/genres/9999", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_genre_regular_user_forbidden(self, client: AsyncClient, db_session: AsyncSession, user_headers):
        g = Genre(id=28, name="Action")
        db_session.add(g)
        await db_session.commit()

        resp = await client.delete("/api/genres/28", headers=user_headers)
        assert resp.status_code == 403
