"""Tests for media user-data endpoints (/api/media/{item}/user-data)."""

import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.list import List, ListItem
from streamarr.models.media import AvailabilityStatus, MediaItem, MediaType
from streamarr.models.user import User
from streamarr.models.viewing_history import ViewingHistory


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = {
        "guid": uuid.uuid4(),
        "title": "User Data Movie",
        "media_type": MediaType.MOVIES,
        "availability_status": AvailabilityStatus.UNKNOWN,
        "created_at": datetime.now(UTC),
        "updated_at": datetime.now(UTC),
    }
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestMediaUserData:
    async def test_get_requires_auth(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/user-data")
        assert resp.status_code == 401

    async def test_get_empty_user_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.get(f"/api/media/{item.guid}/user-data", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["media_item_guid"] == str(item.guid)
        assert data["is_favorite"] is False
        assert data["is_liked"] is False
        assert data["liked_at"] is None
        assert data["is_played"] is False
        assert data["playback_position_seconds"] == 0
        assert data["progress_percentage"] == 0.0

    async def test_update_favorite_and_playstate(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={
                "is_favorite": True,
                "playback_position_seconds": 90,
                "duration_seconds": 100,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_favorite"] is True
        assert data["playback_position_seconds"] == 90
        assert data["duration_seconds"] == 100
        assert data["progress_percentage"] == 90.0

        played = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={"is_played": True},
        )
        assert played.status_code == 200
        assert played.json()["is_played"] is True
        assert played.json()["progress_percentage"] == 100.0

    async def test_update_like_state(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        liked = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={"is_liked": True},
        )

        assert liked.status_code == 200
        liked_data = liked.json()
        assert liked_data["is_liked"] is True
        assert liked_data["liked_at"] is not None

        likes_list_result = await db_session.execute(
            select(List).where(
                List.owner_guid == test_user.guid,
                List.update_source == "user:liked_media",
            )
        )
        likes_list = likes_list_result.scalar_one()
        like_item_result = await db_session.execute(
            select(ListItem).where(
                ListItem.list_guid == likes_list.guid,
                ListItem.item_guid == item.guid,
            )
        )
        assert like_item_result.scalar_one().added_by_guid == test_user.guid
        assert likes_list.item_count == 1

        unliked = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={"is_liked": False},
        )

        assert unliked.status_code == 200
        unliked_data = unliked.json()
        assert unliked_data["is_liked"] is False
        assert unliked_data["liked_at"] is None

        remaining_like_result = await db_session.execute(
            select(ListItem).where(
                ListItem.list_guid == likes_list.guid,
                ListItem.item_guid == item.guid,
            )
        )
        assert remaining_like_result.scalar_one_or_none() is None
        await db_session.refresh(likes_list)
        assert likes_list.item_count == 0

    async def test_update_selected_track_preferences(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={
                "selected_audio_track_index": 1,
                "selected_subtitle_track_index": 2,
                "selected_subtitle_track_id": "opensubtitles:sub-en",
                "selected_audio_language": "de",
                "selected_subtitle_language": "en",
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["selected_audio_track_index"] == 1
        assert data["selected_subtitle_track_index"] == 2
        assert data["selected_subtitle_track_id"] == "opensubtitles:sub-en"
        assert data["selected_audio_language"] == "de"
        assert data["selected_subtitle_language"] == "en"

        history_result = await db_session.execute(
            select(ViewingHistory).where(
                ViewingHistory.user_guid == test_user.guid,
                ViewingHistory.media_item_guid == item.guid,
            )
        )
        history = history_result.scalar_one()
        extra_data = json.loads(history.extra_data)
        assert extra_data["playback_preferences"]["audio_track_index"] == 1

    async def test_clear_selected_track_preferences_preserves_progress(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={
                "playback_position_seconds": 50,
                "duration_seconds": 100,
                "selected_audio_track_index": 1,
                "selected_subtitle_track_id": "sub-en",
            },
        )

        resp = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={
                "selected_audio_track_index": None,
                "selected_subtitle_track_id": None,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["playback_position_seconds"] == 50
        assert data["progress_percentage"] == 50.0
        assert data["selected_audio_track_index"] is None
        assert data["selected_subtitle_track_id"] is None

    async def test_unfavorite_and_unplayed(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)
        await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={"is_favorite": True, "is_played": True},
        )

        resp = await client.put(
            f"/api/media/{item.guid}/user-data",
            headers=user_headers,
            json={"is_favorite": False, "is_played": False},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["is_favorite"] is False
        assert data["is_played"] is False
        assert data["progress_percentage"] == 0.0

    async def test_user_data_commands_update_state(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        played = await client.post(f"/api/media/{item.guid}/played", headers=user_headers)
        assert played.status_code == 200
        assert played.json()["is_played"] is True
        assert played.json()["progress_percentage"] == 100.0

        favorite = await client.post(f"/api/media/{item.guid}/favorite", headers=user_headers)
        assert favorite.status_code == 200
        assert favorite.json()["is_favorite"] is True

        liked = await client.post(f"/api/media/{item.guid}/like", headers=user_headers)
        assert liked.status_code == 200
        assert liked.json()["is_liked"] is True

        unplayed = await client.delete(f"/api/media/{item.guid}/played", headers=user_headers)
        assert unplayed.status_code == 200
        assert unplayed.json()["is_played"] is False
        assert unplayed.json()["progress_percentage"] == 0.0

        unfavorite = await client.delete(f"/api/media/{item.guid}/favorite", headers=user_headers)
        assert unfavorite.status_code == 200
        assert unfavorite.json()["is_favorite"] is False

        unliked = await client.delete(f"/api/media/{item.guid}/like", headers=user_headers)
        assert unliked.status_code == 200
        assert unliked.json()["is_liked"] is False

    async def test_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(db_session)
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/user-data", headers=user_headers)

        assert resp.status_code == 403

    async def test_respects_parental_controls(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(db_session, min_age=18)
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/user-data", headers=user_headers)

        assert resp.status_code == 404
