"""Tests for media lyrics endpoints (/api/media/{item}/lyrics)."""

import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.api.v1 import lyrics as lyrics_api
from pyrate.models.activity_log import ActivityLog
from pyrate.models.media import AvailabilityStatus, MediaItem, MediaType
from pyrate.models.user import User


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = {
        "guid": uuid.uuid4(),
        "title": "Lyric Song",
        "media_type": MediaType.SONGS,
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


class TestGetMediaLyrics:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/lyrics")
        assert resp.status_code == 401

    async def test_reads_plain_text_lyrics(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"lyrics": "Line one\nLine two"}),
        )

        resp = await client.get(f"/api/media/{item.guid}/lyrics", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == {
            "lyrics": "Line one\nLine two",
            "synced": False,
            "source": None,
        }

    async def test_reads_structured_lyrics(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {"lyrics": {"text": "[00:00.00] Line one", "synced": True, "source": "local"}}
            ),
        )

        resp = await client.get(f"/api/media/{item.guid}/lyrics", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["lyrics"] == "[00:00.00] Line one"
        assert data["synced"] is True
        assert data["source"] == "local"

    async def test_missing_lyrics_returns_404(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.get(f"/api/media/{item.guid}/lyrics", headers=user_headers)

        assert resp.status_code == 404

    async def test_respects_music_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = ["movies"]
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"lyrics": "Hidden"}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/lyrics", headers=user_headers)

        assert resp.status_code == 403


class TestManageMediaLyrics:
    async def test_replace_lyrics_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/lyrics",
            headers=admin_headers,
            json={"lyrics": "Line one", "synced": False, "source": "manual"},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "lyrics": "Line one",
            "synced": False,
            "source": "manual",
        }

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "lyrics.update")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "manual" in log_entry.extra_data

    async def test_replace_lyrics_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/lyrics",
            headers=user_headers,
            json={"lyrics": "Line one"},
        )

        assert resp.status_code == 403

    async def test_search_remote_lyrics_from_metadata(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_lyrics": [
                        {
                            "provider": "lrclib",
                            "id": "first",
                            "title": "Lyric Song",
                            "artist": "The Crew",
                            "text": "[00:01.00]Line one",
                            "synced": True,
                            "score": "0.92",
                        },
                        {
                            "provider": "manual",
                            "id": "second",
                            "lyrics": "Different song",
                        },
                    ]
                }
            ),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/lyrics/search",
            headers=user_headers,
            params={"query": "crew", "provider": "lrclib"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0] == {
            "provider": "lrclib",
            "provider_id": "first",
            "title": "Lyric Song",
            "artist": "The Crew",
            "lyrics": "[00:01.00]Line one",
            "synced": True,
            "source": "lrclib",
            "score": 0.92,
        }

    async def test_search_remote_lyrics_from_configured_provider(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        monkeypatch,
    ):
        class FakeSettingsService:
            def __init__(self, db):
                pass

            async def get(self, key, default=None):
                values = {
                    "lyrics.providers": ["lrclib"],
                    "lyrics.provider_urls": {"lrclib": "https://lyrics.example/search"},
                    "lyrics.provider_api_keys": {"lrclib": "secret"},
                }
                return values.get(key, default)

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return {
                    "items": [
                        {
                            "id": "net-1",
                            "title": "Lyric Song",
                            "artist": "Network Artist",
                            "lyrics": "Network line",
                            "score": 0.8,
                        }
                    ]
                }

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                self.requests = []

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, params=None, headers=None):
                assert url == "https://lyrics.example/search"
                assert params == {"track_name": "Network"}
                assert headers == {"Authorization": "Bearer secret"}
                return FakeResponse()

        item = await _create_media_item(db_session)
        monkeypatch.setattr(lyrics_api, "SettingsService", FakeSettingsService)
        monkeypatch.setattr(lyrics_api.httpx, "AsyncClient", FakeAsyncClient)

        resp = await client.get(
            f"/api/media/{item.guid}/lyrics/search",
            headers=user_headers,
            params={"query": "Network", "provider": "lrclib"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "lrclib"
        assert data["items"][0]["provider_id"] == "net-1"
        assert data["items"][0]["lyrics"] == "Network line"

    async def test_search_remote_lyrics_normalizes_lrclib_shape(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        monkeypatch,
    ):
        class FakeSettingsService:
            def __init__(self, db):
                pass

            async def get(self, key, default=None):
                values = {
                    "lyrics.providers": ["lrclib"],
                    "lyrics.provider_urls": {"lrclib": "https://lrclib.example/api/search"},
                    "lyrics.provider_api_keys": {},
                }
                return values.get(key, default)

        class FakeResponse:
            def raise_for_status(self):
                pass

            def json(self):
                return [
                    {
                        "id": 42,
                        "trackName": "Lyric Song",
                        "artistName": "Network Artist",
                        "plainLyrics": "Plain line",
                        "syncedLyrics": "[00:01.00]Synced line",
                    }
                ]

        class FakeAsyncClient:
            def __init__(self, *args, **kwargs):
                pass

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return None

            async def get(self, url, params=None, headers=None):
                assert url == "https://lrclib.example/api/search"
                assert params == {"track_name": "Lyric Song"}
                assert headers is None
                return FakeResponse()

        item = await _create_media_item(db_session)
        monkeypatch.setattr(lyrics_api, "SettingsService", FakeSettingsService)
        monkeypatch.setattr(lyrics_api.httpx, "AsyncClient", FakeAsyncClient)

        resp = await client.get(
            f"/api/media/{item.guid}/lyrics/search",
            headers=user_headers,
            params={"provider": "lrclib"},
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "lrclib"
        assert data["items"][0]["provider_id"] == "42"
        assert data["items"][0]["title"] == "Lyric Song"
        assert data["items"][0]["artist"] == "Network Artist"
        assert data["items"][0]["lyrics"] == "[00:01.00]Synced line"
        assert data["items"][0]["synced"] is True

    async def test_download_remote_lyrics_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "lyrics_results": {
                        "items": [
                            {
                                "provider": "lrclib",
                                "provider_id": "abc123",
                                "lyrics": "[00:01.00]Downloaded line",
                                "synced": True,
                            }
                        ]
                    }
                }
            ),
        )

        resp = await client.post(
            f"/api/media/{item.guid}/lyrics/download",
            headers=admin_headers,
            json={"provider": "lrclib", "provider_id": "abc123"},
        )

        assert resp.status_code == 200
        assert resp.json() == {
            "lyrics": "[00:01.00]Downloaded line",
            "synced": True,
            "source": "lrclib",
        }

        get_resp = await client.get(f"/api/media/{item.guid}/lyrics", headers=admin_headers)
        assert get_resp.status_code == 200
        assert get_resp.json()["lyrics"] == "[00:01.00]Downloaded line"

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "lyrics.download")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "lrclib" in log_entry.extra_data

    async def test_download_remote_lyrics_missing_returns_404(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {"remote_lyrics": [{"provider": "lrclib", "id": "abc123", "lyrics": "Line"}]}
            ),
        )

        resp = await client.post(
            f"/api/media/{item.guid}/lyrics/download",
            headers=admin_headers,
            json={"provider": "lrclib", "provider_id": "missing"},
        )

        assert resp.status_code == 404

    async def test_download_remote_lyrics_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/lyrics/download",
            headers=user_headers,
            json={"provider": "lrclib", "provider_id": "abc123"},
        )

        assert resp.status_code == 403

    async def test_delete_lyrics_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"lyrics": "Line one"}),
        )

        resp = await client.delete(f"/api/media/{item.guid}/lyrics", headers=admin_headers)

        assert resp.status_code == 204
