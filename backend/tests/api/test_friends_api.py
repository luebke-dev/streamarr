"""Tests for the Friends API endpoints (/api/friends/*)."""

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.auth.jwt_handler import jwt_handler
from pyrate.models.user import User

from .conftest import auth_headers


@pytest.fixture
async def friend_user(db_session: AsyncSession) -> User:
    """Create a second user that can serve as a friend."""
    user = User(
        guid=uuid.uuid4(),
        email="friend@example.com",
        first_name="Friend",
        last_name="User",
        is_active=True,
        is_superuser=False,
        hashed_password=jwt_handler.get_password_hash("FriendPass123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


class TestSendFriendRequest:
    async def test_send_request_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/friends/request", json={"email": "nobody@example.com"}
        )
        assert resp.status_code == 401

    async def test_send_request_to_existing_user(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        friend_user: User,
    ):
        resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": friend_user.email},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "pending"

    async def test_send_request_to_self(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": test_user.email},
        )
        assert resp.status_code == 400

    async def test_send_request_to_nonexistent_user(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": "ghost@example.com"},
        )
        assert resp.status_code == 404


class TestListFriends:
    async def test_list_friends_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/friends", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_pending_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/friends/pending", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []

    async def test_list_sent_empty(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/friends/sent", headers=user_headers)
        assert resp.status_code == 200
        assert resp.json() == []


class TestFriendRequestLifecycle:
    async def test_accept_request(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        friend_user: User,
    ):
        # Send request
        create_resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": friend_user.email},
        )
        friendship_id = create_resp.json()["guid"]

        # Accept as the addressee
        friend_headers = auth_headers(friend_user)
        resp = await client.post(
            f"/api/friends/{friendship_id}/accept", headers=friend_headers
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "accepted"

    async def test_reject_request(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        friend_user: User,
    ):
        create_resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": friend_user.email},
        )
        friendship_id = create_resp.json()["guid"]

        friend_headers = auth_headers(friend_user)
        resp = await client.post(
            f"/api/friends/{friendship_id}/reject", headers=friend_headers
        )
        assert resp.status_code == 204

    async def test_remove_friend(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        friend_user: User,
    ):
        # Create and accept
        create_resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": friend_user.email},
        )
        friendship_id = create_resp.json()["guid"]

        friend_headers = auth_headers(friend_user)
        await client.post(
            f"/api/friends/{friendship_id}/accept", headers=friend_headers
        )

        # Remove
        resp = await client.delete(
            f"/api/friends/{friendship_id}", headers=user_headers
        )
        assert resp.status_code == 204

    async def test_accept_nonexistent(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            f"/api/friends/{uuid.uuid4()}/accept", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_reject_nonexistent(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Rejecting a non-existent friendship returns 404."""
        resp = await client.post(
            f"/api/friends/{uuid.uuid4()}/reject", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_reject_not_pending(
        self,
        client: AsyncClient,
        test_user: User,
        user_headers,
        friend_user: User,
    ):
        """Rejecting an already-accepted request returns 404."""
        # Create and accept
        create_resp = await client.post(
            "/api/friends/request",
            headers=user_headers,
            json={"email": friend_user.email},
        )
        friendship_id = create_resp.json()["guid"]

        friend_headers = auth_headers(friend_user)
        await client.post(f"/api/friends/{friendship_id}/accept", headers=friend_headers)

        # Now reject the already-accepted friendship → not_pending
        resp = await client.post(
            f"/api/friends/{friendship_id}/reject", headers=friend_headers
        )
        assert resp.status_code == 404

    async def test_remove_nonexistent(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Removing a non-existent friendship returns 404."""
        resp = await client.delete(
            f"/api/friends/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404
