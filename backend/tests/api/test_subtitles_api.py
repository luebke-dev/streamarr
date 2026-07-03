"""Tests for media subtitle endpoints (/api/media/{item}/subtitles)."""

import json
import uuid
from datetime import UTC, datetime

import httpx
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.activity_log import ActivityLog
from pyrate.models.media import AvailabilityStatus, MediaItem, MediaType
from pyrate.models.user import User


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = dict(
        guid=uuid.uuid4(),
        title="Subtitled Movie",
        media_type=MediaType.MOVIES,
        availability_status=AvailabilityStatus.UNKNOWN,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    defaults.update(overrides)
    item = MediaItem(**defaults)
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestGetMediaSubtitles:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/subtitles")
        assert resp.status_code == 401

    async def test_lists_subtitles_from_extra_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "subtitle_tracks": [
                        {
                            "guid": "en-main",
                            "lang": "en",
                            "title": "English",
                            "format": "srt",
                            "path": "/library/movie/en.srt",
                            "forced": False,
                            "default": True,
                        }
                    ]
                }
            ),
        )

        resp = await client.get(f"/api/media/{item.guid}/subtitles", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "id": "en-main",
                "language": "en",
                "title": "English",
                "format": "srt",
                "path": "/library/movie/en.srt",
                "url": None,
                "is_forced": False,
                "is_default": True,
            }
        ]

    async def test_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"subtitles": [{"id": "en", "language": "en"}]}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/subtitles", headers=user_headers)

        assert resp.status_code == 403


