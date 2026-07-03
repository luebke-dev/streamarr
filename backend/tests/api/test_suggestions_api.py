"""Tests for suggestions and instant-mix endpoints."""

import json
import uuid
from datetime import UTC, date, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.favorite import Favorite
from pyrate.models.genre import Genre
from pyrate.models.media import (
    AvailabilityStatus,
    MediaItem,
    MediaType,
    media_genre_table,
)
from pyrate.models.person import MediaCast, Person
from pyrate.models.user import User
from pyrate.models.viewing_history import ViewingHistory


async def _create_item(
    db: AsyncSession,
    *,
    title: str,
    media_type: MediaType = MediaType.MOVIES,
    genre: Genre | None = None,
    parent_guid=None,
    sequence_number: int | None = None,
    release_date: date | None = None,
    created_at: datetime | None = None,
    extra_data: str | None = None,
    min_age: int | None = None,
) -> MediaItem:
    now = created_at or datetime.now(UTC)
    item = MediaItem(
        guid=uuid.uuid4(),
        title=title,
        media_type=media_type,
        availability_status=AvailabilityStatus.AVAILABLE,
        parent_guid=parent_guid,
        sequence_number=sequence_number,
        release_date=release_date,
        extra_data=extra_data,
        min_age=min_age,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.flush()
    if genre:
        await db.execute(
            media_genre_table.insert().values(
                media_item_guid=item.guid,
                genre_id=genre.id,
            )
        )
    await db.commit()
    await db.refresh(item)
    return item


class TestSuggestions:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/suggestions")
        assert resp.status_code == 401

    async def test_suggestions_use_user_activity_genres(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        action = Genre(id=1, name="Action")
        drama = Genre(id=2, name="Drama")
        db_session.add_all([action, drama])
        await db_session.flush()

        seed = await _create_item(db_session, title="Seed", genre=action)
        await _create_item(db_session, title="Match", genre=action)
        await _create_item(db_session, title="Other", genre=drama)

        db_session.add(Favorite(user_id=test_user.guid, media_item_guid=seed.guid))
        await db_session.commit()

        resp = await client.get("/api/suggestions", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["reason"] == "because_of_your_activity"
        assert [item["title"] for item in data["items"]] == ["Match"]
        assert data["total"] == 1

    async def test_suggestions_exclude_completed_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        genre = Genre(id=1, name="Action")
        db_session.add(genre)
        await db_session.flush()
        seed = await _create_item(db_session, title="Seed", genre=genre)
        completed = await _create_item(db_session, title="Completed", genre=genre)
        open_item = await _create_item(db_session, title="Open", genre=genre)

        db_session.add_all(
            [
                Favorite(user_id=test_user.guid, media_item_guid=seed.guid),
                ViewingHistory(
                    user_guid=test_user.guid,
                    media_item_guid=completed.guid,
                    is_completed=True,
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get("/api/suggestions", headers=user_headers)

        assert resp.status_code == 200
        titles = [item["title"] for item in resp.json()["items"]]
        assert titles == ["Open"]
        assert completed.title not in titles
        assert open_item.title in titles

    async def test_suggestions_enforce_library_permissions(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        await db_session.commit()

        resp = await client.get(
            "/api/suggestions",
            headers=user_headers,
            params={"media_type": "MOVIES"},
        )

        assert resp.status_code == 403

    async def test_autocomplete_matches_visible_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        await _create_item(db_session, title="Space Movie")
        await _create_item(db_session, title="Other", media_type=MediaType.MOVIES)
        await _create_item(
            db_session,
            title="Space Song",
            media_type=MediaType.SONGS,
        )

        resp = await client.get(
            "/api/suggestions/autocomplete",
            headers=user_headers,
            params={"q": "space", "media_type": "MOVIES"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["query"] == "space"
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Space Movie"

    async def test_autocomplete_enforces_library_permissions(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        await _create_item(db_session, title="Space Movie")
        await db_session.commit()

        resp = await client.get(
            "/api/suggestions/autocomplete",
            headers=user_headers,
            params={"q": "space", "media_type": "MOVIES"},
        )

        assert resp.status_code == 403

    async def test_typed_autocomplete_includes_search_domains(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        space_genre = Genre(id=10, name="Space Opera")
        db_session.add(space_genre)
        await db_session.flush()
        media_item = await _create_item(
            db_session,
            title="Space Movie",
            genre=space_genre,
            release_date=date(1999, 5, 19),
            extra_data=json.dumps({"studios": [{"name": "Space Studio"}]}),
        )
        person = Person(guid=uuid.uuid4(), name="Space Actor")
        db_session.add(person)
        await db_session.flush()
        db_session.add(
            MediaCast(
                guid=uuid.uuid4(),
                media_item_guid=media_item.guid,
                person_guid=person.guid,
                character="Pilot",
                department="Acting",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/suggestions/autocomplete/typed",
            headers=user_headers,
            params={"q": "space"},
        )

        assert resp.status_code == 200
        data = resp.json()
        by_type = {item["type"]: item for item in data["items"]}
        assert by_type["media"]["label"] == "Space Movie"
        assert by_type["genre"]["label"] == "Space Opera"
        assert by_type["person"]["label"] == "Space Actor"
        assert by_type["studio"]["label"] == "Space Studio"

    async def test_typed_autocomplete_includes_years(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        await _create_item(
            db_session,
            title="Millennium Movie",
            release_date=date(1999, 5, 19),
        )

        resp = await client.get(
            "/api/suggestions/autocomplete/typed",
            headers=user_headers,
            params={"q": "1999"},
        )

        assert resp.status_code == 200
        years = [item for item in resp.json()["items"] if item["type"] == "year"]
        assert years[0]["value"] == "1999"

    async def test_latest_items_returns_visible_top_level_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        older = await _create_item(
            db_session,
            title="Older Movie",
            created_at=datetime(2024, 1, 1, tzinfo=UTC),
        )
        newer = await _create_item(
            db_session,
            title="Newer Movie",
            created_at=datetime(2024, 2, 1, tzinfo=UTC),
        )
        await _create_item(
            db_session,
            title="Child Episode",
            media_type=MediaType.EPISODES,
            parent_guid=older.guid,
            created_at=datetime(2024, 3, 1, tzinfo=UTC),
        )

        resp = await client.get("/api/suggestions/latest", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert [item["title"] for item in data["items"]] == [
            "Newer Movie",
            "Older Movie",
        ]
        assert data["total"] == 2
        assert str(newer.guid) == data["items"][0]["guid"]

    async def test_latest_items_respects_permissions_and_parental_control(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["movies"]
        test_user.parental_max_age = 12
        await _create_item(
            db_session,
            title="Allowed Movie",
            media_type=MediaType.MOVIES,
            min_age=12,
        )
        await _create_item(
            db_session,
            title="Blocked Movie",
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await _create_item(
            db_session,
            title="Blocked Song",
            media_type=MediaType.SONGS,
        )
        await db_session.commit()

        resp = await client.get("/api/suggestions/latest", headers=user_headers)

        assert resp.status_code == 200
        titles = [item["title"] for item in resp.json()["items"]]
        assert titles == ["Allowed Movie"]

    async def test_latest_items_denies_disallowed_media_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        await db_session.commit()

        resp = await client.get(
            "/api/suggestions/latest",
            headers=user_headers,
            params={"media_type": "MOVIES"},
        )

        assert resp.status_code == 403


class TestInstantMix:
    async def test_instant_mix_returns_seed_and_related_items(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        rock = Genre(id=1, name="Rock")
        pop = Genre(id=2, name="Pop")
        db_session.add_all([rock, pop])
        await db_session.flush()

        seed = await _create_item(
            db_session, title="Seed Song", media_type=MediaType.SONGS, genre=rock
        )
        related = await _create_item(
            db_session, title="Related Song", media_type=MediaType.SONGS, genre=rock
        )
        await _create_item(
            db_session, title="Other Song", media_type=MediaType.SONGS, genre=pop
        )

        resp = await client.get(
            f"/api/suggestions/instant-mix/{seed.guid}", headers=user_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["seed_guid"] == str(seed.guid)
        assert [item["title"] for item in data["items"]] == [
            "Seed Song",
            "Related Song",
        ]
        assert data["items"][1]["guid"] == str(related.guid)

    async def test_instant_mix_blocks_disallowed_seed(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        seed = await _create_item(db_session, title="Movie Seed")
        await db_session.commit()

        resp = await client.get(
            f"/api/suggestions/instant-mix/{seed.guid}", headers=user_headers
        )

        assert resp.status_code == 403
