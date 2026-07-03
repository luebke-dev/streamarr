"""Tests for the Banner API endpoints (/api/banners/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.user import User

from .conftest import auth_headers


class TestGetBanners:
    async def test_get_banners_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/banners")
        assert resp.status_code == 401

    async def test_get_banners_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/banners", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_get_banners_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/banners", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "items" in data
        assert "total" in data

    async def test_get_banners_admin_filter_active(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """Admin can filter banners by is_active status."""
        # Create active and inactive banners
        await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "Active", "message": "Yes", "banner_type": "info", "is_active": True},
        )
        await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "Inactive", "message": "No", "banner_type": "info", "is_active": False},
        )

        # Filter active only
        resp = await client.get("/api/banners?is_active=true", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        for item in data["items"]:
            assert item["is_active"] is True

        # Filter inactive only
        resp = await client.get("/api/banners?is_active=false", headers=admin_headers)
        assert resp.status_code == 200

    async def test_get_banners_admin_pagination(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """Admin pagination works correctly."""
        for i in range(5):
            await client.post(
                "/api/banners",
                headers=admin_headers,
                json={"title": f"Banner {i}", "message": f"Msg {i}", "banner_type": "info"},
            )

        resp = await client.get("/api/banners?page=1&per_page=2", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) == 2
        assert data["per_page"] == 2
        assert data["total_pages"] >= 3

    async def test_get_banners_user_show_dismissed(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        """Regular user with show_dismissed=true sees all active banners."""
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "Dismissable", "message": "Test", "banner_type": "info", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        # Dismiss the banner
        await client.post(f"/api/banners/{guid}/dismiss", headers=user_headers)

        # Without show_dismissed: dismissed banner should be hidden
        resp = await client.get("/api/banners", headers=user_headers)
        assert resp.status_code == 200
        guids = [b["guid"] for b in resp.json()["items"]]
        assert guid not in guids

        # With show_dismissed=true: banner should appear
        resp = await client.get("/api/banners?show_dismissed=true", headers=user_headers)
        assert resp.status_code == 200

    async def test_get_banners_user_pagination(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        """Regular user pagination for non-dismissed banners."""
        for i in range(5):
            await client.post(
                "/api/banners",
                headers=admin_headers,
                json={
                    "title": f"UserBanner {i}",
                    "message": f"Msg {i}",
                    "banner_type": "info",
                    "is_active": True,
                },
            )

        resp = await client.get("/api/banners?page=1&per_page=2", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["items"]) <= 2


class TestCreateBanner:
    async def test_create_banner_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={
                "title": "Test Banner",
                "message": "Hello World",
                "banner_type": "info",
                "is_active": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["title"] == "Test Banner"
        assert data["message"] == "Hello World"
        assert data["is_dismissed"] is False
        assert "guid" in data

    async def test_create_banner_with_all_fields(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={
                "title": "Full Banner",
                "message": "All fields set",
                "banner_type": "warning",
                "is_active": True,
                "dismissible": False,
                "start_date": "2026-01-01T00:00:00",
                "end_date": "2026-12-31T23:59:59",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["banner_type"] == "warning"
        assert data["dismissible"] is False

    async def test_create_banner_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/banners",
            headers=user_headers,
            json={
                "title": "Test",
                "message": "Nope",
                "banner_type": "info",
            },
        )
        assert resp.status_code == 403


class TestBannerCRUD:
    async def test_get_banner_by_guid(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        # Create first
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={
                "title": "Detail Banner",
                "message": "Details",
                "banner_type": "info",
                "is_active": True,
            },
        )
        assert create_resp.status_code == 201
        guid = create_resp.json()["guid"]

        # Get by GUID
        resp = await client.get(f"/api/banners/{guid}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["guid"] == guid
        assert "is_dismissed" in data

    async def test_get_banner_by_guid_as_user(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        """Regular user can get banner and sees is_dismissed flag."""
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "UserView", "message": "Test", "banner_type": "info", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        resp = await client.get(f"/api/banners/{guid}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["is_dismissed"] is False

    async def test_get_banner_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/banners/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_update_banner(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        # Create
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={
                "title": "Old Title",
                "message": "Old message",
                "banner_type": "info",
                "is_active": True,
            },
        )
        guid = create_resp.json()["guid"]

        # Update
        resp = await client.put(
            f"/api/banners/{guid}",
            headers=admin_headers,
            json={"title": "New Title"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "New Title"
        assert "is_dismissed" in data

    async def test_update_banner_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.put(
            f"/api/banners/{uuid.uuid4()}",
            headers=admin_headers,
            json={"title": "Ghost"},
        )
        assert resp.status_code == 404

    async def test_update_banner_as_user_forbidden(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "T", "message": "M", "banner_type": "info"},
        )
        guid = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/banners/{guid}",
            headers=user_headers,
            json={"title": "Hacked"},
        )
        assert resp.status_code == 403

    async def test_delete_banner(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "Del", "message": "Me", "banner_type": "info"},
        )
        guid = create_resp.json()["guid"]

        resp = await client.delete(f"/api/banners/{guid}", headers=admin_headers)
        assert resp.status_code == 204

        # Verify deleted
        resp = await client.get(f"/api/banners/{guid}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_banner_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.delete(f"/api/banners/{uuid.uuid4()}", headers=admin_headers)
        assert resp.status_code == 404

    async def test_delete_banner_as_user_forbidden(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "No", "message": "Del", "banner_type": "info"},
        )
        guid = create_resp.json()["guid"]

        resp = await client.delete(f"/api/banners/{guid}", headers=user_headers)
        assert resp.status_code == 403


class TestBannerDismiss:
    async def test_dismiss_banner(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={
                "title": "Dismiss Me",
                "message": "Go away",
                "banner_type": "info",
                "is_active": True,
            },
        )
        guid = create_resp.json()["guid"]

        resp = await client.post(
            f"/api/banners/{guid}/dismiss", headers=user_headers
        )
        assert resp.status_code == 204

        # Verify is_dismissed is now True when getting the banner
        resp = await client.get(f"/api/banners/{guid}", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json()["is_dismissed"] is True

    async def test_dismiss_nonexistent_banner(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/banners/{uuid.uuid4()}/dismiss", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_dismiss_banner_unauthenticated(self, client: AsyncClient):
        resp = await client.post(f"/api/banners/{uuid.uuid4()}/dismiss")
        assert resp.status_code == 401


class TestActiveBanners:
    async def test_get_active_banners(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/banners/active", headers=user_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_active_banners_returns_non_dismissed(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        """Active endpoint returns only non-dismissed banners with is_dismissed=False."""
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "Active1", "message": "Msg", "banner_type": "info", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        resp = await client.get("/api/banners/active", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        for banner in data:
            assert banner["is_dismissed"] is False

    async def test_get_active_banners_excludes_dismissed(
        self, client: AsyncClient, test_superuser, test_user, user_headers, admin_headers
    ):
        """Dismissed banner should not appear in active list."""
        create_resp = await client.post(
            "/api/banners",
            headers=admin_headers,
            json={"title": "ToBeDismissed", "message": "X", "banner_type": "info", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        # Dismiss it
        await client.post(f"/api/banners/{guid}/dismiss", headers=user_headers)

        resp = await client.get("/api/banners/active", headers=user_headers)
        assert resp.status_code == 200
        guids = [b["guid"] for b in resp.json()]
        assert guid not in guids

    async def test_get_active_banners_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/banners/active")
        assert resp.status_code == 401
