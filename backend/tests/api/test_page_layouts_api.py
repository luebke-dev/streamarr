"""Tests for the Page Layout API endpoints (/api/page-layouts/*)."""

import uuid

from httpx import AsyncClient

from streamarr.models.user import User


class TestPublicLayoutEndpoints:
    async def test_get_layout_by_slug_unauthenticated(self, client: AsyncClient):
        resp = await client.get("/api/page-layouts/slug/home")
        assert resp.status_code == 401

    async def test_get_layout_by_slug_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            "/api/page-layouts/slug/nonexistent", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_layout_for_library_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/page-layouts/library/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404


class TestAdminLayoutEndpoints:
    async def test_list_layouts_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/page-layouts", headers=user_headers)
        assert resp.status_code == 403

    async def test_list_layouts_as_admin(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/page-layouts", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_create_layout(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Test Layout",
                "slug": "test-layout",
                "is_active": True,
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Test Layout"
        assert data["slug"] == "test-layout"

    async def test_get_layout_by_guid(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        create_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={"name": "Detail Layout", "slug": "detail-layout", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        resp = await client.get(f"/api/page-layouts/{guid}", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json()["guid"] == guid

    async def test_update_layout(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        create_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={"name": "Old Name", "slug": "old-slug", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        resp = await client.put(
            f"/api/page-layouts/{guid}",
            headers=admin_headers,
            json={"name": "New Name"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"

    async def test_delete_layout(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        create_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={"name": "Delete Me", "slug": "delete-me", "is_active": True},
        )
        guid = create_resp.json()["guid"]

        resp = await client.delete(f"/api/page-layouts/{guid}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_delete_layout_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.delete(
            f"/api/page-layouts/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404


class TestSectionManagement:
    async def test_add_and_delete_section(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        # Create layout
        layout_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={"name": "Section Layout", "slug": "section-layout", "is_active": True},
        )
        layout_guid = layout_resp.json()["guid"]

        # Add section
        section_resp = await client.post(
            f"/api/page-layouts/{layout_guid}/sections",
            headers=admin_headers,
            json={
                "section_type": "continue_watching",
                "order_index": 0,
                "title": "Continue Watching",
                "is_enabled": True,
            },
        )
        assert section_resp.status_code == 201
        section_guid = section_resp.json()["guid"]

        # Delete section
        resp = await client.delete(
            f"/api/page-layouts/{layout_guid}/sections/{section_guid}",
            headers=admin_headers,
        )
        assert resp.status_code == 204

    async def test_add_latest_items_section(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        layout_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={"name": "Latest Layout", "slug": "latest-layout", "is_active": True},
        )
        layout_guid = layout_resp.json()["guid"]

        resp = await client.post(
            f"/api/page-layouts/{layout_guid}/sections",
            headers=admin_headers,
            json={
                "section_type": "latest_items",
                "order_index": 0,
                "title": "Recently Added",
                "config": {"max_items": 12},
                "is_enabled": True,
            },
        )

        assert resp.status_code == 201
        data = resp.json()
        assert data["section_type"] == "latest_items"
        assert data["config"]["max_items"] == 12


# ===========================================================================
# Additional coverage tests
# ===========================================================================


class TestReorderSections:
    async def test_reorder_sections_success(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /page-layouts/{layout_guid}/sections-order - successful reorder."""
        # Create layout
        layout_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Reorder Layout",
                "slug": "reorder-layout",
                "is_active": True,
            },
        )
        layout_guid = layout_resp.json()["guid"]

        # Add two sections
        s1_resp = await client.post(
            f"/api/page-layouts/{layout_guid}/sections",
            headers=admin_headers,
            json={
                "section_type": "continue_watching",
                "order_index": 0,
                "title": "Section A",
                "is_enabled": True,
            },
        )
        s1_guid = s1_resp.json()["guid"]

        s2_resp = await client.post(
            f"/api/page-layouts/{layout_guid}/sections",
            headers=admin_headers,
            json={
                "section_type": "favorites",
                "order_index": 1,
                "title": "Section B",
                "is_enabled": True,
            },
        )
        s2_guid = s2_resp.json()["guid"]

        # Reorder: B first, A second
        resp = await client.put(
            f"/api/page-layouts/{layout_guid}/sections-order",
            headers=admin_headers,
            json={"section_order": [s2_guid, s1_guid]},
        )
        assert resp.status_code == 200

    async def test_reorder_sections_layout_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /page-layouts/{layout_guid}/sections-order - 404 for invalid layout."""
        resp = await client.put(
            f"/api/page-layouts/{uuid.uuid4()}/sections-order",
            headers=admin_headers,
            json={"section_order": []},
        )
        assert resp.status_code == 404


class TestGetLayoutBySlugSuccess:
    async def test_get_layout_by_slug_found(
        self, client: AsyncClient, test_user: User, test_superuser: User,
        user_headers, admin_headers
    ):
        """GET /page-layouts/slug/{slug} - success case with actual layout."""
        # Create layout as admin
        await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Home Layout",
                "slug": "home-test",
                "is_active": True,
            },
        )

        # Access as regular user
        resp = await client.get(
            "/api/page-layouts/slug/home-test", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["slug"] == "home-test"
        assert data["name"] == "Home Layout"


class TestGetLayoutForLibrary:
    async def test_get_layout_for_library_success(
        self, client: AsyncClient, test_user: User, test_superuser: User,
        user_headers, admin_headers
    ):
        """GET /page-layouts/library/{library_guid} - success with actual layout."""
        library_guid = str(uuid.uuid4())

        # Create layout bound to a library
        await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Library Layout",
                "slug": f"lib-{library_guid[:8]}",
                "is_active": True,
                "library_guid": library_guid,
            },
        )

        resp = await client.get(
            f"/api/page-layouts/library/{library_guid}", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Library Layout"


class TestUpdateSection:
    async def test_update_section_success(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /page-layouts/{layout_guid}/sections/{section_guid} - success."""
        # Create layout
        layout_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Update Section Layout",
                "slug": "update-section-layout",
                "is_active": True,
            },
        )
        layout_guid = layout_resp.json()["guid"]

        # Add section
        section_resp = await client.post(
            f"/api/page-layouts/{layout_guid}/sections",
            headers=admin_headers,
            json={
                "section_type": "continue_watching",
                "order_index": 0,
                "title": "Original Title",
                "is_enabled": True,
            },
        )
        section_guid = section_resp.json()["guid"]

        # Update section
        resp = await client.put(
            f"/api/page-layouts/{layout_guid}/sections/{section_guid}",
            headers=admin_headers,
            json={
                "title": "Updated Title",
                "order_index": 1,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Updated Title"

    async def test_update_section_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /page-layouts/{layout_guid}/sections/{section_guid} - 404."""
        layout_resp = await client.post(
            "/api/page-layouts",
            headers=admin_headers,
            json={
                "name": "Sec Not Found Layout",
                "slug": "sec-nf-layout",
                "is_active": True,
            },
        )
        layout_guid = layout_resp.json()["guid"]

        resp = await client.put(
            f"/api/page-layouts/{layout_guid}/sections/{uuid.uuid4()}",
            headers=admin_headers,
            json={"title": "Ghost"},
        )
        assert resp.status_code == 404


class TestGetLayoutNotFound:
    async def test_get_layout_guid_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """GET /page-layouts/{layout_guid} - 404 for nonexistent GUID."""
        resp = await client.get(
            f"/api/page-layouts/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_update_layout_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """PUT /page-layouts/{layout_guid} - 404 for nonexistent GUID."""
        resp = await client.put(
            f"/api/page-layouts/{uuid.uuid4()}",
            headers=admin_headers,
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404


class TestAddSectionLayoutNotFound:
    async def test_add_section_to_nonexistent_layout(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        """POST /page-layouts/{layout_guid}/sections - 404 for nonexistent layout."""
        resp = await client.post(
            f"/api/page-layouts/{uuid.uuid4()}/sections",
            headers=admin_headers,
            json={
                "section_type": "continue_watching",
                "order_index": 0,
                "title": "Orphan Section",
                "is_enabled": True,
            },
        )
        assert resp.status_code == 404
