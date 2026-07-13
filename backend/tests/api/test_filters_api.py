"""Tests for item filter discovery endpoint."""

import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.genre import Genre
from streamarr.models.media import (
    AvailabilityStatus,
    MediaFile,
    MediaItem,
    MediaType,
    media_genre_table,
    media_platform_table,
)
from streamarr.models.person import MediaCast, Person
from streamarr.models.platform import Platform
from streamarr.models.user import User


async def _create_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Filter Item",
        "media_type": MediaType.MOVIES,
        "availability_status": AvailabilityStatus.AVAILABLE,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestFilters:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/filters")
        assert resp.status_code == 401

    async def test_lists_visible_filter_values(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        genre = Genre(id=28, name="Action")
        platform = Platform(name="PC")
        db_session.add_all([genre, platform])
        await db_session.commit()
        await db_session.refresh(platform)

        movie = await _create_item(
            db_session,
            title="Action Movie",
            release_date=datetime(2020, 1, 1, tzinfo=UTC),
            content_rating="PG-13",
            extra_data='{"studios": ["Studio One"]}',
        )
        person = Person(name="Keanu Reeves")
        db_session.add(person)
        await db_session.commit()
        await db_session.refresh(person)
        db_session.add(
            MediaCast(
                media_item_guid=movie.guid,
                person_guid=person.guid,
                character="Neo",
                department="Acting",
            )
        )
        await db_session.execute(
            media_genre_table.insert().values(
                media_item_guid=movie.guid,
                genre_id=genre.id,
            )
        )
        db_session.add(
            MediaFile(
                media_item_guid=movie.guid,
                file_path="/media/action.mkv",
                file_name="action.mkv",
                format="mkv",
            )
        )
        game = await _create_item(db_session, title="Game", media_type=MediaType.GAMES)
        await db_session.execute(
            media_platform_table.insert().values(
                media_item_guid=game.guid,
                platform_id=platform.id,
            )
        )
        await db_session.commit()

        resp = await client.get("/api/filters", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "MOVIES" in data["media_types"]
        assert {"id": 28, "name": "Action"} in data["genres"]
        assert {"id": platform.id, "name": "PC"} in data["platforms"]
        assert 2020 in data["years"]
        assert "Studio One" in data["studios"]
        assert "mkv" in data["containers"]
        assert "PG-13" in data["content_ratings"]
        assert {"id": str(person.guid), "name": "Keanu Reeves"} in data["persons"]

    async def test_respects_library_permissions(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        await db_session.commit()
        genre = Genre(id=28, name="Action")
        db_session.add(genre)
        await db_session.commit()
        movie = await _create_item(db_session, title="Action Movie")
        await db_session.execute(
            media_genre_table.insert().values(
                media_item_guid=movie.guid,
                genre_id=genre.id,
            )
        )
        await db_session.commit()

        resp = await client.get("/api/filters", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert "MOVIES" not in data["media_types"]
        assert data["genres"] == []
        assert data["studios"] == []
