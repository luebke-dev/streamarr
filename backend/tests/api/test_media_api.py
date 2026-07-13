"""Tests for the Media API endpoints (/api/media/*)."""

import uuid
import base64
import json
from io import BytesIO
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.activity_log import ActivityLog
from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaType,
)
from streamarr.models.person import MediaCast, Person
from streamarr.models.user import User

from .conftest import auth_headers


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _create_library(db: AsyncSession, **overrides) -> Library:
    now = datetime.now(UTC)
    defaults = dict(
        guid=uuid.uuid4(),
        name="Test Movies",
        type="MOVIES",
        plugin_id="movies",
        path="/data/library/movies",
        enabled=True,
        settings=None,
        description=None,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    lib = Library(**defaults)
    db.add(lib)
    await db.commit()
    await db.refresh(lib)
    return lib


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    now = datetime.now(UTC)
    defaults = dict(
        guid=uuid.uuid4(),
        title="Test Movie",
        media_type=MediaType.MOVIES,
        library_guid=None,
        parent_guid=None,
        availability_status=AvailabilityStatus.UNKNOWN,
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    if not hasattr(MediaItem, "library_guid"):
        defaults.pop("library_guid", None)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


# ============================================================================
# MEDIA ITEMS CRUD
# ============================================================================


class TestListMediaItems:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/media")
        assert resp.status_code == 401

    async def test_empty_list(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get("/api/media", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_returns_items(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib = await _create_library(db_session)
        await _create_media_item(
            db_session, title="Inception", library_guid=lib.guid, media_type=MediaType.MOVIES
        )
        resp = await client.get("/api/media", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        titles = [i["title"] for i in data["items"]]
        assert "Inception" in titles

    async def test_filter_by_media_type(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib_m = await _create_library(db_session, type="MOVIES")
        lib_s = await _create_library(db_session, type="SHOWS", name="Shows")
        await _create_media_item(
            db_session, title="Movie1", library_guid=lib_m.guid, media_type=MediaType.MOVIES
        )
        await _create_media_item(
            db_session, title="Show1", library_guid=lib_s.guid, media_type=MediaType.SHOWS
        )
        resp = await client.get(
            "/api/media", headers=user_headers, params={"media_type": "MOVIES"}
        )
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Movie1" in titles
        assert "Show1" not in titles

    async def test_filter_by_search_term(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        await _create_media_item(
            db_session,
            title="Visible Title",
            description="A quiet space opera",
            media_type=MediaType.MOVIES,
        )
        await _create_media_item(
            db_session,
            title="Other",
            description="Unrelated",
            media_type=MediaType.MOVIES,
        )

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"search_term": "space opera"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Visible Title"

    async def test_filter_by_library(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib = await _create_library(db_session)
        await _create_media_item(
            db_session, title="In Library", library_guid=lib.guid, media_type=MediaType.MOVIES
        )
        await _create_media_item(
            db_session, title="No Library", media_type=MediaType.MOVIES
        )
        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"library_guid": str(lib.guid)},
        )
        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "In Library" in titles

    async def test_filter_by_availability_local(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaFile

        local = await _create_media_item(db_session, title="Local")
        remote = await _create_media_item(db_session, title="Remote")
        db_session.add(
            MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=local.guid,
                file_path="/library/movies/local.mkv",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"availability": "local"},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Local" in titles
        assert "Remote" not in titles

    async def test_filter_by_availability_releases(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaRelease

        with_release = await _create_media_item(db_session, title="Has Release")
        none = await _create_media_item(db_session, title="No Release")
        db_session.add(
            MediaRelease(
                guid=uuid.uuid4(),
                media_item_guid=with_release.guid,
                title="Release",
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"availability": "releases"},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Has Release" in titles
        assert "No Release" not in titles

    async def test_filter_by_metadata_completeness(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        await _create_media_item(
            db_session,
            title="Complete",
            poster_path="/poster.jpg",
            description="Description",
        )
        await _create_media_item(db_session, title="Incomplete")

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"has_poster": True, "has_description": True},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Complete" in titles
        assert "Incomplete" not in titles

    async def test_filter_by_release_year_rating_and_backdrop(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        await _create_media_item(
            db_session,
            title="Matching",
            release_date=datetime(2020, 5, 1, tzinfo=UTC),
            content_rating="PG-13",
            backdrop_path="/backdrop.jpg",
        )
        await _create_media_item(
            db_session,
            title="Wrong Year",
            release_date=datetime(2021, 5, 1, tzinfo=UTC),
            content_rating="PG-13",
            backdrop_path="/backdrop.jpg",
        )
        await _create_media_item(
            db_session,
            title="No Backdrop",
            release_date=datetime(2020, 5, 1, tzinfo=UTC),
            content_rating="PG-13",
        )

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={
                "year": 2020,
                "content_rating": "PG-13",
                "has_backdrop": True,
            },
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert titles == ["Matching"]

    async def test_filter_by_studio_name(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        # extra_data is now structured JSON(B); the studio filter reads into the
        # ``production_companies`` key, so store a native object (not a
        # json.dumps'd string, which structured JSON access cannot descend into).
        await _create_media_item(
            db_session,
            title="Studio Match",
            extra_data={"production_companies": [{"name": "Studio One"}]},
        )
        await _create_media_item(
            db_session,
            title="Other Studio",
            extra_data={"production_companies": [{"name": "Studio Two"}]},
        )

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"studio_name": "Studio One"},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Studio Match" in titles
        assert "Other Studio" not in titles

    async def test_filter_by_container(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        matching = await _create_media_item(db_session, title="Matroska")
        other = await _create_media_item(db_session, title="MP4")
        db_session.add_all(
            [
                MediaFile(
                    media_item_guid=matching.guid,
                    file_path="/media/movie.mkv",
                    file_name="movie.mkv",
                    format="mkv",
                ),
                MediaFile(
                    media_item_guid=other.guid,
                    file_path="/media/movie.mp4",
                    file_name="movie.mp4",
                    format="mp4",
                ),
            ]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"container": "MKV"},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Matroska" in titles
        assert "MP4" not in titles

    async def test_filter_by_person(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        matching = await _create_media_item(db_session, title="Cast Match")
        other = await _create_media_item(db_session, title="Other Cast")
        person = Person(name="Keanu Reeves")
        other_person = Person(name="Carrie-Anne Moss")
        db_session.add_all([person, other_person])
        await db_session.commit()
        await db_session.refresh(person)
        await db_session.refresh(other_person)
        db_session.add_all(
            [
                MediaCast(media_item_guid=matching.guid, person_guid=person.guid),
                MediaCast(media_item_guid=other.guid, person_guid=other_person.guid),
            ]
        )
        await db_session.commit()

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"person_guid": str(person.guid)},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "Cast Match" in titles
        assert "Other Cast" not in titles

    async def test_filter_by_favorite_and_played_state(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.viewing_history import ViewingHistory
        from streamarr.services.list import ListService

        favorite = await _create_media_item(db_session, title="Favorite")
        played = await _create_media_item(db_session, title="Played")
        await _create_media_item(db_session, title="Other")
        # Favorites are stored as items of the user's FAVORITES list.
        await ListService(db_session).toggle_favorite(
            test_user.guid, favorite.guid, "movies"
        )
        db_session.add(
            ViewingHistory(
                user_guid=test_user.guid,
                media_item_guid=played.guid,
                is_completed=True,
            )
        )
        await db_session.commit()

        favorite_resp = await client.get(
            "/api/media", headers=user_headers, params={"is_favorite": True}
        )
        played_resp = await client.get(
            "/api/media", headers=user_headers, params={"is_played": True}
        )

        assert favorite_resp.status_code == 200
        assert [i["title"] for i in favorite_resp.json()["items"]] == ["Favorite"]
        assert played_resp.status_code == 200
        assert [i["title"] for i in played_resp.json()["items"]] == ["Played"]

    async def test_filter_by_platform(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import media_platform_table
        from streamarr.models.platform import Platform

        pc = Platform(name="PC")
        switch = Platform(name="Switch")
        db_session.add_all([pc, switch])
        await db_session.commit()
        await db_session.refresh(pc)
        await db_session.refresh(switch)

        game = await _create_media_item(
            db_session, title="PC Game", media_type=MediaType.GAMES
        )
        other = await _create_media_item(
            db_session, title="Switch Game", media_type=MediaType.GAMES
        )
        await db_session.execute(
            media_platform_table.insert().values(
                media_item_guid=game.guid,
                platform_id=pc.id,
            )
        )
        await db_session.execute(
            media_platform_table.insert().values(
                media_item_guid=other.guid,
                platform_id=switch.id,
            )
        )
        await db_session.commit()

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"media_type": "GAMES", "platform_id": pc.id},
        )

        assert resp.status_code == 200
        titles = [i["title"] for i in resp.json()["items"]]
        assert "PC Game" in titles
        assert "Switch Game" not in titles

    async def test_parent_filter_total_counts_only_children(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        parent = await _create_media_item(
            db_session, title="Parent", media_type=MediaType.SHOWS
        )
        await _create_media_item(
            db_session,
            title="Child",
            media_type=MediaType.SHOWS,
            parent_guid=parent.guid,
        )
        await _create_media_item(db_session, title="Other", media_type=MediaType.SHOWS)

        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"parent_guid": str(parent.guid)},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["title"] == "Child"

    async def test_pagination(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib = await _create_library(db_session)
        for i in range(5):
            await _create_media_item(
                db_session,
                title=f"Item {i}",
                library_guid=lib.guid,
                media_type=MediaType.MOVIES,
            )
        resp = await client.get(
            "/api/media", headers=user_headers, params={"page": 1, "per_page": 2}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["total"] >= 5
        assert data["total_pages"] >= 3

    async def test_order_desc(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib = await _create_library(db_session)
        await _create_media_item(
            db_session, title="Alpha", library_guid=lib.guid, media_type=MediaType.MOVIES
        )
        await _create_media_item(
            db_session, title="Zeta", library_guid=lib.guid, media_type=MediaType.MOVIES
        )
        resp = await client.get(
            "/api/media",
            headers=user_headers,
            params={"order_by": "title", "order_desc": False},
        )
        assert resp.status_code == 200


class TestCreateMediaItem:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/media", json={"title": "x", "media_type": "MOVIES"})
        assert resp.status_code == 401

    async def test_create_success(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/media",
            headers=admin_headers,
            json={
                "title": "New Movie",
                "media_type": "MOVIES",
                "description": "A test movie",
            },
        )
        assert resp.status_code == 200, f"Response: {resp.text}"
        data = resp.json()
        assert data["title"] == "New Movie"
        assert data["media_type"] == "MOVIES"

    async def test_create_with_optional_fields(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        lib = await _create_library(db_session)
        resp = await client.post(
            "/api/media",
            headers=admin_headers,
            json={
                "title": "Detailed Movie",
                "media_type": "MOVIES",
                "library_guid": str(lib.guid),
                "original_title": "Original Title",
                "description": "Great description",
                "tagline": "Catchy tagline",
                "poster_path": "/posters/movie.jpg",
                "backdrop_path": "/backdrops/movie.jpg",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["original_title"] == "Original Title"
        assert data["tagline"] == "Catchy tagline"

    async def test_create_child_item(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        lib = await _create_library(db_session, type="SHOWS", name="Shows")
        show = await _create_media_item(
            db_session, title="My Show", library_guid=lib.guid, media_type=MediaType.SHOWS
        )
        resp = await client.post(
            "/api/media",
            headers=admin_headers,
            json={
                "title": "Season 1",
                "media_type": "SHOWS",
                "library_guid": str(lib.guid),
                "parent_guid": str(show.guid),
                "sequence_number": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["parent_guid"] == str(show.guid)
        assert data["sequence_number"] == 1

    async def test_regular_user_forbidden(
        self, client: AsyncClient, user_headers
    ):
        resp = await client.post(
            "/api/media",
            headers=user_headers,
            json={"title": "New Movie", "media_type": "MOVIES"},
        )
        assert resp.status_code == 403


class TestGetMediaItem:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(f"/api/media/{uuid.uuid4()}", headers=user_headers)
        assert resp.status_code == 404

    async def test_get_by_guid(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        lib = await _create_library(db_session)
        item = await _create_media_item(
            db_session,
            title="The Matrix",
            library_guid=lib.guid,
            media_type=MediaType.MOVIES,
            description="Sci-fi classic",
        )
        resp = await client.get(f"/api/media/{item.guid}", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["guid"] == str(item.guid)
        assert data["title"] == "The Matrix"
        assert data["description"] == "Sci-fi classic"

    async def test_get_with_load_options(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        lib = await _create_library(db_session)
        item = await _create_media_item(db_session, library_guid=lib.guid, media_type=MediaType.MOVIES)
        resp = await client.get(
            f"/api/media/{item.guid}",
            headers=user_headers,
            params={"load_files": False, "load_releases": False, "load_external_ids": False},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["files"] == []
        assert data["releases"] == []
        assert data["external_ids"] == []
        assert data["external_links"] == []

    async def test_get_by_guid_includes_external_links(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(
            db_session,
            title="The Matrix",
            media_type=MediaType.MOVIES,
            extra_data={"external_ids": {"imdb": "tt0133093"}},
        )
        db_session.add(
            MediaExternalId(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                provider="tmdb",
                external_id="603",
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}", headers=user_headers)

        assert resp.status_code == 200
        links = {link["provider"]: link for link in resp.json()["external_links"]}
        assert links["tmdb"]["url"] == "https://www.themoviedb.org/movie/603"
        assert links["imdb"]["url"] == "https://www.imdb.com/title/tt0133093/"

    async def test_get_by_guid_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_by_guid_hides_parental_blocked_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}", headers=user_headers)
        assert resp.status_code == 404


class TestUpdateMediaItem:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.patch(f"/api/media/{uuid.uuid4()}", json={"title": "x"})
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_superuser: User, admin_headers):
        resp = await client.patch(
            f"/api/media/{uuid.uuid4()}", headers=admin_headers, json={"title": "x"}
        )
        assert resp.status_code == 404

    async def test_update_title(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session, title="Old Title")
        resp = await client.patch(
            f"/api/media/{item.guid}",
            headers=admin_headers,
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        assert resp.json()["title"] == "New Title"

    async def test_update_multiple_fields(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.patch(
            f"/api/media/{item.guid}",
            headers=admin_headers,
            json={
                "title": "Updated",
                "description": "Updated desc",
                "availability_status": "available",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated"
        assert data["description"] == "Updated desc"
        assert data["availability_status"] == "available"

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session, title="Old Title")
        resp = await client.patch(
            f"/api/media/{item.guid}",
            headers=user_headers,
            json={"title": "New Title"},
        )
        assert resp.status_code == 403


class TestManualMetadataUpdate:
    async def test_manual_metadata_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session, title="Old Title")

        resp = await client.put(
            f"/api/media/{item.guid}/metadata/manual",
            headers=user_headers,
            json={"title": "New Title"},
        )

        assert resp.status_code == 403

    async def test_manual_metadata_update(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            title="Old Title",
            extra_data=json.dumps({"provider": "tmdb"}),
        )

        resp = await client.put(
            f"/api/media/{item.guid}/metadata/manual",
            headers=admin_headers,
            json={
                "title": "Director's Cut",
                "description": "Manual description",
                "content_rating": "PG-13",
                "min_age": 13,
                "poster_path": "/images/manual.jpg",
                "custom_metadata": {"edition": "director"},
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Director's Cut"
        assert data["description"] == "Manual description"
        assert data["content_rating"] == "PG-13"
        assert data["min_age"] == 13
        assert data["poster_path"] == "/images/manual.jpg"
        extra_data = data["extra_data"]
        assert extra_data["provider"] == "tmdb"
        assert extra_data["manual_metadata"]["edition"] == "director"
        assert data["last_metadata_updated_at"] is not None

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "metadata.manual_update")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "custom_metadata" in log_entry.extra_data

    async def test_manual_metadata_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            f"/api/media/{uuid.uuid4()}/metadata/manual",
            headers=admin_headers,
            json={"title": "Missing"},
        )

        assert resp.status_code == 404

    async def test_search_identify_candidates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(
            db_session,
            title="Wrong Title",
            extra_data=json.dumps(
                {
                    "identify_results": [
                        {
                            "provider": "tmdb",
                            "id": "603",
                            "title": "The Matrix",
                            "overview": "A hacker learns the truth.",
                            "poster_path": "/matrix.jpg",
                            "score": 98,
                        }
                    ]
                }
            ),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/metadata/identify",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "tmdb"
        assert data["items"][0]["provider_id"] == "603"
        assert data["items"][0]["title"] == "The Matrix"

    async def test_search_live_identify_candidates(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import media as media_api

        item = await _create_media_item(db_session, title="Wrong Title")
        search_identify = AsyncMock(
            return_value=[
                {
                    "provider": "tmdb",
                    "provider_id": "603",
                    "title": "The Matrix",
                    "description": "A hacker learns the truth.",
                    "poster_path": "/matrix.jpg",
                    "score": 98,
                }
            ]
        )
        metadata_service = MagicMock()
        metadata_service.search_identify_candidates = search_identify
        monkeypatch.setattr(
            media_api,
            "MetadataService",
            lambda db: metadata_service,
        )

        resp = await client.get(
            f"/api/media/{item.guid}/metadata/identify/live?provider=tmdb&query=matrix",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "tmdb"
        assert data["items"][0]["provider_id"] == "603"
        search_identify.assert_awaited_once()
        assert search_identify.await_args.kwargs["query"] == "matrix"
        assert search_identify.await_args.kwargs["media_type"] == "movie"

    async def test_apply_identify_candidate_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {"identify_results": [{"provider": "tmdb", "id": "603", "title": "The Matrix"}]}
            ),
        )

        resp = await client.put(
            f"/api/media/{item.guid}/metadata/identify",
            headers=user_headers,
            json={"provider": "tmdb", "provider_id": "603"},
        )

        assert resp.status_code == 403

    async def test_apply_identify_candidate(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(
            db_session,
            title="Wrong Title",
            extra_data=json.dumps(
                {
                    "identify_results": [
                        {
                            "provider": "tmdb",
                            "id": "603",
                            "title": "The Matrix",
                            "original_title": "The Matrix",
                            "overview": "A hacker learns the truth.",
                            "poster_path": "/matrix.jpg",
                            "backdrop_path": "/matrix-backdrop.jpg",
                            "score": 98,
                        }
                    ]
                }
            ),
        )

        resp = await client.put(
            f"/api/media/{item.guid}/metadata/identify",
            headers=admin_headers,
            json={"provider": "tmdb", "provider_id": "603"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "The Matrix"
        assert data["description"] == "A hacker learns the truth."
        assert data["poster_path"] == "/matrix.jpg"
        extra_data = data["extra_data"]
        assert extra_data["external_ids"]["tmdb"] == "603"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "metadata.identify_apply")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "603" in log_entry.extra_data

    async def test_apply_identify_candidate_not_found(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/metadata/identify",
            headers=admin_headers,
            json={"provider": "tmdb", "provider_id": "missing"},
        )

        assert resp.status_code == 404


class TestDeleteMediaItem:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.delete(f"/api/media/{uuid.uuid4()}")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.delete(f"/api/media/{uuid.uuid4()}", headers=user_headers)
        assert resp.status_code == 404

    async def test_delete_success(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session, title="ToDelete")
        resp = await client.delete(f"/api/media/{item.guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert "deleted" in resp.json()["message"].lower()

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session, title="ToDelete")
        resp = await client.delete(f"/api/media/{item.guid}", headers=user_headers)
        assert resp.status_code == 403


# ============================================================================
# SEARCH
# ============================================================================


class TestSearchMedia:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/media/search/query", params={"q": "test"})
        assert resp.status_code == 401

    async def test_search_by_title(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        await _create_media_item(db_session, title="Inception", media_type=MediaType.MOVIES)
        await _create_media_item(db_session, title="Interstellar", media_type=MediaType.MOVIES)
        await _create_media_item(db_session, title="The Dark Knight", media_type=MediaType.MOVIES)

        resp = await client.get(
            "/api/media/search/query", headers=user_headers, params={"q": "Inter"}
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1
        titles = [r["title"] for r in data["results"]]
        assert "Interstellar" in titles

    async def test_search_no_results(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/media/search/query",
            headers=user_headers,
            params={"q": "NonexistentMovie12345"},
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    async def test_search_filter_by_type(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        await _create_media_item(db_session, title="The Movie", media_type=MediaType.MOVIES)
        await _create_media_item(db_session, title="The Show", media_type=MediaType.SHOWS)

        resp = await client.get(
            "/api/media/search/query",
            headers=user_headers,
            params={"q": "The", "media_type": "MOVIES"},
        )
        assert resp.status_code == 200
        titles = [r["title"] for r in resp.json()["results"]]
        assert "The Movie" in titles


# ============================================================================
# HIERARCHICAL OPERATIONS
# ============================================================================


class TestMediaItemChildren:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/children")
        assert resp.status_code == 401

    async def test_empty_children(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session, title="Show")
        resp = await client.get(
            f"/api/media/{item.guid}/children", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_get_children(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(db_session, title="My Show", media_type=MediaType.SHOWS)
        await _create_media_item(
            db_session,
            title="Season 1",
            media_type=MediaType.SHOWS,
            parent_guid=show.guid,
            sequence_number=1,
        )
        await _create_media_item(
            db_session,
            title="Season 2",
            media_type=MediaType.SHOWS,
            parent_guid=show.guid,
            sequence_number=2,
        )
        resp = await client.get(
            f"/api/media/{show.guid}/children", headers=user_headers
        )
        assert resp.status_code == 200
        children = resp.json()
        assert len(children) == 2
        assert children[0]["sequence_number"] == 1
        assert children[1]["sequence_number"] == 2


class TestShowHierarchy:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/shows/{uuid.uuid4()}/hierarchy")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/shows/{uuid.uuid4()}/hierarchy", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_hierarchy(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(db_session, title="Breaking Bad", media_type=MediaType.SHOWS)
        season = await _create_media_item(
            db_session,
            title="Season 1",
            media_type=MediaType.SHOWS,
            parent_guid=show.guid,
            sequence_number=1,
        )
        await _create_media_item(
            db_session,
            title="Pilot",
            media_type=MediaType.SHOWS,
            parent_guid=season.guid,
            sequence_number=1,
        )
        resp = await client.get(
            f"/api/media/shows/{show.guid}/hierarchy", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["show"]["title"] == "Breaking Bad"
        assert len(data["seasons"]) == 1
        assert len(data["seasons"][0]["episodes"]) == 1


class TestAlbumTracks:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/albums/{uuid.uuid4()}/tracks")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/albums/{uuid.uuid4()}/tracks", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_album_tracks(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        album = await _create_media_item(
            db_session, title="My Album", media_type=MediaType.ALBUMS
        )
        await _create_media_item(
            db_session,
            title="Track 1",
            media_type=MediaType.SONGS,
            parent_guid=album.guid,
            sequence_number=1,
        )
        await _create_media_item(
            db_session,
            title="Track 2",
            media_type=MediaType.SONGS,
            parent_guid=album.guid,
            sequence_number=2,
        )
        resp = await client.get(
            f"/api/media/albums/{album.guid}/tracks", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["album"]["title"] == "My Album"
        assert len(data["tracks"]) == 2


# ============================================================================
# RELEASES
# ============================================================================


class TestMediaReleases:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/releases")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/releases", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_empty_releases(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.get(
            f"/api/media/{item.guid}/releases", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_create_release(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/releases",
            headers=admin_headers,
            json={
                "title": "Movie.2024.1080p.BluRay.x264",
                "media_item_guid": str(item.guid),
                "size": 1500000000,
                "quality": "1080p",
                "score": 85,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Movie.2024.1080p.BluRay.x264"
        assert data["quality"] == "1080p"

    async def test_create_release_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/releases",
            headers=user_headers,
            json={
                "title": "Movie.2024.1080p.BluRay.x264",
                "media_item_guid": str(item.guid),
            },
        )
        assert resp.status_code == 403

    async def test_create_release_for_missing_item(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        fake_guid = uuid.uuid4()
        resp = await client.post(
            f"/api/media/{fake_guid}/releases",
            headers=user_headers,
            json={
                "title": "Some Release",
                "media_item_guid": str(fake_guid),
            },
        )
        assert resp.status_code == 404


# ============================================================================
# EXTERNAL IDS
# ============================================================================


class TestExternalIds:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(
            "/api/media/external/tmdb/12345", params={"media_type": "MOVIES"}
        )
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            "/api/media/external/tmdb/99999",
            headers=user_headers,
            params={"media_type": "MOVIES"},
        )
        assert resp.status_code == 404

    async def test_get_by_external_id_success(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session, title="The Matrix", media_type=MediaType.MOVIES)
        ext_id = MediaExternalId(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            provider="tmdb",
            external_id="603",
        )
        db_session.add(ext_id)
        await db_session.commit()

        resp = await client.get(
            "/api/media/external/tmdb/603",
            headers=user_headers,
            params={"media_type": "MOVIES"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["guid"] == str(item.guid)
        assert data["title"] == "The Matrix"
        assert data["external_ids"][0]["provider"] == "tmdb"

    async def test_external_links_from_stored_and_extra_ids(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        lib = await _create_library(db_session)
        item = await _create_media_item(
            db_session,
            title="The Matrix",
            media_type=MediaType.MOVIES,
            library_guid=lib.guid,
            extra_data=json.dumps({"external_ids": {"imdb": "tt0133093", "tvdb": "12345"}}),
        )
        db_session.add(
            MediaExternalId(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                provider="tmdb",
                external_id="603",
            )
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/external-links", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        links = {link["provider"]: link for link in data["items"]}
        assert links["tmdb"]["url"] == "https://www.themoviedb.org/movie/603"
        assert links["imdb"]["url"] == "https://www.imdb.com/title/tt0133093/"
        assert links["tvdb"]["url"] == "https://thetvdb.com/dereferrer/series/12345"

    async def test_external_links_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/external-links", headers=user_headers)
        assert resp.status_code == 404


# ============================================================================
# DOWNLOAD RELEASE
# ============================================================================


class TestDownloadRelease:
    async def test_item_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/media/{uuid.uuid4()}/releases/{uuid.uuid4()}/download",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_release_not_found(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/releases/{uuid.uuid4()}/download",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_no_download_links(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaRelease

        item = await _create_media_item(db_session)
        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            title="Test.Release.1080p",
            score=50,
        )
        db_session.add(release)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/releases/{release.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 400
        assert "no download links" in resp.json()["detail"].lower()

    @patch("streamarr.api.v1.media.add_download")
    async def test_download_movie_success(
        self,
        mock_add_download,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        from streamarr.models.media import MediaRelease, MediaReleaseLink

        mock_add_download.kiq = AsyncMock()

        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            title="Movie.2024.1080p",
            score=80,
        )
        db_session.add(release)
        await db_session.flush()

        link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link="https://example.com/nzb/123",
            link_type="nzb",
        )
        db_session.add(link)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/releases/{release.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["status"] == "queued"
        assert data["release_title"] == "Movie.2024.1080p"
        mock_add_download.kiq.assert_called_once()

    @patch("streamarr.api.v1.media.add_show_download")
    async def test_download_show_success(
        self,
        mock_add_show_download,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        from streamarr.models.media import MediaRelease, MediaReleaseLink

        mock_add_show_download.kiq = AsyncMock()

        item = await _create_media_item(db_session, media_type=MediaType.SHOWS)
        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            title="Show.S01E01.1080p",
            score=70,
        )
        db_session.add(release)
        await db_session.flush()

        link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link="magnet:?xt=urn:btih:abc",
            link_type="magnet",
        )
        db_session.add(link)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/releases/{release.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 202
        mock_add_show_download.kiq.assert_called_once()


# ============================================================================
# DOWNLOADS
# ============================================================================


class TestGetMediaItemDownloads:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/downloads")
        assert resp.status_code == 401

    async def test_forbidden_for_regular_user(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.get(
            f"/api/media/{item.guid}/downloads", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_item_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/downloads", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_success_with_downloads(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        from streamarr.models.downloads import Download
        from streamarr.models.downloader import Downloader
        from streamarr.models.media import MediaRelease, MediaReleaseLink

        item = await _create_media_item(db_session)

        release = MediaRelease(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            title="Test.Release",
            score=50,
        )
        db_session.add(release)
        await db_session.flush()

        link = MediaReleaseLink(
            guid=uuid.uuid4(),
            media_release_guid=release.guid,
            link="https://example.com/nzb",
            link_type="nzb",
        )
        db_session.add(link)
        await db_session.flush()

        downloader = Downloader(
            guid=uuid.uuid4(),
            label="SABnzbd",
            host="http://localhost:8080",
            type="sabnzbd",
        )
        db_session.add(downloader)
        await db_session.flush()

        download = Download(
            guid=uuid.uuid4(),
            title="Test.Release",
            type="nzb",
            downloader_id=downloader.guid,
            status="completed",
            progress=100.0,
            external_id="sab_123",
            media_release_link_guid=link.guid,
            user_guid=test_superuser.guid,
        )
        db_session.add(download)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/downloads", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["title"] == "Test.Release"
        assert data[0]["status"] == "completed"


# ============================================================================
# AVAILABILITY STATUS
# ============================================================================


class TestUpdateAvailability:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.patch(
            f"/api/media/{uuid.uuid4()}/availability",
            params={"status": "available"},
        )
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.patch(
            f"/api/media/{uuid.uuid4()}/availability",
            headers=user_headers,
            params={"status": "available"},
        )
        assert resp.status_code == 404

    async def test_update_success(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.patch(
            f"/api/media/{item.guid}/availability",
            headers=admin_headers,
            params={"status": "available"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "available"

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.patch(
            f"/api/media/{item.guid}/availability",
            headers=user_headers,
            params={"status": "available"},
        )
        assert resp.status_code == 403


class TestAvailabilityAndWatchAccess:
    async def test_get_availability_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/availability",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_get_availability_hides_parental_blocked_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/availability",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_get_availability_success_uses_shared_policy(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_headers,
    ):
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        availability = SimpleNamespace(
            status="available",
            target_guid=item.guid,
            target_action="play",
            progress_seconds=None,
            download_progress=None,
            download_status=None,
            is_watched=False,
        )

        with patch(
            "streamarr.services.availability.check_availability",
            AsyncMock(return_value=availability),
        ):
            resp = await client.get(
                f"/api/media/{item.guid}/availability",
                headers=user_headers,
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "available"

    async def test_watch_denies_disallowed_library(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        await db_session.commit()

        resp = await client.post(f"/api/media/{item.guid}/watch", headers=user_headers)
        assert resp.status_code == 403

    async def test_watch_hides_parental_blocked_item(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            media_type=MediaType.MOVIES,
            min_age=18,
        )
        await db_session.commit()

        resp = await client.post(f"/api/media/{item.guid}/watch", headers=user_headers)
        assert resp.status_code == 404

    async def test_watch_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        user_headers,
    ):
        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)

        resp = await client.post(f"/api/media/{item.guid}/watch", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["is_watched"] is True


# ============================================================================
# STREAMS
# ============================================================================


class TestGetMediaStreams:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/streams")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/streams", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_no_files(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["audio_streams"] == []
        assert data["subtitle_streams"] == []
        assert data["quality_options"] == []

    async def test_streams_with_structured_probe_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        import json
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        probe = json.dumps({
            "video_streams": [{"index": 0, "codec_name": "h264", "width": 1920, "height": 1080}],
            "audio_streams": [
                {"index": 1, "codec_name": "aac", "language": "eng", "title": "English", "channels": 2, "sample_rate": "48000", "bit_rate": "128000"},
                {"index": 2, "codec_name": "dts", "language": "ger", "title": "German", "channels": 6, "sample_rate": "48000", "bit_rate": "768000"},
            ],
            "subtitle_streams": [
                {"index": 3, "codec_name": "srt", "language": "eng", "title": "English", "forced": False, "default": True},
            ],
        })
        media_file = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/test.mkv",
            quality="1080p",
            height=1080,
            probe_data=probe,
        )
        db_session.add(media_file)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["audio_streams"]) == 2
        assert data["audio_streams"][0]["language"] == "eng"
        assert data["audio_streams"][1]["language"] == "ger"
        assert len(data["subtitle_streams"]) == 1
        assert data["subtitle_streams"][0]["language"] == "eng"
        assert len(data["quality_options"]) == 3  # 1080p file + 720p/480p transcode
        assert data["quality_options"][0]["label"] == "1080p"
        assert data["quality_options"][0]["source"] == "file"
        assert data["quality_options"][1]["label"] == "720p"
        assert data["quality_options"][1]["source"] == "transcode"
        assert data["quality_options"][1]["is_available"] is True
        assert data["quality_options"][2]["label"] == "480p"
        assert data["quality_options"][2]["source"] == "transcode"

    async def test_streams_include_managed_uploaded_subtitles(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        import json
        from streamarr.models.media import MediaFile

        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "subtitles": [
                        {
                            "id": "upload:sub-en",
                            "language": "en",
                            "title": "English Uploaded",
                            "format": "vtt",
                            "path": "uploaded:upload:sub-en",
                            "is_default": True,
                        },
                        {
                            "id": "remote-de",
                            "language": "de",
                            "title": "German Remote",
                            "format": "vtt",
                            "url": "https://subtitles.test/de.vtt",
                        },
                    ]
                }
            ),
        )
        media_file = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/test.mp4",
            quality="1080p",
            height=1080,
            probe_data=json.dumps({"audio_streams": [], "subtitle_streams": []}),
        )
        db_session.add(media_file)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )

        assert resp.status_code == 200
        subtitles = resp.json()["subtitle_streams"]
        assert len(subtitles) == 2
        uploaded = next(item for item in subtitles if item["id"] == "upload:sub-en")
        assert uploaded["source"] == "uploaded"
        assert uploaded["content_url"].endswith("/subtitles/upload%3Asub-en/content")
        assert uploaded["default"] is True
        remote = next(item for item in subtitles if item["id"] == "remote-de")
        assert remote["source"] == "managed"
        assert remote["url"] == "https://subtitles.test/de.vtt"
        assert remote["content_url"].endswith("/subtitles/remote-de/content")

    async def test_streams_with_legacy_ffprobe_format(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        import json
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        probe = json.dumps({
            "streams": [
                {"codec_type": "video", "codec_name": "h264", "width": 1920, "height": 1080, "index": 0},
                {"codec_type": "audio", "codec_name": "aac", "tags": {"language": "eng"}, "index": 1, "channels": 2},
            ],
        })
        media_file = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/legacy.mkv",
            quality="1080p",
            height=1080,
            probe_data=probe,
        )
        db_session.add(media_file)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        # Legacy format gets converted via structure_probe_data
        assert len(data["audio_streams"]) >= 1
        assert len(data["quality_options"]) == 3  # 1080p file + 720p/480p transcode

    async def test_streams_with_legacy_flat_format(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        import json
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        probe = json.dumps({
            "audio_codec": "aac",
            "video_codec": "h264",
            "audio_channels": "5.1",
        })
        media_file = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/flat.mkv",
            quality="720p",
            height=720,
            probe_data=probe,
        )
        db_session.add(media_file)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["audio_streams"]) == 1
        assert data["audio_streams"][0]["codec_name"] == "aac"
        assert len(data["quality_options"]) == 2  # 720p file + 480p transcode
        assert data["quality_options"][0]["label"] == "720p"
        assert data["quality_options"][1]["label"] == "480p"
        assert data["quality_options"][1]["source"] == "transcode"

    async def test_streams_quality_tiers(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        for quality, height in [("2160p", 2160), ("1080p", 1080), ("720p", 720), ("480p", 480)]:
            f = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                file_path=f"/data/movies/test_{quality}.mkv",
                quality=quality,
                height=height,
            )
            db_session.add(f)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/streams", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        labels = [q["label"] for q in data["quality_options"]]
        assert "4K" in labels
        assert "1080p" in labels
        assert "720p" in labels
        assert "480p" in labels


class TestGetMediaSources:
    async def test_media_sources_list_files_with_urls(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session, title="Multi Source Movie")
        lower = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/movie-720.mkv",
            file_name="movie-720.mkv",
            file_size=720,
            height=720,
            bitrate=4000,
            quality="720p",
            format="mkv",
            codec="h264",
        )
        higher = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/movie-1080.mkv",
            file_name="movie-1080.mkv",
            file_size=1080,
            height=1080,
            bitrate=8000,
            quality="1080p",
            format="mkv",
            codec="h265",
        )
        db_session.add_all([lower, higher])
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/media-sources",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["item_guid"] == str(item.guid)
        assert data["title"] == "Multi Source Movie"
        assert data["total"] == 2
        assert data["items"][0]["file_guid"] == str(higher.guid)
        assert data["items"][0]["is_default"] is True
        assert data["items"][0]["download_url"] == (
            f"/api/media/{item.guid}/files/{higher.guid}/download"
        )
        assert data["items"][0]["stream_url"] == (
            f"/api/stream/{item.guid}?file_guid={higher.guid}"
        )
        assert data["items"][1]["file_guid"] == str(lower.guid)

    async def test_media_sources_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(db_session)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/media-sources",
            headers=user_headers,
        )

        assert resp.status_code == 403


# ============================================================================
# REFRESH METADATA
# ============================================================================


class TestRefreshMetadata:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(f"/api/media/{uuid.uuid4()}/refresh-metadata")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.post(
            f"/api/media/{uuid.uuid4()}/refresh-metadata", headers=user_headers
        )
        assert resp.status_code == 404

    @patch("streamarr.worker.refresh_media_item_metadata")
    async def test_success(
        self,
        mock_refresh,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        mock_refresh.kiq = AsyncMock()

        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/refresh-metadata", headers=admin_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "queued" in data["message"].lower()
        mock_refresh.kiq.assert_called_once_with(str(item.guid))

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/refresh-metadata", headers=user_headers
        )
        assert resp.status_code == 403


# ============================================================================
# SHOW RESUME
# ============================================================================


class TestShowResume:
    async def _create_show_hierarchy(self, db, num_seasons=1, eps_per_season=3):
        """Helper to create a show with seasons and episodes."""
        show = await _create_media_item(
            db, title="Test Show", media_type=MediaType.SHOWS
        )
        episodes = []
        for s in range(1, num_seasons + 1):
            season = await _create_media_item(
                db,
                title=f"Season {s}",
                media_type=MediaType.SHOWS,
                parent_guid=show.guid,
                sequence_number=s,
            )
            for e in range(1, eps_per_season + 1):
                ep = await _create_media_item(
                    db,
                    title=f"S{s:02d}E{e:02d}",
                    media_type=MediaType.SHOWS,
                    parent_guid=season.guid,
                    sequence_number=e,
                )
                episodes.append(ep)
        return show, episodes

    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/shows/{uuid.uuid4()}/resume")
        assert resp.status_code == 401

    async def test_show_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/media/shows/{uuid.uuid4()}/resume", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_no_episodes(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Empty Show", media_type=MediaType.SHOWS
        )
        resp = await client.get(
            f"/api/media/shows/{show.guid}/resume", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_no_history_starts_s01e01(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show, episodes = await self._create_show_hierarchy(db_session)
        resp = await client.get(
            f"/api/media/shows/{show.guid}/resume", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "start"
        assert data["season_number"] == 1
        assert data["episode_number"] == 1

    async def test_in_progress_episode_resumes(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.viewing_history import ViewingHistory

        show, episodes = await self._create_show_hierarchy(db_session)
        # Mark second episode as in-progress
        history = ViewingHistory(
            guid=uuid.uuid4(),
            user_guid=test_user.guid,
            media_item_guid=episodes[1].guid,
            progress_seconds=300,
            duration_seconds=2400,
            progress_percentage=12.5,
            is_completed=False,
        )
        db_session.add(history)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/shows/{show.guid}/resume", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "resume"
        assert data["progress_seconds"] == 300

    async def test_completed_episode_goes_next(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.viewing_history import ViewingHistory

        show, episodes = await self._create_show_hierarchy(db_session)
        # Mark first episode as completed
        history = ViewingHistory(
            guid=uuid.uuid4(),
            user_guid=test_user.guid,
            media_item_guid=episodes[0].guid,
            progress_seconds=2400,
            duration_seconds=2400,
            progress_percentage=100.0,
            is_completed=True,
        )
        db_session.add(history)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/shows/{show.guid}/resume", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "next"

    async def test_fully_watched_replays(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.viewing_history import ViewingHistory

        show, episodes = await self._create_show_hierarchy(db_session, eps_per_season=1)
        # Mark only episode as completed
        history = ViewingHistory(
            guid=uuid.uuid4(),
            user_guid=test_user.guid,
            media_item_guid=episodes[0].guid,
            progress_seconds=2400,
            duration_seconds=2400,
            progress_percentage=100.0,
            is_completed=True,
        )
        db_session.add(history)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/shows/{show.guid}/resume", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "replay"


# ============================================================================
# EPISODE NAVIGATION
# ============================================================================


class TestNextEpisode:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/next-episode")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/next-episode", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_not_an_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        # A show without parent_guid is not an episode
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        resp = await client.get(
            f"/api/media/{show.guid}/next-episode", headers=user_headers
        )
        assert resp.status_code == 400

    async def test_next_in_same_season(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        season = await _create_media_item(
            db_session,
            title="Season 1",
            media_type=MediaType.SHOWS,
            parent_guid=show.guid,
            sequence_number=1,
        )
        ep1 = await _create_media_item(
            db_session,
            title="Episode 1",
            media_type=MediaType.SHOWS,
            parent_guid=season.guid,
            sequence_number=1,
        )
        ep2 = await _create_media_item(
            db_session,
            title="Episode 2",
            media_type=MediaType.SHOWS,
            parent_guid=season.guid,
            sequence_number=2,
        )

        resp = await client.get(
            f"/api/media/{ep1.guid}/next-episode", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["next_episode"]["guid"] == str(ep2.guid)

    async def test_next_season_first_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        s1 = await _create_media_item(
            db_session, title="S1", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=1,
        )
        s2 = await _create_media_item(
            db_session, title="S2", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=2,
        )
        ep_last = await _create_media_item(
            db_session, title="S1E3", media_type=MediaType.SHOWS,
            parent_guid=s1.guid, sequence_number=3,
        )
        ep_next = await _create_media_item(
            db_session, title="S2E1", media_type=MediaType.SHOWS,
            parent_guid=s2.guid, sequence_number=1,
        )

        resp = await client.get(
            f"/api/media/{ep_last.guid}/next-episode", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["next_episode"]["guid"] == str(ep_next.guid)

    async def test_no_next_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        season = await _create_media_item(
            db_session, title="S1", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=1,
        )
        last_ep = await _create_media_item(
            db_session, title="S1E1", media_type=MediaType.SHOWS,
            parent_guid=season.guid, sequence_number=1,
        )

        resp = await client.get(
            f"/api/media/{last_ep.guid}/next-episode", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["next_episode"] is None


class TestPreviousEpisode:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/previous-episode")
        assert resp.status_code == 401

    async def test_not_found(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/previous-episode", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_not_an_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        resp = await client.get(
            f"/api/media/{show.guid}/previous-episode", headers=user_headers
        )
        assert resp.status_code == 400

    async def test_previous_in_same_season(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        season = await _create_media_item(
            db_session, title="S1", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=1,
        )
        ep1 = await _create_media_item(
            db_session, title="E1", media_type=MediaType.SHOWS,
            parent_guid=season.guid, sequence_number=1,
        )
        ep2 = await _create_media_item(
            db_session, title="E2", media_type=MediaType.SHOWS,
            parent_guid=season.guid, sequence_number=2,
        )

        resp = await client.get(
            f"/api/media/{ep2.guid}/previous-episode", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_episode"]["guid"] == str(ep1.guid)

    async def test_previous_season_last_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        s1 = await _create_media_item(
            db_session, title="S1", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=1,
        )
        s2 = await _create_media_item(
            db_session, title="S2", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=2,
        )
        ep_last_s1 = await _create_media_item(
            db_session, title="S1E3", media_type=MediaType.SHOWS,
            parent_guid=s1.guid, sequence_number=3,
        )
        ep_first_s2 = await _create_media_item(
            db_session, title="S2E1", media_type=MediaType.SHOWS,
            parent_guid=s2.guid, sequence_number=1,
        )

        resp = await client.get(
            f"/api/media/{ep_first_s2.guid}/previous-episode", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["previous_episode"]["guid"] == str(ep_last_s1.guid)

    async def test_no_previous_episode(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        show = await _create_media_item(
            db_session, title="Show", media_type=MediaType.SHOWS
        )
        season = await _create_media_item(
            db_session, title="S1", media_type=MediaType.SHOWS,
            parent_guid=show.guid, sequence_number=1,
        )
        first_ep = await _create_media_item(
            db_session, title="S1E1", media_type=MediaType.SHOWS,
            parent_guid=season.guid, sequence_number=1,
        )

        resp = await client.get(
            f"/api/media/{first_ep.guid}/previous-episode", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json()["previous_episode"] is None


# ============================================================================
# FILE OPERATIONS
# ============================================================================


class TestMediaImages:
    async def test_get_images_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/images")
        assert resp.status_code == 401

    async def test_get_images_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/images", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_images_success(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            poster_path="/images/poster.jpg",
            backdrop_path="/images/backdrop.jpg",
        )

        resp = await client.get(f"/api/media/{item.guid}/images", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "poster_path": "/images/poster.jpg",
            "backdrop_path": "/images/backdrop.jpg",
        }

    async def test_set_image_forbidden_for_regular_user(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/images/poster",
            headers=user_headers,
            json={"path": "/images/poster.jpg"},
        )

        assert resp.status_code == 403

    async def test_set_image_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/images/poster",
            headers=admin_headers,
            json={"path": "/images/poster.jpg"},
        )

        assert resp.status_code == 200
        assert resp.json()["poster_path"] == "/images/poster.jpg"
        await db_session.refresh(item)
        assert item.poster_path == "/images/poster.jpg"

    async def test_upload_image_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv("STREAMARR_ARTWORK_DIR", str(tmp_path / "artwork"))
        item = await _create_media_item(db_session)
        image_bytes = b"\x89PNG\r\n\x1a\nuploaded-poster"

        resp = await client.post(
            f"/api/media/{item.guid}/images/poster/upload",
            headers=admin_headers,
            json={
                "file_name": "poster.png",
                "content_type": "image/png",
                "content_base64": base64.b64encode(image_bytes).decode("ascii"),
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["poster_path"] == data["stored_path"]
        assert data["content_type"] == "image/png"
        assert data["size_bytes"] == len(image_bytes)
        await db_session.refresh(item)
        assert item.poster_path == data["stored_path"]

        image_resp = await client.get(data["stored_path"], headers=admin_headers)
        assert image_resp.status_code == 200
        assert image_resp.content == image_bytes
        assert image_resp.headers["content-type"].startswith("image/png")

        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "metadata.image_upload"
            )
        )
        assert "poster.png" in log_result.scalar_one().extra_data

    async def test_upload_image_rejects_mismatched_content(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        monkeypatch,
        tmp_path,
    ):
        monkeypatch.setenv("STREAMARR_ARTWORK_DIR", str(tmp_path / "artwork"))
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/images/poster/upload",
            headers=admin_headers,
            json={
                "file_name": "poster.png",
                "content_type": "image/png",
                "content_base64": base64.b64encode(b"not-a-png").decode("ascii"),
            },
        )

        assert resp.status_code == 400

    async def test_upload_image_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/images/poster/upload",
            headers=user_headers,
            json={
                "file_name": "poster.png",
                "content_type": "image/png",
                "content_base64": base64.b64encode(b"\x89PNG\r\n\x1a\nx").decode("ascii"),
            },
        )

        assert resp.status_code == 403

    async def test_transform_uploaded_image_content(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        monkeypatch,
        tmp_path,
    ):
        pytest.importorskip("PIL")
        from PIL import Image

        monkeypatch.setenv("STREAMARR_ARTWORK_DIR", str(tmp_path / "artwork"))
        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), (255, 0, 0)).save(image_buffer, format="PNG")
        image_bytes = image_buffer.getvalue()
        item = await _create_media_item(db_session)

        upload = await client.post(
            f"/api/media/{item.guid}/images/poster/upload",
            headers=admin_headers,
            json={
                "file_name": "poster.png",
                "content_type": "image/png",
                "content_base64": base64.b64encode(image_bytes).decode("ascii"),
            },
        )

        assert upload.status_code == 200
        transformed = await client.get(
            f"{upload.json()['stored_path']}/transform",
            headers=admin_headers,
            params={"width": 2, "height": 2, "format": "webp", "quality": 80},
        )

        assert transformed.status_code == 200
        assert transformed.headers["content-type"].startswith("image/webp")
        result = Image.open(BytesIO(transformed.content))
        assert result.size == (2, 2)

    async def test_delete_image_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(
            db_session,
            poster_path="/images/poster.jpg",
            backdrop_path="/images/backdrop.jpg",
        )

        resp = await client.delete(
            f"/api/media/{item.guid}/images/backdrop",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "poster_path": "/images/poster.jpg",
            "backdrop_path": None,
        }
        await db_session.refresh(item)
        assert item.backdrop_path is None

    async def test_bulk_set_images_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/images",
            headers=admin_headers,
            json={
                "poster_path": "/images/poster.jpg",
                "backdrop_path": "/images/backdrop.jpg",
            },
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "poster_path": "/images/poster.jpg",
            "backdrop_path": "/images/backdrop.jpg",
        }
        await db_session.refresh(item)
        assert item.poster_path == "/images/poster.jpg"
        assert item.backdrop_path == "/images/backdrop.jpg"

        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "metadata.images_update"
            )
        )
        assert "poster_path" in log_result.scalar_one().extra_data

    async def test_bulk_delete_images_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(
            db_session,
            poster_path="/images/poster.jpg",
            backdrop_path="/images/backdrop.jpg",
        )

        resp = await client.delete(
            f"/api/media/{item.guid}/images",
            headers=admin_headers,
        )

        assert resp.status_code == 200
        assert resp.json() == {"poster_path": None, "backdrop_path": None}
        await db_session.refresh(item)
        assert item.poster_path is None
        assert item.backdrop_path is None

        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "metadata.images_delete"
            )
        )
        assert "backdrop_path" in log_result.scalar_one().extra_data

    async def test_bulk_set_images_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/images",
            headers=user_headers,
            json={"poster_path": "/images/poster.jpg"},
        )

        assert resp.status_code == 403

    async def test_search_remote_images(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_images": [
                        {
                            "provider": "tmdb",
                            "id": "poster-1",
                            "type": "poster",
                            "url": "https://image.test/poster.jpg",
                            "thumbnail_url": "https://image.test/poster-small.jpg",
                            "width": 500,
                            "height": 750,
                            "language": "en",
                            "score": 90,
                        },
                        {
                            "provider": "tmdb",
                            "id": "poster-2",
                            "type": "poster",
                            "url": "https://image.test/poster-de.jpg",
                            "language": "de",
                            "score": 95,
                        },
                        {
                            "provider": "tmdb",
                            "id": "backdrop-1",
                            "type": "backdrop",
                            "url": "https://image.test/backdrop.jpg",
                            "score": 80,
                        },
                    ]
                }
            ),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/images/remote",
            headers=user_headers,
            params={
                "image_type": "poster",
                "language": "en",
                "include_language_neutral": False,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "tmdb"
        assert data["items"][0]["provider_id"] == "poster-1"
        assert data["items"][0]["image_type"] == "poster"
        assert data["items"][0]["language"] == "en"

    async def test_search_live_remote_images(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
        monkeypatch,
    ):
        from streamarr.api.v1 import media as media_api

        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"external_ids": {"tmdb": "603"}}),
        )
        search_remote_images = AsyncMock(
            return_value=[
                {
                    "provider": "tmdb",
                    "provider_id": "603:poster",
                    "image_type": "poster",
                    "url": "https://image.test/matrix.jpg",
                    "language": "de",
                    "score": 100,
                },
                {
                    "provider": "tmdb",
                    "provider_id": "603:poster:neutral",
                    "image_type": "poster",
                    "url": "https://image.test/matrix-neutral.jpg",
                    "score": 90,
                },
            ]
        )
        metadata_service = MagicMock()
        metadata_service.search_remote_images = search_remote_images
        monkeypatch.setattr(
            media_api,
            "MetadataService",
            lambda db: metadata_service,
        )

        resp = await client.get(
            f"/api/media/{item.guid}/images/remote/live",
            headers=admin_headers,
            params={
                "provider": "tmdb",
                "image_type": "poster",
                "language": "de",
                "include_language_neutral": False,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider_id"] == "603:poster"
        assert data["items"][0]["url"] == "https://image.test/matrix.jpg"
        assert data["items"][0]["language"] == "de"
        search_remote_images.assert_awaited_once()
        assert search_remote_images.await_args.kwargs["provider_id"] == "603"

    async def test_get_image_transform_descriptor(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            poster_path="https://image.test/poster.jpg?token=abc",
        )

        resp = await client.get(
            f"/api/media/{item.guid}/images/poster/transform",
            headers=user_headers,
            params={"width": 300, "quality": 85, "format": "webp"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["image_type"] == "poster"
        assert data["source_url"] == "https://image.test/poster.jpg?token=abc"
        assert data["width"] == 300
        assert data["quality"] == 85
        assert data["format"] == "webp"
        assert data["transformed_url"].startswith(
            "https://image.test/poster.jpg?"
        )
        assert "token=abc" in data["transformed_url"]
        assert "width=300" in data["transformed_url"]
        assert "quality=85" in data["transformed_url"]
        assert "format=webp" in data["transformed_url"]

    async def test_get_image_transform_missing_image(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.get(
            f"/api/media/{item.guid}/images/poster/transform",
            headers=user_headers,
        )

        assert resp.status_code == 404

    async def test_proxy_remote_image(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers, monkeypatch
    ):
        from streamarr.api.v1 import media as media_api

        item = await _create_media_item(
            db_session,
            poster_path="https://image.test/poster.jpg",
        )
        fetch_remote_image = AsyncMock(return_value=(b"remote-image", "image/jpeg"))
        monkeypatch.setattr(media_api, "_fetch_remote_image", fetch_remote_image)

        resp = await client.get(
            f"/api/media/{item.guid}/images/poster/proxy",
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.content == b"remote-image"
        assert resp.headers["content-type"].startswith("image/jpeg")
        fetch_remote_image.assert_awaited_once_with("https://image.test/poster.jpg")

    async def test_proxy_remote_image_with_transform(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers, monkeypatch
    ):
        pytest.importorskip("PIL")
        from PIL import Image
        from streamarr.api.v1 import media as media_api

        image_buffer = BytesIO()
        Image.new("RGB", (4, 4), (0, 0, 255)).save(image_buffer, format="PNG")
        item = await _create_media_item(
            db_session,
            poster_path="https://image.test/poster.png",
        )
        monkeypatch.setattr(
            media_api,
            "_fetch_remote_image",
            AsyncMock(return_value=(image_buffer.getvalue(), "image/png")),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/images/poster/proxy",
            headers=user_headers,
            params={"width": 2, "height": 2, "format": "webp"},
        )

        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("image/webp")
        result = Image.open(BytesIO(resp.content))
        assert result.size == (2, 2)

    async def test_select_remote_image_requires_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_images": [
                        {
                            "provider": "tmdb",
                            "id": "poster-1",
                            "type": "poster",
                            "url": "https://image.test/poster.jpg",
                        }
                    ]
                }
            ),
        )

        resp = await client.put(
            f"/api/media/{item.guid}/images/poster/remote",
            headers=user_headers,
            json={"provider": "tmdb", "provider_id": "poster-1"},
        )

        assert resp.status_code == 403

    async def test_select_remote_image_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_images": [
                        {
                            "provider": "tmdb",
                            "id": "poster-1",
                            "type": "poster",
                            "url": "https://image.test/poster.jpg",
                        }
                    ]
                }
            ),
        )

        resp = await client.put(
            f"/api/media/{item.guid}/images/poster/remote",
            headers=admin_headers,
            json={"provider": "tmdb", "provider_id": "poster-1"},
        )

        assert resp.status_code == 200
        assert resp.json()["poster_path"] == "https://image.test/poster.jpg"
        await db_session.refresh(item)
        assert item.poster_path == "https://image.test/poster.jpg"

        log_result = await db_session.execute(
            select(ActivityLog).where(
                ActivityLog.event_type == "metadata.remote_image_select"
            )
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "poster-1" in log_entry.extra_data

    async def test_select_remote_image_not_found(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/images/poster/remote",
            headers=admin_headers,
            json={"provider": "tmdb", "provider_id": "missing"},
        )

        assert resp.status_code == 404


class TestMediaTrailers:
    async def test_get_trailers_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/trailers")
        assert resp.status_code == 401

    async def test_get_trailers_from_extra_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_trailers": [
                        {
                            "provider": "tmdb",
                            "id": "abc",
                            "name": "Official Trailer",
                            "site": "YouTube",
                            "key": "yt-key",
                            "type": "Trailer",
                            "official": True,
                            "published_at": "2026-01-02T00:00:00Z",
                        },
                        {
                            "name": "Featurette",
                            "url": "https://example.test/featurette",
                            "type": "Featurette",
                        },
                    ]
                }
            ),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/trailers", headers=user_headers
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["name"] == "Official Trailer"
        assert data["items"][0]["url"] == "https://www.youtube.com/watch?v=yt-key"
        assert data["items"][0]["official"] is True

    async def test_update_trailers_admin_only(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/trailers",
            headers=user_headers,
            json={"items": []},
        )

        assert resp.status_code == 403

    async def test_update_trailers_success(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/trailers",
            headers=admin_headers,
            json={
                "items": [
                    {
                        "id": "local-1",
                        "name": "Trailer",
                        "url": "https://example.test/trailer.mp4",
                        "provider": "manual",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "manual"

        await db_session.refresh(item)
        extra_data = item.extra_data
        assert extra_data["trailers"][0]["url"] == "https://example.test/trailer.mp4"


class TestDownloadMediaFile:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}/download"
        )
        assert resp.status_code == 401

    async def test_item_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}/download",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_forbidden_without_library_permission(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        from streamarr.models.media import MediaFile

        test_user.allowed_libraries = []
        await db_session.commit()

        item = await _create_media_item(db_session, media_type=MediaType.MOVIES)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/library/movies/test.mkv",
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/files/{f.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 403

    async def test_file_not_found(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_media_item(db_session)
        resp = await client.get(
            f"/api/media/{item.guid}/files/{uuid.uuid4()}/download",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_rejects_file_outside_allowed_roots(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        tmp_path,
    ):
        from streamarr.models.media import MediaFile

        outside_path = tmp_path / "outside.mkv"
        outside_path.write_bytes(b"outside")
        item = await _create_media_item(db_session)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(outside_path),
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/files/{f.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_download_success_with_library_root(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        tmp_path,
    ):
        from streamarr.models.media import MediaFile

        media_path = tmp_path / "movies" / "Feature.mkv"
        media_path.parent.mkdir()
        media_path.write_bytes(b"movie-bytes")

        lib = await _create_library(db_session, path=str(tmp_path))
        item = await _create_media_item(
            db_session, library_guid=lib.guid, media_type=MediaType.MOVIES
        )
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=str(media_path),
            file_name="Feature.mkv",
            file_size=11,
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/files/{f.guid}/download",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.content == b"movie-bytes"
        assert "Feature.mkv" in resp.headers["content-disposition"]


class TestDeleteMediaFile:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.delete(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}"
        )
        assert resp.status_code == 401

    async def test_forbidden_for_regular_user(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/test.mkv",
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.delete(
            f"/api/media/{item.guid}/files/{f.guid}", headers=user_headers
        )
        assert resp.status_code == 403

    async def test_item_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.delete(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_file_not_found(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.delete(
            f"/api/media/{item.guid}/files/{uuid.uuid4()}",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_delete_success(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/nonexistent.mkv",
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.delete(
            f"/api/media/{item.guid}/files/{f.guid}",
            headers=admin_headers,
        )
        assert resp.status_code == 204

    @patch("os.path.exists", return_value=True)
    @patch("os.remove")
    async def test_delete_with_disk_delete(
        self,
        mock_remove,
        mock_exists,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        from streamarr.models.media import MediaFile

        item = await _create_media_item(db_session)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/disk_delete.mkv",
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.delete(
            f"/api/media/{item.guid}/files/{f.guid}",
            headers=admin_headers,
            params={"delete_from_disk": True},
        )
        assert resp.status_code == 204
        mock_remove.assert_called_once_with("/data/movies/disk_delete.mkv")


# ============================================================================
# REPROBE
# ============================================================================


class TestReprobeMediaFile:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}/reprobe"
        )
        assert resp.status_code == 401

    async def test_item_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/media/{uuid.uuid4()}/files/{uuid.uuid4()}/reprobe",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_file_not_found(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/files/{uuid.uuid4()}/reprobe",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/files/{uuid.uuid4()}/reprobe",
            headers=user_headers,
        )
        assert resp.status_code == 403

    @patch("streamarr.worker.probe_media_file")
    async def test_reprobe_success(
        self,
        mock_probe,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        from streamarr.models.media import MediaFile

        mock_probe.kiq = AsyncMock()

        item = await _create_media_item(db_session)
        f = MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path="/data/movies/test.mkv",
        )
        db_session.add(f)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/files/{f.guid}/reprobe",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "queued" in data["message"].lower()
        mock_probe.kiq.assert_called_once_with(str(f.guid))


class TestReprobeAllMediaFiles:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post(f"/api/media/{uuid.uuid4()}/files/reprobe-all")
        assert resp.status_code == 401

    async def test_item_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/media/{uuid.uuid4()}/files/reprobe-all",
            headers=user_headers,
        )
        assert resp.status_code == 404

    async def test_no_files(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/files/reprobe-all",
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_regular_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        resp = await client.post(
            f"/api/media/{item.guid}/files/reprobe-all",
            headers=user_headers,
        )
        assert resp.status_code == 403

    @patch("streamarr.worker.probe_media_file")
    async def test_reprobe_all_success(
        self,
        mock_probe,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        admin_headers,
    ):
        from streamarr.models.media import MediaFile

        mock_probe.kiq = AsyncMock()

        item = await _create_media_item(db_session)
        for i in range(3):
            f = MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                file_path=f"/data/movies/test_{i}.mkv",
            )
            db_session.add(f)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/files/reprobe-all",
            headers=admin_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "3" in data["message"]
        assert len(data["file_guids"]) == 3
        assert mock_probe.kiq.call_count == 3
