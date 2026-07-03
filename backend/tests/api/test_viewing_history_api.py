"""Tests for the Viewing History API endpoints (/api/viewing-history/*)."""

import json
import uuid

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.device import Device
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.user import User
from pyrate.models.viewing_history import ViewingHistory


@pytest.fixture
async def movie(db_session: AsyncSession) -> MediaItem:
    item = MediaItem(title="History Movie", media_type=MediaType.MOVIES)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest.fixture
async def movie2(db_session: AsyncSession) -> MediaItem:
    item = MediaItem(title="History Movie 2", media_type=MediaType.MOVIES)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


@pytest_asyncio.fixture
async def show_hierarchy(db_session: AsyncSession):
    """Create show -> season -> episode hierarchy."""
    show = MediaItem(title="Test Show", media_type=MediaType.SHOWS)
    db_session.add(show)
    await db_session.flush()

    season = MediaItem(
        title="Season 1", media_type=MediaType.SHOWS,
        parent_guid=show.guid, sequence_number=1,
    )
    db_session.add(season)
    await db_session.flush()

    ep1 = MediaItem(
        title="Episode 1", media_type=MediaType.SHOWS,
        parent_guid=season.guid, sequence_number=1,
    )
    ep2 = MediaItem(
        title="Episode 2", media_type=MediaType.SHOWS,
        parent_guid=season.guid, sequence_number=2,
    )
    db_session.add_all([ep1, ep2])
    await db_session.commit()
    for obj in (show, season, ep1, ep2):
        await db_session.refresh(obj)
    return {"show": show, "season": season, "ep1": ep1, "ep2": ep2}