class TestManageMediaSubtitles:
    async def test_replace_subtitles_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/subtitles",
            headers=admin_headers,
            json={
                "subtitles": [
                    {
                        "id": "en-main",
                        "language": "en",
                        "title": "English",
                        "format": "vtt",
                        "url": "https://example.test/en.vtt",
                        "is_default": True,
                    }
                ]
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["id"] == "en-main"
        assert data[0]["format"] == "vtt"
        assert data[0]["is_default"] is True

    async def test_replace_subtitles_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/subtitles",
            headers=user_headers,
            json={"subtitles": [{"id": "en", "language": "en"}]},
        )

        assert resp.status_code == 403

    async def test_delete_subtitle_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"subtitles": [{"id": "en", "language": "en"}]}),
        )

        resp = await client.delete(
            f"/api/media/{item.guid}/subtitles/en", headers=admin_headers
        )

        assert resp.status_code == 204

    async def test_delete_missing_subtitle_returns_404(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.delete(
            f"/api/media/{item.guid}/subtitles/missing", headers=admin_headers
        )

        assert resp.status_code == 404


class TestSubtitleProviders:
    async def test_search_provider_results(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_subtitles": [
                        {
                            "provider": "opensubtitles",
                            "id": "sub-en",
                            "language": "en",
                            "title": "English",
                            "format": "srt",
                            "url": "https://example.test/en.srt",
                            "score": 92.5,
                        },
                        {
                            "provider": "opensubtitles",
                            "id": "sub-de",
                            "language": "de",
                            "title": "Deutsch",
                            "format": "srt",
                            "url": "https://example.test/de.srt",
                            "score": 80,
                        },
                    ]
                }
            ),
        )

        resp = await client.get(
            f"/api/media/{item.guid}/subtitles/search?language=en",
            headers=user_headers,
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["provider"] == "opensubtitles"
        assert data["items"][0]["provider_id"] == "sub-en"
        assert data["items"][0]["language"] == "en"
        assert data["items"][0]["match_score"] == 117.5
        assert "language" in data["items"][0]["match_reasons"]

    async def test_search_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {"remote_subtitles": [{"id": "sub-en", "language": "en"}]}
            ),
        )
        await db_session.commit()

        resp = await client.get(
            f"/api/media/{item.guid}/subtitles/search",
            headers=user_headers,
        )

        assert resp.status_code == 403

    async def test_download_provider_result_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "remote_subtitles": [
                        {
                            "provider": "opensubtitles",
                            "id": "sub-en",
                            "language": "en",
                            "title": "English SDH",
                            "format": "srt",
                            "url": "https://example.test/en.srt",
                        }
                    ],
                    "subtitles": [
                        {
                            "id": "old-en",
                            "language": "en",
                            "title": "Old English",
                            "is_default": True,
                        }
                    ],
                }
            ),
        )

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/download",
            headers=admin_headers,
            json={
                "provider": "opensubtitles",
                "provider_id": "sub-en",
                "make_default": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "downloaded"
        assert data["subtitle"]["id"] == "opensubtitles:sub-en"
        assert data["subtitle"]["is_default"] is True

        subtitles = await client.get(
            f"/api/media/{item.guid}/subtitles", headers=admin_headers
        )
        assert subtitles.status_code == 200
        stored = subtitles.json()
        assert any(sub["id"] == "opensubtitles:sub-en" for sub in stored)
        assert all(
            not sub["is_default"]
            for sub in stored
            if sub["id"] != "opensubtitles:sub-en" and sub["language"] == "en"
        )

        log_result = await db_session.execute(
            select(ActivityLog).where(ActivityLog.event_type == "subtitle.download")
        )
        log_entry = log_result.scalar_one()
        assert log_entry.entity_guid == item.guid
        assert "opensubtitles" in log_entry.extra_data

    async def test_download_provider_result_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {"remote_subtitles": [{"provider": "metadata", "id": "sub-en", "language": "en"}]}
            ),
        )

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/download",
            headers=user_headers,
            json={"provider": "metadata", "provider_id": "sub-en"},
        )

        assert resp.status_code == 403

    async def test_download_missing_provider_result_returns_404(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/download",
            headers=admin_headers,
            json={"provider": "metadata", "provider_id": "missing"},
        )

        assert resp.status_code == 404

    async def test_network_provider_search_service(self, db_session: AsyncSession):
        from pyrate.services.subtitle_provider import SubtitleProviderService

        item = await _create_media_item(db_session)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.params["title"] == item.title
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "id": "net-en",
                            "language": "en",
                            "title": "Network English",
                            "format": "srt",
                            "url": "https://subs.example/en.srt",
                            "score": 95,
                        }
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            service = SubtitleProviderService(
                enabled_providers=["custom"],
                provider_urls={"custom": "https://subs.example/search"},
                client=http_client,
            )
            results = await service.search_async(item, language="en")

        assert len(results) == 1
        assert results[0]["provider"] == "custom"
        assert results[0]["provider_id"] == "net-en"
        assert results[0]["url"] == "https://subs.example/en.srt"

    async def test_opensubtitles_provider_search_service(self, db_session: AsyncSession):
        from pyrate.services.subtitle_provider import SubtitleProviderService

        item = await _create_media_item(db_session)

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Api-Key"] == "secret-key"
            assert request.url.params["query"] == item.title
            assert request.url.params["languages"] == "en"
            assert request.url.params["type"] == "movie"
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "os-sub-1",
                            "attributes": {
                                "language": "en",
                                "release": "Movie.2024.1080p-GROUP",
                                "ratings": 9.1,
                                "download_count": 123,
                                "hearing_impaired": True,
                                "feature_details": {"title": "Subtitled Movie"},
                                "files": [
                                    {
                                        "file_id": 98765,
                                        "file_name": "Movie.2024.1080p-GROUP.srt",
                                    }
                                ],
                            },
                        }
                    ]
                },
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            service = SubtitleProviderService(
                enabled_providers=["opensubtitles"],
                provider_urls={"opensubtitles": "https://api.opensubtitles.test/subtitles"},
                provider_api_keys={"opensubtitles": "secret-key"},
                client=http_client,
            )
            results = await service.search_async(item, language="en")

        assert len(results) == 1
        assert results[0]["provider"] == "opensubtitles"
        assert results[0]["provider_id"] == "98765"
        assert results[0]["file_name"] == "Movie.2024.1080p-GROUP.srt"
        assert results[0]["format"] == "srt"
        assert results[0]["score"] == 9.1
        assert results[0]["downloads"] == 123
        assert results[0]["is_hearing_impaired"] is True

    async def test_opensubtitles_download_resolution_service(
        self, db_session: AsyncSession
    ):
        from pyrate.services.subtitle_provider import SubtitleProviderService

        item = await _create_media_item(db_session)

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "data": [
                            {
                                "attributes": {
                                    "language": "en",
                                    "files": [
                                        {
                                            "file_id": 98765,
                                            "file_name": "Movie.Release.srt",
                                        }
                                    ],
                                }
                            }
                        ]
                    },
                )
            assert request.method == "POST"
            assert request.url.path == "/download"
            assert request.headers["Api-Key"] == "secret-key"
            assert json.loads(request.content) == {"file_id": 98765}
            return httpx.Response(
                200,
                json={
                    "link": "https://download.opensubtitles.test/file.srt",
                    "file_name": "Resolved.Movie.srt",
                },
            )

        transport = httpx.MockTransport(handler)
        async with httpx.AsyncClient(transport=transport) as http_client:
            service = SubtitleProviderService(
                enabled_providers=["opensubtitles"],
                provider_urls={"opensubtitles": "https://api.opensubtitles.test/subtitles"},
                provider_api_keys={"opensubtitles": "secret-key"},
                client=http_client,
            )
            candidate = (
                await service.search_async(item, language="en", provider="opensubtitles")
            )[0]
            resolved = await service.resolve_download_async(candidate)

        assert resolved["provider_id"] == "98765"
        assert resolved["url"] == "https://download.opensubtitles.test/file.srt"
        assert resolved["file_name"] == "Resolved.Movie.srt"
        assert resolved["format"] == "srt"


