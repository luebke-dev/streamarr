"""Tests for media chapter endpoints (/api/media/{item}/chapters)."""

import json
import uuid
from datetime import UTC, datetime

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import AvailabilityStatus, MediaItem, MediaType
from pyrate.models.user import User


async def _create_media_item(db: AsyncSession, **overrides) -> MediaItem:
    defaults = dict(
        guid=uuid.uuid4(),
        title="Chaptered Movie",
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


class TestGetMediaChapters:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/chapters")
        assert resp.status_code == 401

    async def test_lists_chapters_from_extra_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "chapters": [
                        {"title": "Middle", "start_seconds": 60, "end_seconds": 120},
                        {"title": "Opening", "start": 0, "end": 60},
                    ]
                }
            ),
        )

        resp = await client.get(f"/api/media/{item.guid}/chapters", headers=user_headers)

        assert resp.status_code == 200
        data = resp.json()
        assert [chapter["title"] for chapter in data] == ["Opening", "Middle"]
        assert data[0]["start_seconds"] == 0
        assert data[1]["end_seconds"] == 120

    async def test_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"chapters": [{"title": "One", "start_seconds": 0}]}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/chapters", headers=user_headers)

        assert resp.status_code == 403

    async def test_respects_parental_controls(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            min_age=18,
            extra_data=json.dumps({"chapters": [{"title": "One", "start_seconds": 0}]}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/chapters", headers=user_headers)

        assert resp.status_code == 404


class TestReplaceMediaChapters:
    async def test_replace_chapters_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/chapters",
            headers=admin_headers,
            json={
                "chapters": [
                    {"title": "Opening", "start_seconds": 0},
                    {"title": "Finale", "start_seconds": 90, "end_seconds": 120},
                ]
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["end_seconds"] == 90
        assert data[1]["title"] == "Finale"

    async def test_replace_chapters_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/chapters",
            headers=user_headers,
            json={"chapters": [{"title": "Opening", "start_seconds": 0}]},
        )

        assert resp.status_code == 403

    async def test_rejects_end_before_start(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/chapters",
            headers=admin_headers,
            json={"chapters": [{"title": "Bad", "start_seconds": 10, "end_seconds": 5}]},
        )

        assert resp.status_code == 400