class TestListViewingHistory:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/viewing-history")
        assert resp.status_code == 401

    async def test_empty(self, client: AsyncClient, test_user: User, user_headers):
        resp = await client.get("/api/viewing-history", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


class TestCreateViewingHistory:
    async def test_create_new(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 300,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["progress_seconds"] == 300
        assert data["duration_seconds"] == 7200

    async def test_update_existing(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Create
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )

        # Update
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 500,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["progress_seconds"] == 500

    async def test_create_without_guid(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "progress_seconds": 100,
            },
        )
        assert resp.status_code == 400

    async def test_create_nonexistent_media(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(uuid.uuid4()),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 404

    async def test_create_with_playlist_context(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        playlist_id = uuid.uuid4()

        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 300,
                "duration_seconds": 7200,
                "extra_data": json.dumps(
                    {"playlist_guid": str(playlist_id), "playlist_index": 2}
                ),
            },
        )

        assert resp.status_code == 200
        assert resp.json()["playlist_guid"] == str(playlist_id)
        assert resp.json()["playlist_index"] == 2

        list_resp = await client.get(
            "/api/viewing-history",
            headers=user_headers,
            params={"content_guid": str(movie.guid)},
        )
        assert list_resp.status_code == 200
        history = list_resp.json()["items"][0]
        assert history["playlist_guid"] == str(playlist_id)
        assert history["playlist_index"] == 2


class TestReportPlaystate:
    async def test_reports_history_and_device_status(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        movie,
    ):
        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="browser-1",
            name="Browser",
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()

        resp = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 120,
                "duration_seconds": 3600,
                "is_playing": True,
                "device_guid": str(device.guid),
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["history"]["progress_seconds"] == 120
        assert data["device_guid"] == str(device.guid)
        assert data["is_playing"] is True

        await db_session.refresh(device)
        assert device.is_playing is True
        assert device.current_media_guid == movie.guid
        assert device.current_playback_position == 120
        assert device.current_playback_duration == 3600

    async def test_playstate_event_semantics_are_persisted(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        movie,
    ):
        start = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 10,
                "duration_seconds": 3600,
                "event_name": "start",
                "is_playing": True,
                "extra_data": json.dumps({"client_session_id": "session-1"}),
            },
        )
        assert start.status_code == 200
        assert start.json()["event_name"] == "start"
        assert start.json()["is_playing"] is True

        pause = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 120,
                "duration_seconds": 3600,
                "event_name": "pause",
                "is_playing": True,
            },
        )
        assert pause.status_code == 200
        assert pause.json()["event_name"] == "pause"
        assert pause.json()["is_playing"] is False
        assert pause.json()["is_paused"] is True

        history = await db_session.get(
            ViewingHistory,
            uuid.UUID(pause.json()["history"]["guid"]),
        )
        extra_data = json.loads(history.extra_data)
        assert extra_data["client_session_id"] == "session-1"
        assert extra_data["playstate"]["last_event"]["event_name"] == "pause"
        assert len(extra_data["playstate"]["events"]) == 2

    async def test_item_playstate_routes_record_payloads(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        movie,
    ):
        device = Device(
            guid=uuid.uuid4(),
            user_id=test_user.guid,
            device_id="external-client",
            name="Living Room",
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()

        playing = await client.post(
            f"/api/viewing-history/{movie.guid}/playing",
            headers=user_headers,
            json={
                "position_ticks": 90 * 10_000_000,
                "duration_ticks": 3600 * 10_000_000,
                "play_session_id": "session-1",
                "device_id": "external-client",
                "media_type": "movie",
                "media_title": movie.title,
                "media_source_id": "source-1",
                "audio_stream_index": 1,
                "subtitle_stream_index": 2,
            },
        )

        assert playing.status_code == 200
        data = playing.json()
        assert data["event_name"] == "start"
        assert data["client_session_id"] == "session-1"
        assert data["history"]["progress_seconds"] == 90
        assert data["history"]["duration_seconds"] == 3600
        assert data["history"]["progress_percentage"] == 2.5

        paused = await client.post(
            f"/api/viewing-history/{movie.guid}/progress",
            headers=user_headers,
            json={
                "position_seconds": 120,
                "duration_seconds": 3600,
                "play_session_id": "session-1",
                "device_id": "external-client",
                "is_paused": True,
            },
        )

        assert paused.status_code == 200
        assert paused.json()["event_name"] == "pause"
        assert paused.json()["is_playing"] is False
        assert paused.json()["is_paused"] is True

        await db_session.refresh(device)
        assert device.is_playing is False
        assert device.current_media_guid == movie.guid
        assert device.current_playback_position == 120

        history = await db_session.get(
            ViewingHistory,
            uuid.UUID(paused.json()["history"]["guid"]),
        )
        extra_data = json.loads(history.extra_data)
        assert extra_data["route_source"] == "item_playstate_route"
        assert extra_data["play_session_id"] == "session-1"
        assert extra_data["media_source_id"] == "source-1"
        assert extra_data["audio_stream_index"] == 1
        assert extra_data["subtitle_stream_index"] == 2
        assert extra_data["playstate"]["last_event"]["event_name"] == "pause"

    async def test_playstate_sessions_surface_latest_client_session(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        movie,
    ):
        start = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 10,
                "duration_seconds": 3600,
                "event_name": "start",
                "is_playing": True,
                "client_session_id": "session-1",
            },
        )
        assert start.status_code == 200
        assert start.json()["client_session_id"] == "session-1"

        pause = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 125,
                "duration_seconds": 3600,
                "event_name": "pause",
                "is_playing": True,
                "client_session_id": "session-1",
            },
        )
        assert pause.status_code == 200

        resp = await client.get(
            "/api/viewing-history/playstate/sessions",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        session = data["items"][0]
        assert session["session_id"] == "session-1"
        assert session["content_guid"] == str(movie.guid)
        assert session["media_title"] == movie.title
        assert session["event_name"] == "pause"
        assert session["is_playing"] is False
        assert session["is_paused"] is True
        assert session["progress_seconds"] == 125

    async def test_playstate_sessions_surface_playlist_context(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        movie,
    ):
        playlist_id = uuid.uuid4()

        resp = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 45,
                "duration_seconds": 3600,
                "event_name": "progress",
                "is_playing": True,
                "client_session_id": "playlist-session",
                "playlist_guid": str(playlist_id),
                "playlist_index": 3,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["history"]["playlist_guid"] == str(playlist_id)
        assert resp.json()["history"]["playlist_index"] == 3

        sessions = await client.get(
            "/api/viewing-history/playstate/sessions",
            headers=user_headers,
        )
        assert sessions.status_code == 200
        session = sessions.json()["items"][0]
        assert session["playlist_guid"] == str(playlist_id)
        assert session["playlist_index"] == 3

    async def test_finish_playstate_marks_history_completed(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        movie,
    ):
        resp = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 3600,
                "duration_seconds": 3600,
                "event_name": "finish",
                "is_playing": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_playing"] is False
        assert data["history"]["progress_percentage"] == 100.0
        assert data["history"]["is_completed"] is True

    async def test_rejects_other_users_device(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_superuser: User,
        user_headers,
        movie,
    ):
        device = Device(
            guid=uuid.uuid4(),
            user_id=test_superuser.guid,
            device_id="other-device",
            is_active=True,
            is_trusted=False,
        )
        db_session.add(device)
        await db_session.commit()

        resp = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={
                "content_guid": str(movie.guid),
                "progress_seconds": 120,
                "device_guid": str(device.guid),
            },
        )

        assert resp.status_code == 404