class TestSubtitleUpload:
    async def test_user_can_upload_and_read_subtitle_content(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/upload",
            headers=user_headers,
            json={
                "language": "en",
                "content": "1\n00:00:00,000 --> 00:00:01,000\nHello\n",
                "file_name": "English.srt",
                "make_default": True,
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "uploaded"
        subtitle = data["subtitle"]
        assert subtitle["id"].startswith("upload:")
        assert subtitle["language"] == "en"
        assert subtitle["format"] == "srt"
        assert subtitle["is_default"] is True

        content = await client.get(
            f"/api/media/{item.guid}/subtitles/{subtitle['id']}/content",
            headers=user_headers,
        )
        assert content.status_code == 200
        assert "Hello" in content.text

    async def test_user_can_read_remote_subtitle_content_via_proxy(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
        monkeypatch,
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "subtitles": [
                        {
                            "id": "remote-en",
                            "language": "en",
                            "format": "vtt",
                            "url": "https://subtitles.test/en.vtt",
                        }
                    ]
                }
            ),
        )

        class _FakeResponse:
            content = b"WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n"
            encoding = "utf-8"

            def raise_for_status(self):
                return None

        async def _fake_safe_get(url, **kwargs):
            assert url == "https://subtitles.test/en.vtt"
            return _FakeResponse()

        monkeypatch.setattr("pyrate.api.v1.subtitles.safe_get", _fake_safe_get)

        content = await client.get(
            f"/api/media/{item.guid}/subtitles/remote-en/content",
            headers=user_headers,
        )

        assert content.status_code == 200
        assert content.headers["content-type"].startswith("text/vtt")
        assert "Hello" in content.text

    async def test_remote_subtitle_rejects_non_http_url(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "subtitles": [
                        {
                            "id": "local",
                            "language": "en",
                            "url": "file:///etc/passwd",
                        }
                    ]
                }
            ),
        )

        content = await client.get(
            f"/api/media/{item.guid}/subtitles/local/content",
            headers=user_headers,
        )

        assert content.status_code == 404

    async def test_upload_default_clears_existing_language_default(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "subtitles": [
                        {
                            "id": "old-en",
                            "language": "en",
                            "title": "Old English",
                            "is_default": True,
                        }
                    ]
                }
            ),
        )

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/upload",
            headers=user_headers,
            json={
                "language": "en",
                "content": "WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHi\n",
                "format": "vtt",
                "make_default": True,
            },
        )

        assert resp.status_code == 200
        subtitles = await client.get(
            f"/api/media/{item.guid}/subtitles", headers=user_headers
        )
        assert subtitles.status_code == 200
        stored = subtitles.json()
        assert next(sub for sub in stored if sub["id"] == "old-en")["is_default"] is False

    async def test_upload_rejects_unsupported_format(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/upload",
            headers=user_headers,
            json={"language": "en", "content": "hello", "format": "exe"},
        )

        assert resp.status_code == 422

    async def test_upload_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(db_session)
        await db_session.commit()

        resp = await client.post(
            f"/api/media/{item.guid}/subtitles/upload",
            headers=user_headers,
            json={"language": "en", "content": "hello"},
        )

        assert resp.status_code == 403

    async def test_delete_uploaded_subtitle_removes_content(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)
        upload = await client.post(
            f"/api/media/{item.guid}/subtitles/upload",
            headers=admin_headers,
            json={"language": "en", "content": "hello"},
        )
        subtitle_id = upload.json()["subtitle"]["id"]

        deleted = await client.delete(
            f"/api/media/{item.guid}/subtitles/{subtitle_id}", headers=admin_headers
        )
        assert deleted.status_code == 204

        content = await client.get(
            f"/api/media/{item.guid}/subtitles/{subtitle_id}/content",
            headers=admin_headers,
        )
        assert content.status_code == 404
