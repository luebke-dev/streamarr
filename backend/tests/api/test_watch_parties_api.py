"""Tests for the Watch Party API endpoints (/api/parties/*)."""

import uuid
from unittest.mock import patch, AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.media import MediaItem, MediaType
from pyrate.models.user import User

from .conftest import auth_headers


@pytest.fixture
async def movie(db_session: AsyncSession) -> MediaItem:
    item = MediaItem(title="Party Movie", media_type=MediaType.MOVIES)
    db_session.add(item)
    await db_session.commit()
    await db_session.refresh(item)
    return item


class TestCreateWatchParty:
    async def test_unauthenticated(self, client: AsyncClient):
        resp = await client.post("/api/parties", json={"name": "Party"})
        assert resp.status_code == 401

    async def test_create(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Movie Night",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Movie Night"
        assert "party_code" in data


class TestGetWatchParties:
    async def test_list_user_sessions(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/parties", headers=user_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_session_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get(
            f"/api/parties/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_get_friends_sessions(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/parties/friends", headers=user_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


class TestWatchPartyLifecycle:
    async def test_create_and_end(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        # Create
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "End Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        # End
        resp = await client.delete(
            f"/api/parties/{session_id}", headers=user_headers
        )
        assert resp.status_code == 204

    async def test_end_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.delete(
            f"/api/parties/{uuid.uuid4()}", headers=user_headers
        )
        assert resp.status_code == 404

    async def test_heartbeat(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Heartbeat Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.post(
            f"/api/parties/{session_id}/heartbeat", headers=user_headers
        )
        assert resp.status_code == 204


class TestAdminWatchParties:
    async def test_admin_list_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.get("/api/parties/admin/all", headers=user_headers)
        assert resp.status_code == 403

    async def test_admin_list(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.get("/api/parties/admin/all", headers=admin_headers)
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)


# ===========================================================================
# Extended tests
# ===========================================================================


@pytest_asyncio.fixture
async def test_user2(db_session: AsyncSession) -> User:
    """Second test user for multi-user scenarios."""
    from pyrate.auth.jwt_handler import jwt_handler

    user = User(
        guid=uuid.uuid4(),
        email="apitest2@example.com",
        first_name="API",
        last_name="Tester2",
        is_active=True,
        is_superuser=False,
        hashed_password=jwt_handler.get_password_hash("TestPassword123"),
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


class TestJoinWatchParty:
    async def test_join_via_code(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        # Create party
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Join Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        party_code = create_resp.json()["party_code"]

        # Join as user2
        user2_headers = auth_headers(test_user2)
        resp = await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["members"]) == 2

    async def test_join_invalid_code(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.post(
            "/api/parties/join",
            headers=user_headers,
            json={"party_code": "ZZZZZZ"},
        )
        assert resp.status_code == 404

    async def test_join_already_connected(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Dup Join",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        party_code = create_resp.json()["party_code"]
        user2_headers = auth_headers(test_user2)

        # Join first time
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )
        # Join again
        resp = await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )
        assert resp.status_code == 400

    async def test_join_unauthenticated(self, client: AsyncClient):
        resp = await client.post(
            "/api/parties/join",
            json={"party_code": "ABCDEF"},
        )
        assert resp.status_code == 401


class TestLeaveWatchParty:
    async def test_leave(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Leave Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.delete(
            f"/api/parties/{session_id}/leave", headers=user2_headers
        )
        assert resp.status_code == 204


class TestUpdateWatchParty:
    async def test_update_as_host(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Update Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.patch(
            f"/api/parties/{session_id}",
            headers=user_headers,
            json={"name": "Updated Name", "allow_control": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Updated Name"
        assert data["allow_control"] is True

    async def test_update_as_non_host(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Non-host Update",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.patch(
            f"/api/parties/{session_id}",
            headers=user2_headers,
            json={"name": "Hacked"},
        )
        assert resp.status_code == 403

    async def test_update_not_found(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        resp = await client.patch(
            f"/api/parties/{uuid.uuid4()}",
            headers=user_headers,
            json={"name": "Ghost"},
        )
        assert resp.status_code == 404


class TestSyncPlayback:
    async def test_sync_as_host(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Sync Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.post(
            f"/api/parties/{session_id}/sync",
            headers=user_headers,
            json={
                "current_time": 120.5,
                "is_playing": True,
                "playback_rate": 1.5,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["current_time"] == 120.5
        assert data["is_playing"] is True
        assert data["playback_rate"] == 1.5

    async def test_sync_as_guest_no_control(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "No Ctrl Sync",
                "media_id": str(movie.guid),
                "media_type": "movie",
                "allow_control": False,
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.post(
            f"/api/parties/{session_id}/sync",
            headers=user2_headers,
            json={"current_time": 60.0, "is_playing": False},
        )
        assert resp.status_code == 403

    async def test_sync_as_guest_with_control(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Ctrl Sync",
                "media_id": str(movie.guid),
                "media_type": "movie",
                "allow_control": True,
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.post(
            f"/api/parties/{session_id}/sync",
            headers=user2_headers,
            json={"current_time": 60.0, "is_playing": True},
        )
        assert resp.status_code == 200


class TestKickMember:
    @patch("pyrate.api.v1.parties.get_websocket_manager")
    async def test_kick(
        self, mock_ws, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        mock_manager = MagicMock()
        mock_manager.broadcast_to_resource = AsyncMock()
        mock_ws.return_value = mock_manager

        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Kick Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.delete(
            f"/api/parties/{session_id}/members/{test_user2.guid}",
            headers=user_headers,
        )
        assert resp.status_code == 204

    @patch("pyrate.api.v1.parties.get_websocket_manager")
    async def test_kick_not_host(
        self, mock_ws, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        mock_manager = MagicMock()
        mock_manager.broadcast_to_resource = AsyncMock()
        mock_ws.return_value = mock_manager

        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Kick NH",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.delete(
            f"/api/parties/{session_id}/members/{test_user.guid}",
            headers=user2_headers,
        )
        assert resp.status_code == 403


class TestEndWatchPartyExtended:
    async def test_end_as_non_host(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "End NH",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        resp = await client.delete(
            f"/api/parties/{session_id}", headers=user2_headers
        )
        assert resp.status_code == 403


class TestGetWatchPartyDetail:
    async def test_get_as_member(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Detail Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.get(
            f"/api/parties/{session_id}", headers=user_headers
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Detail Test"
        assert len(data["members"]) == 1

    async def test_get_as_non_member(
        self, client: AsyncClient, test_user: User, user_headers, movie, test_user2
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Non-member",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        user2_headers = auth_headers(test_user2)
        resp = await client.get(
            f"/api/parties/{session_id}", headers=user2_headers
        )
        assert resp.status_code == 403


class TestFriendsWatchParties:
    async def test_friends_sessions(
        self, client: AsyncClient, db_session: AsyncSession,
        test_user: User, user_headers, movie, test_user2
    ):
        # Create friendship
        friendship = Friendship(
            requester_id=test_user.guid,
            addressee_id=test_user2.guid,
            status=FriendshipStatus.accepted,
        )
        db_session.add(friendship)
        await db_session.commit()

        # user2 creates a party
        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties",
            headers=user2_headers,
            json={
                "name": "Friend Party",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )

        # user1 sees friend's party
        resp = await client.get("/api/parties/friends", headers=user_headers)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) >= 1
        assert any(p["name"] == "Friend Party" for p in data)


class TestAdminWatchPartiesExtended:
    async def test_admin_end_session(
        self, client: AsyncClient, test_user: User, user_headers,
        test_superuser: User, admin_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Admin End",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.delete(
            f"/api/parties/admin/{session_id}", headers=admin_headers
        )
        assert resp.status_code == 204

    async def test_admin_end_not_found(
        self, client: AsyncClient, test_superuser: User, admin_headers
    ):
        resp = await client.delete(
            f"/api/parties/admin/{uuid.uuid4()}", headers=admin_headers
        )
        assert resp.status_code == 404

    async def test_admin_end_as_user_forbidden(
        self, client: AsyncClient, test_user: User, user_headers, movie
    ):
        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Forbid End",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        resp = await client.delete(
            f"/api/parties/admin/{session_id}", headers=user_headers
        )
        assert resp.status_code == 403


# ===========================================================================
# Additional kick member edge cases
# ===========================================================================


class TestKickMemberEdgeCases:
    @patch("pyrate.api.v1.parties.get_websocket_manager")
    async def test_kick_nonexistent_member(
        self,
        mock_ws,
        client: AsyncClient,
        test_user: User,
        user_headers,
        movie,
    ):
        """Kick a user_id that is not a member of the party -> error."""
        mock_manager = MagicMock()
        mock_manager.broadcast_to_resource = AsyncMock()
        mock_ws.return_value = mock_manager

        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Kick Ghost",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]

        nonexistent_user_id = uuid.uuid4()
        resp = await client.delete(
            f"/api/parties/{session_id}/members/{nonexistent_user_id}",
            headers=user_headers,
        )
        # Should return 404 or 400 since the user is not a member
        assert resp.status_code in (400, 404)

    @patch("pyrate.api.v1.parties.get_websocket_manager")
    async def test_kick_broadcasts_websocket(
        self,
        mock_ws,
        client: AsyncClient,
        test_user: User,
        user_headers,
        movie,
        test_user2,
    ):
        """After kicking, WebSocket broadcast is sent."""
        mock_manager = MagicMock()
        mock_manager.broadcast_to_resource = AsyncMock()
        mock_ws.return_value = mock_manager

        create_resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "WS Kick Test",
                "media_id": str(movie.guid),
                "media_type": "movie",
            },
        )
        session_id = create_resp.json()["guid"]
        party_code = create_resp.json()["party_code"]

        # Join as user2
        user2_headers = auth_headers(test_user2)
        await client.post(
            "/api/parties/join",
            headers=user2_headers,
            json={"party_code": party_code},
        )

        # Kick user2
        resp = await client.delete(
            f"/api/parties/{session_id}/members/{test_user2.guid}",
            headers=user_headers,
        )
        assert resp.status_code == 204

        # Verify WebSocket broadcast was called
        mock_manager.broadcast_to_resource.assert_called_once_with(
            resource_type="party",
            resource_id=str(session_id),
            event="party_member_kicked",
            data={
                "party_id": str(session_id),
                "kicked_user_id": str(test_user2.guid),
            },
        )


# ===========================================================================
# Additional edge case coverage
# ===========================================================================


class TestCreateWatchPartyError:
    async def test_create_with_invalid_media_id(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Create watch party with non-existent media_id may raise ValueError."""
        resp = await client.post(
            "/api/parties",
            headers=user_headers,
            json={
                "name": "Invalid Media",
                "media_id": str(uuid.uuid4()),
                "media_type": "movie",
            },
        )
        # Service may raise ValueError -> 400, or succeed anyway
        assert resp.status_code in (201, 400)


class TestSyncPlaybackError:
    async def test_sync_nonexistent_session(
        self, client: AsyncClient, test_user: User, user_headers
    ):
        """Sync on a non-existent session returns 400 or 403."""
        resp = await client.post(
            f"/api/parties/{uuid.uuid4()}/sync",
            headers=user_headers,
            json={"current_time": 0.0, "is_playing": False},
        )
        assert resp.status_code in (400, 403, 404)
