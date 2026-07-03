"""Tests for FriendshipService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.user import User
from pyrate.services.friendship import FriendshipService


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


async def _make_user(db: AsyncSession, email: str) -> User:
    """Helper: create and persist a user."""
    user = User(
        guid=uuid.uuid4(),
        email=email,
        first_name="Test",
        last_name="User",
        is_active=True,
        is_superuser=False,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# send_request
# ---------------------------------------------------------------------------


class TestSendRequest:
    """Tests for FriendshipService.send_request()."""

    @pytest.mark.asyncio
    async def test_send_request_success(self, db_session: AsyncSession):
        """A pending friendship is created between two distinct users."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice@example.com")
        bob = await _make_user(db_session, "bob@example.com")

        friendship = await svc.send_request(alice.guid, bob.email)

        assert friendship is not None
        assert friendship.requester_id == alice.guid
        assert friendship.addressee_id == bob.guid
        assert friendship.status == FriendshipStatus.pending

    @pytest.mark.asyncio
    async def test_send_request_user_not_found(self, db_session: AsyncSession):
        """Sending to an unknown e-mail raises ValueError('no_user')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice2@example.com")

        with pytest.raises(ValueError, match="no_user"):
            await svc.send_request(alice.guid, "nobody@nowhere.com")

    @pytest.mark.asyncio
    async def test_send_request_to_self(self, db_session: AsyncSession):
        """Sending a request to yourself raises ValueError('self_request')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice3@example.com")

        with pytest.raises(ValueError, match="self_request"):
            await svc.send_request(alice.guid, alice.email)

    @pytest.mark.asyncio
    async def test_send_request_already_pending(self, db_session: AsyncSession):
        """A duplicate pending request raises ValueError('already_pending')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice4@example.com")
        bob = await _make_user(db_session, "bob4@example.com")

        await svc.send_request(alice.guid, bob.email)

        with pytest.raises(ValueError, match="already_pending"):
            await svc.send_request(alice.guid, bob.email)

    @pytest.mark.asyncio
    async def test_send_request_already_friends(self, db_session: AsyncSession):
        """Sending a request to an existing friend raises ValueError('already_friends')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice5@example.com")
        bob = await _make_user(db_session, "bob5@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)

        with pytest.raises(ValueError, match="already_friends"):
            await svc.send_request(alice.guid, bob.email)

    @pytest.mark.asyncio
    async def test_send_request_reverse_direction_while_pending(self, db_session: AsyncSession):
        """Sending in reverse direction while a pending request exists raises ValueError('already_pending')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice6@example.com")
        bob = await _make_user(db_session, "bob6@example.com")

        # Alice sends to Bob
        await svc.send_request(alice.guid, bob.email)

        # Bob tries to send to Alice — same pair, blocked
        with pytest.raises(ValueError, match="already_pending"):
            await svc.send_request(bob.guid, alice.email)


# ---------------------------------------------------------------------------
# accept
# ---------------------------------------------------------------------------


class TestAccept:
    """Tests for FriendshipService.accept()."""

    @pytest.mark.asyncio
    async def test_accept_pending_request(self, db_session: AsyncSession):
        """Addressee can accept a pending request."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_a@example.com")
        bob = await _make_user(db_session, "bob_a@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        accepted = await svc.accept(fs.guid, bob.guid)

        assert accepted.status == FriendshipStatus.accepted

    @pytest.mark.asyncio
    async def test_accept_wrong_user_raises(self, db_session: AsyncSession):
        """A third party cannot accept the request."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_b@example.com")
        bob = await _make_user(db_session, "bob_b@example.com")
        carol = await _make_user(db_session, "carol_b@example.com")

        fs = await svc.send_request(alice.guid, bob.email)

        with pytest.raises(ValueError, match="not_found"):
            await svc.accept(fs.guid, carol.guid)

    @pytest.mark.asyncio
    async def test_accept_nonexistent_raises(self, db_session: AsyncSession):
        """Accepting a nonexistent friendship raises ValueError('not_found')."""
        svc = FriendshipService(db_session)
        bob = await _make_user(db_session, "bob_c@example.com")

        with pytest.raises(ValueError, match="not_found"):
            await svc.accept(uuid.uuid4(), bob.guid)

    @pytest.mark.asyncio
    async def test_accept_already_accepted_raises(self, db_session: AsyncSession):
        """Accepting an already-accepted friendship raises ValueError('not_pending')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_d@example.com")
        bob = await _make_user(db_session, "bob_d@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)

        with pytest.raises(ValueError, match="not_pending"):
            await svc.accept(fs.guid, bob.guid)


# ---------------------------------------------------------------------------
# reject
# ---------------------------------------------------------------------------


class TestReject:
    """Tests for FriendshipService.reject()."""

    @pytest.mark.asyncio
    async def test_reject_pending_request(self, db_session: AsyncSession):
        """Addressee can reject (delete) a pending request."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_r@example.com")
        bob = await _make_user(db_session, "bob_r@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        result = await svc.reject(fs.guid, bob.guid)

        assert result is True
        # Friendship should be gone
        reloaded = await svc._load(fs.guid)
        assert reloaded is None

    @pytest.mark.asyncio
    async def test_reject_wrong_user_raises(self, db_session: AsyncSession):
        """Only the addressee may reject the request."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_r2@example.com")
        bob = await _make_user(db_session, "bob_r2@example.com")

        fs = await svc.send_request(alice.guid, bob.email)

        with pytest.raises(ValueError, match="not_found"):
            await svc.reject(fs.guid, alice.guid)  # requester, not addressee

    @pytest.mark.asyncio
    async def test_reject_already_accepted_raises(self, db_session: AsyncSession):
        """Rejecting an accepted friendship raises ValueError('not_pending')."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_r3@example.com")
        bob = await _make_user(db_session, "bob_r3@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)

        with pytest.raises(ValueError, match="not_pending"):
            await svc.reject(fs.guid, bob.guid)


# ---------------------------------------------------------------------------
# remove
# ---------------------------------------------------------------------------


class TestRemove:
    """Tests for FriendshipService.remove()."""

    @pytest.mark.asyncio
    async def test_requester_can_remove(self, db_session: AsyncSession):
        """The original requester can remove an accepted friendship."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_rm@example.com")
        bob = await _make_user(db_session, "bob_rm@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)
        result = await svc.remove(fs.guid, alice.guid)

        assert result is True
        assert await svc._load(fs.guid) is None

    @pytest.mark.asyncio
    async def test_addressee_can_remove(self, db_session: AsyncSession):
        """The addressee can also remove an accepted friendship."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_rm2@example.com")
        bob = await _make_user(db_session, "bob_rm2@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)
        result = await svc.remove(fs.guid, bob.guid)

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises(self, db_session: AsyncSession):
        """Removing a nonexistent friendship raises ValueError('not_found')."""
        svc = FriendshipService(db_session)
        user = await _make_user(db_session, "user_rm@example.com")

        with pytest.raises(ValueError, match="not_found"):
            await svc.remove(uuid.uuid4(), user.guid)

    @pytest.mark.asyncio
    async def test_remove_non_participant_raises(self, db_session: AsyncSession):
        """A user not involved in the friendship cannot remove it."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_rm3@example.com")
        bob = await _make_user(db_session, "bob_rm3@example.com")
        carol = await _make_user(db_session, "carol_rm3@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)

        with pytest.raises(ValueError, match="not_found"):
            await svc.remove(fs.guid, carol.guid)


# ---------------------------------------------------------------------------
# get_friends / get_pending
# ---------------------------------------------------------------------------


class TestGetFriends:
    """Tests for get_friends, get_pending_received, get_pending_sent."""

    @pytest.mark.asyncio
    async def test_get_friends_returns_accepted_only(self, db_session: AsyncSession):
        """get_friends returns only accepted friendships."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_gf@example.com")
        bob = await _make_user(db_session, "bob_gf@example.com")
        carol = await _make_user(db_session, "carol_gf@example.com")

        # Accept with bob
        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)
        # Leave carol pending
        await svc.send_request(alice.guid, carol.email)

        friends = await svc.get_friends(alice.guid)
        assert len(friends) == 1
        guids = {f.requester_id for f in friends} | {f.addressee_id for f in friends}
        assert bob.guid in guids

    @pytest.mark.asyncio
    async def test_get_friends_empty(self, db_session: AsyncSession):
        """get_friends returns empty list for a user with no accepted friendships."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_gf2@example.com")

        friends = await svc.get_friends(alice.guid)
        assert friends == []

    @pytest.mark.asyncio
    async def test_get_pending_received(self, db_session: AsyncSession):
        """get_pending_received returns requests where user is the addressee."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_pr@example.com")
        bob = await _make_user(db_session, "bob_pr@example.com")

        await svc.send_request(alice.guid, bob.email)

        received = await svc.get_pending_received(bob.guid)
        assert len(received) == 1
        assert received[0].requester_id == alice.guid

    @pytest.mark.asyncio
    async def test_get_pending_sent(self, db_session: AsyncSession):
        """get_pending_sent returns requests where user is the requester."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_ps@example.com")
        bob = await _make_user(db_session, "bob_ps@example.com")

        await svc.send_request(alice.guid, bob.email)

        sent = await svc.get_pending_sent(alice.guid)
        assert len(sent) == 1
        assert sent[0].addressee_id == bob.guid

    @pytest.mark.asyncio
    async def test_get_pending_sent_empty_after_accept(self, db_session: AsyncSession):
        """get_pending_sent is empty once the request has been accepted."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_ps2@example.com")
        bob = await _make_user(db_session, "bob_ps2@example.com")

        fs = await svc.send_request(alice.guid, bob.email)
        await svc.accept(fs.guid, bob.guid)

        sent = await svc.get_pending_sent(alice.guid)
        assert sent == []


# ---------------------------------------------------------------------------
# create_accepted
# ---------------------------------------------------------------------------


class TestCreateAccepted:
    """Tests for FriendshipService.create_accepted()."""

    @pytest.mark.asyncio
    async def test_creates_accepted_friendship(self, db_session: AsyncSession):
        """create_accepted directly creates an accepted friendship."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_ca@example.com")
        bob = await _make_user(db_session, "bob_ca@example.com")

        fs = await svc.create_accepted(alice.guid, bob.guid)

        assert fs.status == FriendshipStatus.accepted
        assert {fs.requester_id, fs.addressee_id} == {alice.guid, bob.guid}

    @pytest.mark.asyncio
    async def test_upgrades_pending_to_accepted(self, db_session: AsyncSession):
        """create_accepted upgrades an existing pending friendship to accepted."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_ca2@example.com")
        bob = await _make_user(db_session, "bob_ca2@example.com")

        # First create a pending relationship
        await svc.send_request(alice.guid, bob.email)

        # Now force-accept via create_accepted
        fs = await svc.create_accepted(alice.guid, bob.guid)
        assert fs.status == FriendshipStatus.accepted

    @pytest.mark.asyncio
    async def test_idempotent_if_already_accepted(self, db_session: AsyncSession):
        """create_accepted is idempotent - does not create duplicates."""
        svc = FriendshipService(db_session)
        alice = await _make_user(db_session, "alice_ca3@example.com")
        bob = await _make_user(db_session, "bob_ca3@example.com")

        fs1 = await svc.create_accepted(alice.guid, bob.guid)
        fs2 = await svc.create_accepted(alice.guid, bob.guid)

        assert fs1.guid == fs2.guid
        friends = await svc.get_friends(alice.guid)
        assert len(friends) == 1
