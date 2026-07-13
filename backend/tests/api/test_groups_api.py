"""Tests for groups API endpoints (/api/groups/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.group import Group
from streamarr.models.user import User


# ---------------------------------------------------------------------------
# POST /api/groups
# ---------------------------------------------------------------------------
class TestCreateGroup:
    async def test_create_group_admin(self, client: AsyncClient, admin_headers):
        resp = await client.post(
            "/api/groups",
            json={
                "name": "Premium Users",
                "description": "Premium tier group",
                "max_concurrent_streams": 4,
                "max_video_quality": "uhd",
            },
            headers=admin_headers,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Premium Users"
        assert data["max_concurrent_streams"] == 4
        assert data["member_count"] == 0

    async def test_create_group_duplicate_name(self, client: AsyncClient, db_session, admin_headers):
        group = Group(
            guid=uuid.uuid4(),
            name="Existing Group",
        )
        db_session.add(group)
        await db_session.commit()

        resp = await client.post(
            "/api/groups",
            json={"name": "Existing Group"},
            headers=admin_headers,
        )
        assert resp.status_code == 400

    async def test_create_group_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.post(
            "/api/groups",
            json={"name": "Test"},
            headers=user_headers,
        )
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/groups
# ---------------------------------------------------------------------------
class TestListGroups:
    async def test_list_groups_empty(self, client: AsyncClient, admin_headers):
        resp = await client.get("/api/groups", headers=admin_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_groups(self, client: AsyncClient, db_session, admin_headers):
        g1 = Group(guid=uuid.uuid4(), name="Group A")
        g2 = Group(guid=uuid.uuid4(), name="Group B")
        db_session.add_all([g1, g2])
        await db_session.commit()

        resp = await client.get("/api/groups", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_list_groups_regular_user_forbidden(self, client: AsyncClient, user_headers):
        resp = await client.get("/api/groups", headers=user_headers)
        assert resp.status_code == 403


# ---------------------------------------------------------------------------
# GET /api/groups/{group_id}
# ---------------------------------------------------------------------------
class TestGetGroup:
    async def test_get_group(self, client: AsyncClient, db_session, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Test Group")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        resp = await client.get(f"/api/groups/{group.guid}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Group"
        assert "member_ids" in data

    async def test_get_group_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.get(f"/api/groups/{fake}", headers=admin_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /api/groups/{group_id}
# ---------------------------------------------------------------------------
class TestUpdateGroup:
    async def test_update_group(self, client: AsyncClient, db_session, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Old Name")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        resp = await client.patch(
            f"/api/groups/{group.guid}",
            json={"name": "New Name", "max_concurrent_streams": 10},
            headers=admin_headers,
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["max_concurrent_streams"] == 10

    async def test_update_group_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.patch(
            f"/api/groups/{fake}",
            json={"name": "Updated"},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_update_group_name_conflict(
        self, client: AsyncClient, db_session, admin_headers
    ):
        """Updating a group to use an existing name from a DIFFERENT group returns 400."""
        group_a = Group(guid=uuid.uuid4(), name="Group Alpha")
        group_b = Group(guid=uuid.uuid4(), name="Group Beta")
        db_session.add_all([group_a, group_b])
        await db_session.commit()
        await db_session.refresh(group_a)
        await db_session.refresh(group_b)

        resp = await client.patch(
            f"/api/groups/{group_b.guid}",
            json={"name": "Group Alpha"},
            headers=admin_headers,
        )
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# DELETE /api/groups/{group_id}
# ---------------------------------------------------------------------------
class TestDeleteGroup:
    async def test_delete_group(self, client: AsyncClient, db_session, admin_headers):
        group = Group(guid=uuid.uuid4(), name="To Delete")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        resp = await client.delete(f"/api/groups/{group.guid}", headers=admin_headers)
        assert resp.status_code == 204

    async def test_delete_group_not_found(self, client: AsyncClient, admin_headers):
        fake = uuid.uuid4()
        resp = await client.delete(f"/api/groups/{fake}", headers=admin_headers)
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# User-group assignment endpoints
# ---------------------------------------------------------------------------
class TestUserGroupAssignment:
    async def test_assign_user_to_group(self, client: AsyncClient, db_session, test_user, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Assign Group")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        resp = await client.post(
            "/api/groups/assign",
            json={"user_id": str(test_user.guid), "group_id": str(group.guid)},
            headers=admin_headers,
        )
        assert resp.status_code == 204

    async def test_assign_to_nonexistent_group(self, client: AsyncClient, test_user, admin_headers):
        fake = uuid.uuid4()
        resp = await client.post(
            "/api/groups/assign",
            json={"user_id": str(test_user.guid), "group_id": str(fake)},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_bulk_assign(self, client: AsyncClient, db_session, test_user, test_superuser, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Bulk Group")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        resp = await client.post(
            "/api/groups/assign/bulk",
            json={
                "user_ids": [str(test_user.guid), str(test_superuser.guid)],
                "group_id": str(group.guid),
            },
            headers=admin_headers,
        )
        assert resp.status_code == 204

    async def test_bulk_assign_nonexistent_group(
        self, client: AsyncClient, test_user, admin_headers
    ):
        """Bulk-assigning to a non-existent group returns 404."""
        fake = uuid.uuid4()
        resp = await client.post(
            "/api/groups/assign/bulk",
            json={"user_ids": [str(test_user.guid)], "group_id": str(fake)},
            headers=admin_headers,
        )
        assert resp.status_code == 404

    async def test_remove_user_from_group(self, client: AsyncClient, db_session, test_user, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Remove Group")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        # Assign first
        await client.post(
            "/api/groups/assign",
            json={"user_id": str(test_user.guid), "group_id": str(group.guid)},
            headers=admin_headers,
        )

        # Then remove — httpx DELETE with json body needs explicit content + header
        import json as json_mod

        body = json_mod.dumps({"user_id": str(test_user.guid), "group_id": str(group.guid)})
        headers = {**admin_headers, "Content-Type": "application/json"}
        resp = await client.request(
            "DELETE",
            "/api/groups/assign",
            content=body,
            headers=headers,
        )
        assert resp.status_code == 204

    async def test_remove_user_not_in_group(
        self, client: AsyncClient, db_session, test_user, admin_headers
    ):
        """Removing a user who isn't in the group returns 404."""
        group = Group(guid=uuid.uuid4(), name="Non-Member Group")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        import json as json_mod

        body = json_mod.dumps(
            {"user_id": str(test_user.guid), "group_id": str(group.guid)}
        )
        headers = {**admin_headers, "Content-Type": "application/json"}
        resp = await client.request(
            "DELETE", "/api/groups/assign", content=body, headers=headers
        )
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# User group queries
# ---------------------------------------------------------------------------
class TestUserGroups:
    async def test_get_user_groups(self, client: AsyncClient, db_session, test_user, admin_headers):
        group = Group(guid=uuid.uuid4(), name="Membership")
        db_session.add(group)
        await db_session.commit()
        await db_session.refresh(group)

        await client.post(
            "/api/groups/assign",
            json={"user_id": str(test_user.guid), "group_id": str(group.guid)},
            headers=admin_headers,
        )

        resp = await client.get(f"/api/groups/user/{test_user.guid}", headers=admin_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert str(group.guid) in data["group_ids"]

    async def test_get_own_groups(self, client: AsyncClient, test_user, user_headers):
        resp = await client.get(f"/api/groups/user/{test_user.guid}", headers=user_headers)
        assert resp.status_code == 200

    async def test_get_other_user_groups_forbidden(self, client: AsyncClient, test_superuser, user_headers):
        resp = await client.get(f"/api/groups/user/{test_superuser.guid}", headers=user_headers)
        assert resp.status_code == 403

    async def test_get_user_permissions(self, client: AsyncClient, test_user, user_headers):
        resp = await client.get(f"/api/groups/user/{test_user.guid}/permissions", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert "max_concurrent_streams" in data
        assert "allowed_libraries" in data

    async def test_get_user_groups_nonexistent_user(
        self, client: AsyncClient, admin_headers
    ):
        """Querying groups for a non-existent user returns 404."""
        resp = await client.get(
            f"/api/groups/user/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_get_other_user_permissions_forbidden(
        self, client: AsyncClient, test_superuser, user_headers
    ):
        """Regular user cannot view another user's permissions."""
        resp = await client.get(
            f"/api/groups/user/{test_superuser.guid}/permissions", headers=user_headers
        )
        assert resp.status_code == 403
