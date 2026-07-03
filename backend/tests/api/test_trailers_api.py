"""Tests for top-level trailer browsing endpoints."""

import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import AvailabilityStatus, MediaItem, MediaType
from pyrate.models.user import User


async def _create_item(
    db: AsyncSession,
    *,
    title: str,
    media_type: MediaType = MediaType.MOVIES,
    extra_data: dict | None = None,
    min_age: int | None = None,
) -> MediaItem:
    now = datetime.now(UTC)
    item = MediaItem(
        guid=uuid.uuid4(),
        title=title,
        media_type=media_type,
        availability_status=AvailabilityStatus.AVAILABLE,
        extra_data=json.dumps(extra_data) if extra_data is not None else None,
        min_age=min_age,
        created_at=now,
        updated_at=now,
    )
    db.add(item)
    await db.commit()
    await db.refresh(item)
    return item


class TestBrowseTrailers:
    async def test_requires_auth(self, client: AsyncClient):
        resp = await client.get("/api/trailers")
        assert resp.status_code == 401

    async def test_returns_items_with_metadata_trailers(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        item = await _create_item(
            db_session,
            title="Trailer Movie",
            extra_data={
                "remote_trailers": [
                    {
                        "provider": "tmdb",
                        "id": "trailer-1",
                        "name": "Official Trailer",
                        "site": "YouTube",
                        "key": "abc123",
                        "type": "Trailer",
                    }
                ]
            },
        )
        await _create_item(db_session, title="No Trailer")

        resp = await client.get("/api/trailers", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["media_item"]["guid"] == str(item.guid)
        assert data["items"][0]["trailer_count"] == 1
        assert data["items"][0]["trailers"][0]["url"] == (
            "https://www.youtube.com/watch?v=abc123"
        )

    async def test_filters_by_permissions_and_parental_control(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["movies"]
        test_user.parental_max_age = 12
        trailer_data = {
            "trailers": [{"id": "trailer", "name": "Trailer", "url": "https://example.test"}]
        }
        await _create_item(
            db_session,
            title="Allowed Movie",
            media_type=MediaType.MOVIES,
            extra_data=trailer_data,
            min_age=12,
        )
        await _create_item(
            db_session,
            title="Blocked Movie",
            media_type=MediaType.MOVIES,
            extra_data=trailer_data,
            min_age=18,
        )
        await _create_item(
            db_session,
            title="Blocked Song",
            media_type=MediaType.SONGS,
            extra_data=trailer_data,
        )
        await db_session.commit()

        resp = await client.get("/api/trailers", headers=user_headers)

        assert resp.status_code == 200
        titles = [item["media_item"]["title"] for item in resp.json()["items"]]
        assert titles == ["Allowed Movie"]

    async def test_denies_disallowed_media_type(
        self,
        client: AsyncClient,
        db_session: AsyncSession,
        test_user: User,
        user_headers,
    ):
        test_user.allowed_libraries = ["music"]
        await db_session.commit()

        resp = await client.get(
            "/api/trailers",
            headers=user_headers,
            params={"media_type": "MOVIES"},
        )

        assert resp.status_code == 403
