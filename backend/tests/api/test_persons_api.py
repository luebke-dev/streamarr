"""Tests for persons API endpoints (/api/persons/*)."""

import uuid
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.library import Library
from streamarr.models.media import MediaItem, MediaType
from streamarr.models.person import MediaCast, Person
from streamarr.models.user import User

from .conftest import auth_headers


@pytest.fixture
async def test_person(db_session: AsyncSession) -> Person:
    person = Person(
        guid=uuid.uuid4(),
        name="Test Actor",
        tmdb_id=12345,
        profile_path="/actor.jpg",
        known_for_department="Acting",
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(person)
    await db_session.commit()
    await db_session.refresh(person)
    return person


@pytest.fixture
async def test_person_with_credits(
    db_session: AsyncSession, test_person: Person
) -> Person:
    _now = datetime.now(UTC)
    library = Library(
        guid=uuid.uuid4(),
        name="Movies Lib",
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
        title="Credit Movie",
        media_type=MediaType.MOVIES,
        library_guid=library.guid,
    )
    db_session.add(media)
    await db_session.flush()

    cast = MediaCast(
        guid=uuid.uuid4(),
        media_item_guid=media.guid,
        person_guid=test_person.guid,
        character="Hero",
        department="Acting",
        job="Actor",
        cast_order=1,
        created_at=datetime.now(UTC),
    )
    db_session.add(cast)
    await db_session.commit()
    return test_person


# ---------------------------------------------------------------------------
# GET /api/persons
# ---------------------------------------------------------------------------
class TestSearchPersons:
    async def test_search_with_query(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        test_person: Person,
    ):
        resp = await client.get(
            "/api/persons",
            params={"q": "Test Actor"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["name"] == "Test Actor"

    async def test_search_no_query(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/persons", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    async def test_search_no_match(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/persons",
            params={"q": "Nonexistent Person XYZ"},
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data == []

    async def test_search_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/persons", params={"q": "test"})
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/persons/{person_guid}
# ---------------------------------------------------------------------------
class TestGetPerson:
    async def test_get_person_found(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        test_person: Person,
    ):
        resp = await client.get(
            f"/api/persons/{test_person.guid}",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Actor"
        assert data["tmdb_id"] == 12345
        assert data["external_links"] == [
            {
                "provider": "tmdb",
                "provider_id": "12345",
                "display_name": "TMDB",
                "url": "https://www.themoviedb.org/person/12345",
            }
        ]

    async def test_get_person_includes_homepage_link(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        person = Person(
            guid=uuid.uuid4(),
            name="Homepage Actor",
            tmdb_id=999,
            homepage="https://example.com/person",
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(person)
        await db_session.commit()

        resp = await client.get(f"/api/persons/{person.guid}", headers=user_headers)

        assert resp.status_code == 200
        links = {link["provider"]: link for link in resp.json()["external_links"]}
        assert links["tmdb"]["url"] == "https://www.themoviedb.org/person/999"
        assert links["homepage"]["url"] == "https://example.com/person"

    async def test_get_person_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/persons/{fake_guid}",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_get_person_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/persons/{uuid.uuid4()}")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# GET /api/persons/{person_guid}/credits
# ---------------------------------------------------------------------------
class TestGetPersonCredits:
    async def test_credits_found(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        test_person_with_credits: Person,
    ):
        resp = await client.get(
            f"/api/persons/{test_person_with_credits.guid}/credits",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert data[0]["character"] == "Hero"

    async def test_credits_person_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.get(
            f"/api/persons/{fake_guid}/credits",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_credits_empty(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        test_person: Person,
    ):
        resp = await client.get(
            f"/api/persons/{test_person.guid}/credits",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data == []
