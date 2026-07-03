"""Tests for media attachment endpoints (/api/media/{item}/attachments)."""

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
        title="Attached Movie",
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


class TestGetMediaAttachments:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.get(f"/api/media/{uuid.uuid4()}/attachments")
        assert resp.status_code == 401

    async def test_lists_attachments_from_extra_data(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps(
                {
                    "attachments": [
                        {
                            "filename": "cover.jpg",
                            "path": "/library/movie/cover.jpg",
                            "mimeType": "image/jpeg",
                            "type": "image",
                            "size": 1234,
                        }
                    ]
                }
            ),
        )

        resp = await client.get(f"/api/media/{item.guid}/attachments", headers=user_headers)

        assert resp.status_code == 200
        assert resp.json() == [
            {
                "name": "cover.jpg",
                "path": "/library/movie/cover.jpg",
                "url": None,
                "mime_type": "image/jpeg",
                "attachment_type": "image",
                "size_bytes": 1234,
            }
        ]

    async def test_respects_library_permissions(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.allowed_libraries = []
        item = await _create_media_item(
            db_session,
            extra_data=json.dumps({"attachments": [{"name": "cover.jpg"}]}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/attachments", headers=user_headers)

        assert resp.status_code == 403

    async def test_respects_parental_controls(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        test_user.parental_max_age = 12
        item = await _create_media_item(
            db_session,
            min_age=18,
            extra_data=json.dumps({"attachments": [{"name": "cover.jpg"}]}),
        )
        await db_session.commit()

        resp = await client.get(f"/api/media/{item.guid}/attachments", headers=user_headers)

        assert resp.status_code == 404


class TestReplaceMediaAttachments:
    async def test_replace_attachments_as_admin(
        self, client: AsyncClient, db_session: AsyncSession, test_superuser: User, admin_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/attachments",
            headers=admin_headers,
            json={
                "attachments": [
                    {
                        "name": "poster.png",
                        "url": "https://example.test/poster.png",
                        "mime_type": "image/png",
                    }
                ]
            },
        )

        assert resp.status_code == 200
        data = resp.json()
        assert data[0]["name"] == "poster.png"
        assert data[0]["url"] == "https://example.test/poster.png"
        assert data[0]["mime_type"] == "image/png"

    async def test_replace_attachments_as_user_forbidden(
        self, client: AsyncClient, db_session: AsyncSession, test_user: User, user_headers
    ):
        item = await _create_media_item(db_session)

        resp = await client.put(
            f"/api/media/{item.guid}/attachments",
            headers=user_headers,
            json={"attachments": [{"name": "poster.png"}]},
        )

        assert resp.status_code == 403