class TestDeleteViewingHistory:
    async def test_delete(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        guid = create_resp.json()["guid"]

        resp = await client.delete(
            f"/api/viewing-history/{guid}", headers=user_headers
        )
        assert resp.status_code == 204

    async def test_delete_nonexistent(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.delete(
            f"/api/viewing-history/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404


class TestContinueWatching:
    async def test_continue_watching_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/viewing-history/continue-watching", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestRecentlyWatched:
    async def test_recently_watched_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestViewingStats:
    async def test_stats_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/viewing-history/stats", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_watched"] == 0
        assert data["total_watch_time_seconds"] == 0


# ===========================================================================
# Extended tests
# ===========================================================================


class TestListViewingHistoryPagination:
    async def test_pagination(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        # Create two entries
        for m in (movie, movie2):
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "movie",
                    "movie_guid": str(m.guid),
                    "progress_seconds": 100,
                    "duration_seconds": 7200,
                },
            )

        resp = await client.get(
            "/api/viewing-history?per_page=1&page=1", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 1
        assert data["total"] == 2
        assert data["total_pages"] == 2

    async def test_filter_by_content_guid(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        for m in (movie, movie2):
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "movie",
                    "movie_guid": str(m.guid),
                    "progress_seconds": 100,
                    "duration_seconds": 7200,
                },
            )

        resp = await client.get(
            f"/api/viewing-history?content_guid={movie.guid}",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1


class TestCreateViewingHistoryExtended:
    async def test_auto_complete_at_90_percent(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 6600,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_completed"] is True
        assert data["progress_percentage"] > 90.0

    async def test_not_completed_below_90(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 3600,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["is_completed"] is False

    async def test_update_resets_completed(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Create at 95%
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 6840,
                "duration_seconds": 7200,
            },
        )
        # Update back to 50%
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 3600,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 200
        assert resp.json()["is_completed"] is False

    async def test_episode_guid(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        ep = show_hierarchy["ep1"]
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(ep.guid),
                "progress_seconds": 600,
                "duration_seconds": 2400,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["episode_guid"] == str(ep.guid)


class TestContinueWatchingExtended:
    async def test_continue_watching_with_items(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Create an in-progress entry
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 1800,
                "duration_seconds": 7200,
            },
        )
        resp = await client.get(
            "/api/viewing-history/continue-watching", headers=user_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["movie_guid"] == str(movie.guid)

    async def test_continue_watching_excludes_completed(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Create fully watched entry (>90%)
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 7000,
                "duration_seconds": 7200,
            },
        )
        resp = await client.get(
            "/api/viewing-history/continue-watching", headers=user_headers
        )
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_continue_watching_with_limit(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        for m in (movie, movie2):
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "movie",
                    "movie_guid": str(m.guid),
                    "progress_seconds": 1800,
                    "duration_seconds": 7200,
                },
            )
        resp = await client.get(
            "/api/viewing-history/continue-watching?limit=1", headers=user_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_continue_watching_content_type_filter(
        self, client: AsyncClient, test_user: User, user_headers, movie, show_hierarchy
    ):
        # Movie progress
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 1800,
                "duration_seconds": 7200,
            },
        )
        # Episode progress
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(show_hierarchy["ep1"].guid),
                "progress_seconds": 600,
                "duration_seconds": 2400,
            },
        )

        resp = await client.get(
            "/api/viewing-history/continue-watching?content_type=movie",
            headers=user_headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content_type"] == "movie"


class TestNextUp:
    async def test_next_up_starts_unwatched_show(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        resp = await client.get("/api/viewing-history/next-up", headers=user_headers)

        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["show_guid"] == str(show_hierarchy["show"].guid)
        assert items[0]["action"] == "start"
        assert items[0]["episode"]["guid"] == str(show_hierarchy["ep1"].guid)

    async def test_next_up_resumes_in_progress_episode(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        ep = show_hierarchy["ep1"]
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(ep.guid),
                "progress_seconds": 600,
                "duration_seconds": 2400,
            },
        )

        resp = await client.get("/api/viewing-history/next-up", headers=user_headers)

        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["action"] == "resume"
        assert item["progress_seconds"] == 600
        assert item["episode"]["guid"] == str(ep.guid)

    async def test_next_up_returns_next_after_completed_episode(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(show_hierarchy["ep1"].guid),
                "progress_seconds": 2300,
                "duration_seconds": 2400,
            },
        )

        resp = await client.get("/api/viewing-history/next-up", headers=user_headers)

        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["action"] == "next"
        assert item["episode"]["guid"] == str(show_hierarchy["ep2"].guid)

    async def test_next_up_replays_finished_show(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        for ep_key in ("ep1", "ep2"):
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "episode",
                    "episode_guid": str(show_hierarchy[ep_key].guid),
                    "progress_seconds": 2300,
                    "duration_seconds": 2400,
                },
            )

        resp = await client.get("/api/viewing-history/next-up", headers=user_headers)

        assert resp.status_code == 200
        item = resp.json()[0]
        assert item["action"] == "replay"
        assert item["episode"]["guid"] == str(show_hierarchy["ep1"].guid)

    async def test_next_up_show_filter_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/viewing-history/next-up?show_guid={uuid.uuid4()}",
            headers=user_headers,
        )

        assert resp.status_code == 404

    async def test_next_up_can_exclude_unwatched(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        resp = await client.get(
            "/api/viewing-history/next-up?include_unwatched=false",
            headers=user_headers,
        )

        assert resp.status_code == 200
        assert resp.json() == []


class TestRecentlyWatchedExtended:
    async def test_recently_watched_with_items(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 7000,
                "duration_seconds": 7200,
            },
        )
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["is_completed"] is True

    async def test_recently_watched_includes_completed(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        # One completed, one in-progress
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 7000,
                "duration_seconds": 7200,
            },
        )
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie2.guid),
                "progress_seconds": 1000,
                "duration_seconds": 7200,
            },
        )
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_recently_watched_with_limit(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        for m in (movie, movie2):
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "movie",
                    "movie_guid": str(m.guid),
                    "progress_seconds": 1000,
                    "duration_seconds": 7200,
                },
            )
        resp = await client.get(
            "/api/viewing-history/recently-watched?limit=1", headers=user_headers
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_recently_watched_episode_hierarchy(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        ep = show_hierarchy["ep1"]
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(ep.guid),
                "progress_seconds": 600,
                "duration_seconds": 2400,
            },
        )
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content_type"] == "episode"
        assert items[0]["episode_guid"] == str(ep.guid)


