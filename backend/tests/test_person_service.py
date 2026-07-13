"""Tests for the PersonService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaItem, MediaType
from streamarr.models.person import MediaCast, Person
from streamarr.models.user import User
from streamarr.services.person import PersonService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest_asyncio.fixture
async def media_item(db_session: AsyncSession) -> MediaItem:
    """Create a media item for cast association."""
    item = MediaItem(
        guid=uuid.uuid4(),
        title="Test Movie",
        media_type=MediaType.MOVIES,
    )
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def person(db_session: AsyncSession) -> Person:
    """Create a test person."""
    p = Person(
        guid=uuid.uuid4(),
        tmdb_id=12345,
        name="John Doe",
        profile_path="/profiles/john.jpg",
        known_for_department="Acting",
    )
    db_session.add(p)
    await db_session.commit()
    await db_session.refresh(p)
    return p


# ---------------------------------------------------------------------------
# Person CRUD
# ---------------------------------------------------------------------------

class TestPersonCRUD:
    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, person: Person):
        service = PersonService(db_session)
        result = await service.get_by_id(person.guid)
        assert result is not None
        assert result.guid == person.guid
        assert result.name == "John Doe"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        service = PersonService(db_session)
        result = await service.get_by_id(uuid.uuid4())
        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_tmdb_id(self, db_session: AsyncSession, person: Person):
        service = PersonService(db_session)
        result = await service.get_by_tmdb_id(12345)
        assert result is not None
        assert result.name == "John Doe"

    @pytest.mark.asyncio
    async def test_get_by_tmdb_id_not_found(self, db_session: AsyncSession):
        service = PersonService(db_session)
        result = await service.get_by_tmdb_id(99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_or_create_new(self, db_session: AsyncSession):
        service = PersonService(db_session)
        result = await service.get_or_create(
            tmdb_id=54321,
            name="Jane Smith",
            profile_path="/profiles/jane.jpg",
            known_for_department="Directing",
        )
        assert result.tmdb_id == 54321
        assert result.name == "Jane Smith"
        assert result.profile_path == "/profiles/jane.jpg"

    @pytest.mark.asyncio
    async def test_get_or_create_existing(self, db_session: AsyncSession, person: Person):
        service = PersonService(db_session)
        result = await service.get_or_create(
            tmdb_id=12345,
            name="John Doe",
        )
        assert result.guid == person.guid

    @pytest.mark.asyncio
    async def test_get_or_create_updates_profile_path(
        self, db_session: AsyncSession, person: Person
    ):
        service = PersonService(db_session)
        result = await service.get_or_create(
            tmdb_id=12345,
            name="John Doe",
            profile_path="/profiles/john_new.jpg",
        )
        assert result.guid == person.guid
        assert result.profile_path == "/profiles/john_new.jpg"

    @pytest.mark.asyncio
    async def test_search(self, db_session: AsyncSession, person: Person):
        service = PersonService(db_session)
        results = await service.search("John")
        assert len(results) == 1
        assert results[0].name == "John Doe"

    @pytest.mark.asyncio
    async def test_search_case_insensitive(self, db_session: AsyncSession, person: Person):
        service = PersonService(db_session)
        results = await service.search("john")
        assert len(results) == 1

    @pytest.mark.asyncio
    async def test_search_no_results(self, db_session: AsyncSession):
        service = PersonService(db_session)
        results = await service.search("NonExistent")
        assert len(results) == 0

    @pytest.mark.asyncio
    async def test_search_with_limit(self, db_session: AsyncSession):
        service = PersonService(db_session)
        for i in range(5):
            p = Person(guid=uuid.uuid4(), tmdb_id=100 + i, name=f"Actor {i}")
            db_session.add(p)
        await db_session.commit()

        results = await service.search("Actor", limit=3)
        assert len(results) == 3


# ---------------------------------------------------------------------------
# Cast management
# ---------------------------------------------------------------------------

class TestCastManagement:
    @pytest.mark.asyncio
    async def test_add_cast(
        self, db_session: AsyncSession, media_item: MediaItem, person: Person
    ):
        service = PersonService(db_session)
        cast = await service.add_cast(
            media_item_guid=media_item.guid,
            person_guid=person.guid,
            character="Hero",
            department="Acting",
            job="Actor",
            cast_order=0,
        )
        assert cast.guid is not None
        assert cast.character == "Hero"
        assert cast.department == "Acting"
        assert cast.cast_order == 0

    @pytest.mark.asyncio
    async def test_get_cast_for_media(
        self, db_session: AsyncSession, media_item: MediaItem, person: Person
    ):
        service = PersonService(db_session)
        await service.add_cast(
            media_item_guid=media_item.guid,
            person_guid=person.guid,
            character="Hero",
            cast_order=0,
        )
        p2 = Person(guid=uuid.uuid4(), tmdb_id=99999, name="Jane Smith")
        db_session.add(p2)
        await db_session.flush()
        await service.add_cast(
            media_item_guid=media_item.guid,
            person_guid=p2.guid,
            character="Villain",
            cast_order=1,
        )

        cast_list = await service.get_cast_for_media(media_item.guid)
        assert len(cast_list) == 2
        assert cast_list[0].character == "Hero"
        assert cast_list[1].character == "Villain"

    @pytest.mark.asyncio
    async def test_get_cast_for_media_empty(self, db_session: AsyncSession):
        service = PersonService(db_session)
        cast_list = await service.get_cast_for_media(uuid.uuid4())
        assert len(cast_list) == 0

    @pytest.mark.asyncio
    async def test_get_media_for_person(
        self, db_session: AsyncSession, media_item: MediaItem, person: Person
    ):
        service = PersonService(db_session)
        await service.add_cast(
            media_item_guid=media_item.guid,
            person_guid=person.guid,
            character="Hero",
        )
        result = await service.get_media_for_person(person.guid)
        assert len(result) == 1
        assert result[0].media_item_guid == media_item.guid


# ---------------------------------------------------------------------------
# TMDB import
# ---------------------------------------------------------------------------

class TestImportCastFromTMDB:
    @pytest.mark.asyncio
    async def test_import_cast_and_crew(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        service = PersonService(db_session)
        credits_data = {
            "cast": [
                {
                    "id": 1001,
                    "name": "Actor One",
                    "character": "Hero",
                    "profile_path": "/a1.jpg",
                    "known_for_department": "Acting",
                    "order": 0,
                },
                {
                    "id": 1002,
                    "name": "Actor Two",
                    "character": "Villain",
                    "order": 1,
                },
            ],
            "crew": [
                {
                    "id": 2001,
                    "name": "Director One",
                    "job": "Director",
                    "department": "Directing",
                    "profile_path": "/d1.jpg",
                },
                {
                    "id": 2002,
                    "name": "Camera Operator",
                    "job": "Camera Operator",
                    "department": "Camera",
                },
            ],
        }

        entries = await service.import_cast_from_tmdb(
            media_item.guid, credits_data, max_cast=25, max_crew=10
        )
        # 2 cast + 1 crew (only Director is in important_jobs; Camera Operator is not)
        assert len(entries) == 3
        assert entries[0].character == "Hero"
        assert entries[0].department == "Acting"
        assert entries[2].job == "Director"

    @pytest.mark.asyncio
    async def test_import_cast_skips_missing_id(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        service = PersonService(db_session)
        credits_data = {
            "cast": [
                {"name": "No ID Actor", "character": "Extra"},
            ],
            "crew": [],
        }
        entries = await service.import_cast_from_tmdb(media_item.guid, credits_data)
        assert len(entries) == 0

    @pytest.mark.asyncio
    async def test_import_cast_max_limits(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        service = PersonService(db_session)
        credits_data = {
            "cast": [
                {"id": 3000 + i, "name": f"Actor {i}", "character": f"Char {i}", "order": i}
                for i in range(10)
            ],
            "crew": [
                {"id": 4000 + i, "name": f"Director {i}", "job": "Director", "department": "Directing"}
                for i in range(5)
            ],
        }
        entries = await service.import_cast_from_tmdb(
            media_item.guid, credits_data, max_cast=3, max_crew=2
        )
        assert len(entries) == 5  # 3 cast + 2 crew

    @pytest.mark.asyncio
    async def test_import_cast_tv_aggregate_credits(
        self, db_session: AsyncSession, media_item: MediaItem
    ):
        """Test import with TV aggregate credits format (roles/jobs arrays)."""
        service = PersonService(db_session)
        credits_data = {
            "cast": [
                {
                    "id": 5001,
                    "name": "TV Actor",
                    "roles": [{"character": "Detective"}],
                    "order": 0,
                },
            ],
            "crew": [
                {
                    "id": 5002,
                    "name": "TV Director",
                    "jobs": [{"job": "Director"}],
                    "department": "Directing",
                },
            ],
        }
        entries = await service.import_cast_from_tmdb(media_item.guid, credits_data)
        assert len(entries) == 2
        assert entries[0].character == "Detective"
        assert entries[1].job == "Director"