class TestViewingStatsExtended:
    async def test_stats_with_movies(
        self, client: AsyncClient, test_user: User, user_headers, movie, movie2
    ):
        # One completed movie, one in-progress
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 7000,
                "duration_seconds": 7200,
            },
        )
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie2.guid),
                "progress_seconds": 1800,
                "duration_seconds": 7200,
            },
        )

        resp = await client.get("/api/viewing-history/stats", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_watched"] == 2
        assert data["total_movies_watched"] == 1  # Only completed
        assert data["completed_content"] == 1
        assert data["in_progress_content"] == 1
        assert data["total_watch_time_seconds"] == 8800

    async def test_stats_with_episodes(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        for ep_key in ("ep1", "ep2"):
            ep = show_hierarchy[ep_key]
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "episode",
                    "episode_guid": str(ep.guid),
                    "progress_seconds": 2300,
                    "duration_seconds": 2400,
                },
            )
        resp = await client.get("/api/viewing-history/stats", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_episodes_watched"] == 2
        assert data["total_watch_time_hours"] > 0


class TestDeleteViewingHistoryExtended:
    async def test_delete_other_users_history(
        self, client: AsyncClient, test_user: User, test_superuser: User,
        user_headers, admin_headers, movie
    ):
        """Regular user cannot delete another user's history (filtered by user_guid)."""
        # Create history as admin
        create_resp = await client.post(
            "/api/viewing-history",
            headers=admin_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        guid = create_resp.json()["guid"]

        # Try to delete as regular user -> should be 404 (not found for this user)
        resp = await client.delete(
            f"/api/viewing-history/{guid}", headers=user_headers
        )
        assert resp.status_code == 404


# ===========================================================================
# Additional coverage tests - content_type filter, continue watching, etc.
# ===========================================================================


class TestListViewingHistoryContentTypeFilter:
    async def test_filter_by_content_type_param(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """GET /viewing-history with content_type filter param."""
        # Create a history entry
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )

        # The endpoint accepts content_type as a query param but it's not used
        # for filtering in the query (only content_guid is). The param still parses.
        resp = await client.get(
            "/api/viewing-history?content_type=movie",
            headers=user_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] >= 1


class TestContinueWatchingEpisodeDedup:
    async def test_continue_watching_episode_dedup(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        """Continue watching deduplicates episodes from the same show."""
        # Watch two episodes from the same show
        for ep_key in ("ep1", "ep2"):
            ep = show_hierarchy[ep_key]
            await client.post(
                "/api/viewing-history",
                headers=user_headers,
                json={
                    "content_type": "episode",
                    "episode_guid": str(ep.guid),
                    "progress_seconds": 600,
                    "duration_seconds": 2400,
                },
            )

        resp = await client.get(
            "/api/viewing-history/continue-watching",
            headers=user_headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        # Should be deduplicated to 1 entry per show
        assert len(items) == 1
        assert items[0]["content_type"] == "episode"
        assert items[0]["show_title"] == "Test Show"
        assert items[0]["season_number"] == 1

    async def test_continue_watching_episode_filter(
        self, client: AsyncClient, test_user: User, user_headers, movie, show_hierarchy
    ):
        """Continue watching with content_type=episode filter."""
        # Movie progress
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 1800,
                "duration_seconds": 7200,
            },
        )
        # Episode progress
        ep = show_hierarchy["ep1"]
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(ep.guid),
                "progress_seconds": 600,
                "duration_seconds": 2400,
            },
        )

        resp = await client.get(
            "/api/viewing-history/continue-watching?content_type=episode",
            headers=user_headers,
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["content_type"] == "episode"


class TestRecentlyWatchedEpisodeHierarchy:
    async def test_recently_watched_show_hierarchy(
        self, client: AsyncClient, test_user: User, user_headers, show_hierarchy
    ):
        """Recently watched includes show_title, season_number, episode_number."""
        ep = show_hierarchy["ep1"]
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "episode",
                "episode_guid": str(ep.guid),
                "progress_seconds": 2300,
                "duration_seconds": 2400,
            },
        )
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["show_title"] == "Test Show"
        assert items[0]["season_number"] == 1
        assert items[0]["episode_number"] == 1

    async def test_recently_watched_completed_items(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """Recently watched includes completed items."""
        # Create a completed entry (>90%)
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 7000,
                "duration_seconds": 7200,
            },
        )
        resp = await client.get(
            "/api/viewing-history/recently-watched", headers=user_headers
        )
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["is_completed"] is True


class TestCreateViewingHistorySong:
    async def test_create_song_history(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        """Create viewing history for a song."""
        song = MediaItem(title="Test Song", media_type=MediaType.SONGS)
        db_session.add(song)
        await db_session.commit()
        await db_session.refresh(song)

        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "music",
                "song_guid": str(song.guid),
                "progress_seconds": 60,
                "duration_seconds": 240,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["song_guid"] == str(song.guid)


# ===========================================================================
# Additional coverage tests
# ===========================================================================


class TestCreateViewingHistoryNoDuration:
    async def test_create_with_zero_duration(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """Create history with duration_seconds=0."""
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 0,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_completed"] is False
        assert data["progress_percentage"] == 0.0

    async def test_update_without_duration(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        """Update existing entry without providing duration_seconds."""
        # Create first
        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        # Update without duration
        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 200,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        # duration_seconds should remain from original
        assert data["duration_seconds"] == 7200


class TestContinueWatchingGameFilter:
    async def test_continue_watching_game_filter(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        """Test content_type=game filter for continue watching."""
        game = MediaItem(title="Test Game", media_type=MediaType.GAMES)
        db_session.add(game)
        await db_session.commit()
        await db_session.refresh(game)

        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "game",
                "movie_guid": str(game.guid),
                "progress_seconds": 100,
                "duration_seconds": 600,
            },
        )

        resp = await client.get(
            "/api/viewing-history/continue-watching?content_type=game",
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_continue_watching_music_filter(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        """Test content_type=music filter for continue watching."""
        song = MediaItem(title="Test Song CW", media_type=MediaType.SONGS)
        db_session.add(song)
        await db_session.commit()
        await db_session.refresh(song)

        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "music",
                "song_guid": str(song.guid),
                "progress_seconds": 30,
                "duration_seconds": 240,
            },
        )

        resp = await client.get(
            "/api/viewing-history/continue-watching?content_type=music",
            headers=user_headers,
        )
        assert resp.status_code == 200

    async def test_continue_watching_book_filter(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Test content_type=book filter (even if no items)."""
        resp = await client.get(
            "/api/viewing-history/continue-watching?content_type=book",
            headers=user_headers,
        )
        assert resp.status_code == 200
        assert resp.json() == []


class TestListViewingHistoryShowType:
    async def test_list_with_show_type_item(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, user_headers
    ):
        """List viewing history with a SHOWS item that has no parent (show-level)."""
        show = MediaItem(title="Show Level Item", media_type=MediaType.SHOWS)
        db_session.add(show)
        await db_session.commit()
        await db_session.refresh(show)

        await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "show",
                "movie_guid": str(show.guid),
                "progress_seconds": 100,
                "duration_seconds": 3600,
            },
        )

        resp = await client.get("/api/viewing-history", headers=user_headers)
        assert resp.status_code == 200
        items = resp.json()["items"]
        # Find our show item
        show_items = [i for i in items if i.get("movie_guid") == str(show.guid)]
        assert len(show_items) >= 1


class TestViewingHistoryAccessPolicy:
    """Contract tests: the central media-access policy gates history writes."""

    async def test_create_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers, movie
    ):
        test_user.allowed_libraries = []
        await db_session.commit()

        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(movie.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        assert resp.status_code == 403

    async def test_create_respects_parental_controls(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.parental_max_age = 12
        item = MediaItem(title="Adult Movie", media_type=MediaType.MOVIES, min_age=18)
        db_session.add(item)
        await db_session.commit()
        await db_session.refresh(item)

        resp = await client.post(
            "/api/viewing-history",
            headers=user_headers,
            json={
                "content_type": "movie",
                "movie_guid": str(item.guid),
                "progress_seconds": 100,
                "duration_seconds": 7200,
            },
        )
        # min_age denials are masked as 404 by the central read policy
        assert resp.status_code == 404

    async def test_playstate_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers, movie
    ):
        test_user.allowed_libraries = []
        await db_session.commit()

        resp = await client.post(
            "/api/viewing-history/playstate",
            headers=user_headers,
            json={"content_guid": str(movie.guid), "progress_seconds": 100},
        )
        assert resp.status_code == 403
