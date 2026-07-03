"""Tests for WatchParty models, data layer operations, and service methods."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.friendship import Friendship, FriendshipStatus
from pyrate.models.party import WatchParty, WatchPartyMember
from pyrate.models.user import User
from pyrate.schemas.party import PlaybackSync, WatchPartyCreate, WatchPartyUpdate
from pyrate.services.party import WatchPartyService


@pytest_asyncio.fixture
async def sample_party(db_session: AsyncSession, test_user: User) -> WatchParty:
    """Create a sample watch party."""
    party = WatchParty(
        guid=uuid.uuid4(),
        owner_id=test_user.guid,
        name="Movie Night",
        allow_control=False,
        is_active=True,
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    db_session.add(party)
    await db_session.commit()
    await db_session.refresh(party)
    return party


@pytest_asyncio.fixture
async def sample_member(
    db_session: AsyncSession, sample_party: WatchParty, test_user: User
) -> WatchPartyMember:
    """Create a sample watch party member (host)."""
    member = WatchPartyMember(
        guid=uuid.uuid4(),
        party_id=sample_party.guid,
        user_id=test_user.guid,
        is_host=True,
        is_connected=True,
    )
    db_session.add(member)
    await db_session.commit()
    await db_session.refresh(member)
    return member


class TestWatchPartyModel:
    """Tests for WatchParty model operations."""

    @pytest.mark.asyncio
    async def test_create_party(self, db_session: AsyncSession, test_user: User):
        """Test creating a watch party."""
        party = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="Test Party",
            allow_control=True,
            expires_at=datetime.now(UTC) + timedelta(hours=12),
        )
        db_session.add(party)
        await db_session.commit()
        await db_session.refresh(party)

        assert party.guid is not None
        assert party.name == "Test Party"
        assert party.owner_id == test_user.guid
        assert party.allow_control is True
        assert party.is_active is True
        assert party.party_code is not None
        assert len(party.party_code) == 6

    @pytest.mark.asyncio
    async def test_party_default_values(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test default values on a new party."""
        party = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db_session.add(party)
        await db_session.commit()
        await db_session.refresh(party)

        assert party.current_time == 0.0
        assert party.is_playing is False
        assert party.playback_rate == 1.0
        assert party.is_active is True
        assert party.allow_control is False

    @pytest.mark.asyncio
    async def test_get_party_by_code(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test finding a party by its code."""
        code = sample_party.party_code
        stmt = select(WatchParty).where(WatchParty.party_code == code)
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()

        assert found is not None
        assert found.guid == sample_party.guid

    @pytest.mark.asyncio
    async def test_get_party_by_code_not_found(self, db_session: AsyncSession):
        """Test that an invalid code returns None."""
        stmt = select(WatchParty).where(WatchParty.party_code == "ZZZZZZ")
        result = await db_session.execute(stmt)
        found = result.scalar_one_or_none()
        assert found is None

    @pytest.mark.asyncio
    async def test_end_party(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test ending a watch party."""
        sample_party.is_active = False
        sample_party.ended_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(sample_party)

        assert sample_party.is_active is False
        assert sample_party.ended_at is not None

    @pytest.mark.asyncio
    async def test_update_playback_state(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test updating playback state."""
        sample_party.current_time = 120.5
        sample_party.is_playing = True
        sample_party.playback_rate = 1.5
        sample_party.last_sync_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(sample_party)

        assert sample_party.current_time == 120.5
        assert sample_party.is_playing is True
        assert sample_party.playback_rate == 1.5

    @pytest.mark.asyncio
    async def test_update_media_info(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test setting media information on a party."""
        media_id = uuid.uuid4()
        sample_party.media_id = media_id
        sample_party.media_type = "movie"
        sample_party.media_title = "Inception"
        await db_session.commit()
        await db_session.refresh(sample_party)

        assert sample_party.media_id == media_id
        assert sample_party.media_type == "movie"
        assert sample_party.media_title == "Inception"

    @pytest.mark.asyncio
    async def test_query_active_parties(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test querying only active parties."""
        active = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="Active",
            is_active=True,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        inactive = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="Ended",
            is_active=False,
            ended_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db_session.add_all([active, inactive])
        await db_session.commit()

        stmt = select(WatchParty).where(WatchParty.is_active.is_(True))
        result = await db_session.execute(stmt)
        parties = result.scalars().all()

        names = [p.name for p in parties]
        assert "Active" in names
        assert "Ended" not in names

    @pytest.mark.asyncio
    async def test_query_parties_by_owner(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test querying parties by owner."""
        party1 = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="User1 Party",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        party2 = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user2.guid,
            name="User2 Party",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db_session.add_all([party1, party2])
        await db_session.commit()

        stmt = select(WatchParty).where(WatchParty.owner_id == test_user.guid)
        result = await db_session.execute(stmt)
        parties = list(result.scalars().all())

        assert len(parties) == 1
        assert parties[0].name == "User1 Party"

    @pytest.mark.asyncio
    async def test_unique_party_codes(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that each party gets a unique code."""
        codes = set()
        for _ in range(10):
            party = WatchParty(
                guid=uuid.uuid4(),
                owner_id=test_user.guid,
                expires_at=datetime.now(UTC) + timedelta(hours=24),
            )
            db_session.add(party)
            await db_session.flush()
            codes.add(party.party_code)

        await db_session.commit()
        assert len(codes) == 10


class TestWatchPartyMemberModel:
    """Tests for WatchPartyMember model operations."""

    @pytest.mark.asyncio
    async def test_add_member(
        self,
        db_session: AsyncSession,
        sample_party: WatchParty,
        test_user2: User,
    ):
        """Test adding a member to a party."""
        member = WatchPartyMember(
            guid=uuid.uuid4(),
            party_id=sample_party.guid,
            user_id=test_user2.guid,
            is_host=False,
            is_connected=True,
        )
        db_session.add(member)
        await db_session.commit()
        await db_session.refresh(member)

        assert member.party_id == sample_party.guid
        assert member.user_id == test_user2.guid
        assert member.is_host is False
        assert member.is_connected is True

    @pytest.mark.asyncio
    async def test_member_disconnect(
        self,
        db_session: AsyncSession,
        sample_member: WatchPartyMember,
    ):
        """Test disconnecting a member."""
        sample_member.is_connected = False
        sample_member.left_at = datetime.now(UTC)
        await db_session.commit()
        await db_session.refresh(sample_member)

        assert sample_member.is_connected is False
        assert sample_member.left_at is not None

    @pytest.mark.asyncio
    async def test_member_heartbeat(
        self,
        db_session: AsyncSession,
        sample_member: WatchPartyMember,
    ):
        """Test updating member heartbeat."""
        now = datetime.now(UTC)
        sample_member.last_heartbeat = now
        sample_member.last_position = 60.5
        await db_session.commit()
        await db_session.refresh(sample_member)

        assert sample_member.last_position == 60.5

    @pytest.mark.asyncio
    async def test_query_active_members(
        self,
        db_session: AsyncSession,
        sample_party: WatchParty,
        test_user: User,
        test_user2: User,
    ):
        """Test querying active (connected) members."""
        host = WatchPartyMember(
            guid=uuid.uuid4(),
            party_id=sample_party.guid,
            user_id=test_user.guid,
            is_host=True,
            is_connected=True,
        )
        guest = WatchPartyMember(
            guid=uuid.uuid4(),
            party_id=sample_party.guid,
            user_id=test_user2.guid,
            is_host=False,
            is_connected=False,
            left_at=datetime.now(UTC),
        )
        db_session.add_all([host, guest])
        await db_session.commit()

        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == sample_party.guid,
            WatchPartyMember.is_connected.is_(True),
        )
        result = await db_session.execute(stmt)
        active = list(result.scalars().all())

        assert len(active) == 1
        assert active[0].user_id == test_user.guid

    @pytest.mark.asyncio
    async def test_count_connected_members(
        self,
        db_session: AsyncSession,
        sample_party: WatchParty,
        test_user: User,
        test_user2: User,
    ):
        """Test counting connected members."""
        for i, user in enumerate([test_user, test_user2]):
            member = WatchPartyMember(
                guid=uuid.uuid4(),
                party_id=sample_party.guid,
                user_id=user.guid,
                is_host=(i == 0),
                is_connected=True,
            )
            db_session.add(member)
        await db_session.commit()

        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == sample_party.guid,
            WatchPartyMember.is_connected.is_(True),
        )
        result = await db_session.execute(stmt)
        members = list(result.scalars().all())
        assert len(members) == 2

    @pytest.mark.asyncio
    async def test_cascade_delete(
        self,
        db_session: AsyncSession,
        test_user: User,
    ):
        """Test that deleting a party cascades to members."""
        party = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        db_session.add(party)
        await db_session.flush()

        member = WatchPartyMember(
            guid=uuid.uuid4(),
            party_id=party.guid,
            user_id=test_user.guid,
            is_host=True,
        )
        db_session.add(member)
        await db_session.commit()

        member_guid = member.guid

        await db_session.delete(party)
        await db_session.commit()

        stmt = select(WatchPartyMember).where(
            WatchPartyMember.guid == member_guid
        )
        result = await db_session.execute(stmt)
        assert result.scalar_one_or_none() is None


class TestWatchPartyPlaybackSync:
    """Tests for playback synchronization at the model level."""

    @pytest.mark.asyncio
    async def test_sync_playback_state(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test syncing playback position."""
        sample_party.current_time = 300.0
        sample_party.is_playing = True
        sample_party.playback_rate = 1.0
        sample_party.last_sync_at = datetime.now(UTC)
        await db_session.commit()

        stmt = select(WatchParty).where(WatchParty.guid == sample_party.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()

        assert party.current_time == 300.0
        assert party.is_playing is True

    @pytest.mark.asyncio
    async def test_pause_playback(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test pausing playback."""
        sample_party.is_playing = True
        await db_session.commit()

        sample_party.is_playing = False
        sample_party.current_time = 150.0
        await db_session.commit()

        stmt = select(WatchParty).where(WatchParty.guid == sample_party.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()

        assert party.is_playing is False
        assert party.current_time == 150.0

    @pytest.mark.asyncio
    async def test_change_playback_rate(
        self, db_session: AsyncSession, sample_party: WatchParty
    ):
        """Test changing playback rate."""
        sample_party.playback_rate = 2.0
        await db_session.commit()

        stmt = select(WatchParty).where(WatchParty.guid == sample_party.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()

        assert party.playback_rate == 2.0


class TestWatchPartyExpiry:
    """Tests for party expiration."""

    @pytest.mark.asyncio
    async def test_query_non_expired_parties(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test querying only non-expired parties."""
        active = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="Active",
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        )
        expired = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            name="Expired",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add_all([active, expired])
        await db_session.commit()

        now = datetime.now(UTC)
        stmt = select(WatchParty).where(
            WatchParty.is_active.is_(True),
            WatchParty.expires_at > now,
        )
        result = await db_session.execute(stmt)
        parties = list(result.scalars().all())

        names = [p.name for p in parties]
        assert "Active" in names
        assert "Expired" not in names

    @pytest.mark.asyncio
    async def test_party_with_custom_expiry(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test creating a party with custom expiry."""
        custom_expiry = datetime.now(UTC) + timedelta(hours=2)
        party = WatchParty(
            guid=uuid.uuid4(),
            owner_id=test_user.guid,
            expires_at=custom_expiry,
        )
        db_session.add(party)
        await db_session.commit()
        await db_session.refresh(party)

        expires = party.expires_at if party.expires_at.tzinfo else party.expires_at.replace(tzinfo=UTC)
        diff = (expires - datetime.now(UTC)).total_seconds()
        assert 7000 < diff < 7300  # ~2 hours, with tolerance


# ===========================================================================
# WatchPartyService integration tests
# ===========================================================================


class TestWatchPartyServiceCreate:
    """Tests for WatchPartyService.create_session."""

    @pytest.mark.asyncio
    async def test_create_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        data = WatchPartyCreate(name="Movie Night", media_id=uuid.uuid4(), media_type="movie")
        result = await service.create_session(test_user.guid, data)

        assert result.name == "Movie Night"
        assert result.owner_id == test_user.guid
        assert len(result.party_code) == 6
        assert result.is_active is True
        assert len(result.members) == 1
        assert result.members[0].is_host is True
        assert result.members[0].user_id == test_user.guid

    @pytest.mark.asyncio
    async def test_create_session_defaults(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        data = WatchPartyCreate()
        result = await service.create_session(test_user.guid, data)

        assert result.allow_control is False
        assert result.current_time == 0.0
        assert result.is_playing is False
        assert result.playback_rate == 1.0

    @pytest.mark.asyncio
    async def test_create_session_allow_control(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        data = WatchPartyCreate(name="Open Control", allow_control=True)
        result = await service.create_session(test_user.guid, data)

        assert result.allow_control is True


class TestWatchPartyServiceJoin:
    """Tests for WatchPartyService.join_session."""

    @pytest.mark.asyncio
    async def test_join_session(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        data = WatchPartyCreate(name="Join Test")
        created = await service.create_session(test_user.guid, data)

        joined = await service.join_session(test_user2.guid, created.party_code)
        assert len(joined.members) == 2
        guest = [m for m in joined.members if m.user_id == test_user2.guid][0]
        assert guest.is_host is False
        assert guest.is_connected is True

    @pytest.mark.asyncio
    async def test_join_nonexistent_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        with pytest.raises(ValueError, match="not found"):
            await service.join_session(test_user.guid, "ZZZZZZ")

    @pytest.mark.asyncio
    async def test_join_already_connected(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Dup"))
        await service.join_session(test_user2.guid, created.party_code)

        with pytest.raises(ValueError, match="already"):
            await service.join_session(test_user2.guid, created.party_code)

    @pytest.mark.asyncio
    async def test_rejoin_after_leave(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Rejoin"))
        await service.join_session(test_user2.guid, created.party_code)
        await service.leave_session(test_user2.guid, created.guid)

        # Rejoin
        rejoined = await service.join_session(test_user2.guid, created.party_code)
        guest = [m for m in rejoined.members if m.user_id == test_user2.guid][0]
        assert guest.is_connected is True

    @pytest.mark.asyncio
    async def test_join_expired_session(self, db_session: AsyncSession, test_user: User, test_user2: User):
        # Create party directly with expired time
        party = WatchParty(
            owner_id=test_user.guid,
            name="Expired",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )
        db_session.add(party)
        await db_session.flush()

        member = WatchPartyMember(party_id=party.guid, user_id=test_user.guid, is_host=True)
        db_session.add(member)
        await db_session.commit()
        await db_session.refresh(party)

        service = WatchPartyService(db_session)
        with pytest.raises(ValueError, match="not found"):
            await service.join_session(test_user2.guid, party.party_code)

    @pytest.mark.asyncio
    async def test_join_inactive_session(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Ended"))
        await service.end_session(created.guid)

        with pytest.raises(ValueError, match="not found"):
            await service.join_session(test_user2.guid, created.party_code)


class TestWatchPartyServiceLeave:
    """Tests for WatchPartyService.leave_session."""

    @pytest.mark.asyncio
    async def test_leave_session(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Leave"))
        await service.join_session(test_user2.guid, created.party_code)

        await service.leave_session(test_user2.guid, created.guid)

        # Verify member is disconnected
        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == created.guid,
            WatchPartyMember.user_id == test_user2.guid,
        )
        result = await db_session.execute(stmt)
        member = result.scalar_one()
        assert member.is_connected is False
        assert member.left_at is not None

    @pytest.mark.asyncio
    async def test_host_leave_ends_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Host Leave"))
        await service.leave_session(test_user.guid, created.guid)

        # Session should be ended
        stmt = select(WatchParty).where(WatchParty.guid == created.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()
        assert party.is_active is False

    @pytest.mark.asyncio
    async def test_leave_nonexistent_member(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="NM"))
        # Should not raise for non-member
        await service.leave_session(uuid.uuid4(), created.guid)


class TestWatchPartyServiceKick:
    """Tests for WatchPartyService.kick_member."""

    @pytest.mark.asyncio
    async def test_kick_member(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Kick"))
        await service.join_session(test_user2.guid, created.party_code)

        await service.kick_member(created.guid, test_user.guid, test_user2.guid)

        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == created.guid,
            WatchPartyMember.user_id == test_user2.guid,
        )
        result = await db_session.execute(stmt)
        member = result.scalar_one()
        assert member.is_connected is False

    @pytest.mark.asyncio
    async def test_kick_not_host(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="KN"))
        await service.join_session(test_user2.guid, created.party_code)

        with pytest.raises(ValueError, match="host"):
            await service.kick_member(created.guid, test_user2.guid, test_user.guid)

    @pytest.mark.asyncio
    async def test_kick_host_forbidden(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="KH"))

        with pytest.raises(ValueError, match="host"):
            await service.kick_member(created.guid, test_user.guid, test_user.guid)

    @pytest.mark.asyncio
    async def test_kick_nonexistent_member(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="KNM"))

        with pytest.raises(ValueError, match="not found"):
            await service.kick_member(created.guid, test_user.guid, uuid.uuid4())

    @pytest.mark.asyncio
    async def test_kick_inactive_session(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="KI"))
        await service.join_session(test_user2.guid, created.party_code)
        await service.end_session(created.guid)

        with pytest.raises(ValueError, match="not found"):
            await service.kick_member(created.guid, test_user.guid, test_user2.guid)


class TestWatchPartyServiceEndSession:
    """Tests for WatchPartyService.end_session."""

    @pytest.mark.asyncio
    async def test_end_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="End"))
        await service.end_session(created.guid)

        stmt = select(WatchParty).where(WatchParty.guid == created.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()
        assert party.is_active is False
        assert party.ended_at is not None

    @pytest.mark.asyncio
    async def test_end_nonexistent_session(self, db_session: AsyncSession):
        service = WatchPartyService(db_session)
        with pytest.raises(ValueError, match="not found"):
            await service.end_session(uuid.uuid4())


class TestWatchPartyServiceUpdate:
    """Tests for WatchPartyService.update_session."""

    @pytest.mark.asyncio
    async def test_update_name(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Old"))
        updated = await service.update_session(created.guid, test_user.guid, WatchPartyUpdate(name="New"))
        assert updated.name == "New"

    @pytest.mark.asyncio
    async def test_update_allow_control(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="ACU"))
        updated = await service.update_session(created.guid, test_user.guid, WatchPartyUpdate(allow_control=True))
        assert updated.allow_control is True

    @pytest.mark.asyncio
    async def test_update_media(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        new_media = uuid.uuid4()
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="MU"))
        updated = await service.update_session(
            created.guid, test_user.guid, WatchPartyUpdate(media_id=new_media, media_type="episode")
        )
        assert updated.media_id == new_media
        assert updated.media_type == "episode"

    @pytest.mark.asyncio
    async def test_update_nonexistent(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        with pytest.raises(ValueError, match="not found"):
            await service.update_session(uuid.uuid4(), test_user.guid, WatchPartyUpdate(name="X"))


class TestWatchPartyServiceSync:
    """Tests for WatchPartyService.sync_playback."""

    @pytest.mark.asyncio
    async def test_sync_as_host(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Sync"))
        sync_data = PlaybackSync(current_time=120.5, is_playing=True, playback_rate=1.5)
        result = await service.sync_playback(created.guid, test_user.guid, sync_data)

        assert result.current_time == 120.5
        assert result.is_playing is True
        assert result.playback_rate == 1.5

    @pytest.mark.asyncio
    async def test_sync_as_guest_with_control(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(
            test_user.guid, WatchPartyCreate(name="GuestSync", allow_control=True)
        )
        await service.join_session(test_user2.guid, created.party_code)

        sync_data = PlaybackSync(current_time=60.0, is_playing=False)
        result = await service.sync_playback(created.guid, test_user2.guid, sync_data)
        assert result.current_time == 60.0
        assert result.is_playing is False

    @pytest.mark.asyncio
    async def test_sync_as_guest_no_control(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(
            test_user.guid, WatchPartyCreate(name="NoCtrl", allow_control=False)
        )
        await service.join_session(test_user2.guid, created.party_code)

        with pytest.raises(ValueError, match="host"):
            await service.sync_playback(
                created.guid, test_user2.guid, PlaybackSync(current_time=10.0, is_playing=True)
            )

    @pytest.mark.asyncio
    async def test_sync_non_member(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="NM"))

        with pytest.raises(ValueError, match="not a member"):
            await service.sync_playback(
                created.guid, uuid.uuid4(), PlaybackSync(current_time=10.0, is_playing=True)
            )

    @pytest.mark.asyncio
    async def test_sync_inactive_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="SI"))
        await service.end_session(created.guid)

        with pytest.raises(ValueError, match="not found"):
            await service.sync_playback(
                created.guid, test_user.guid, PlaybackSync(current_time=10.0, is_playing=True)
            )


class TestWatchPartyServiceGetSession:
    """Tests for WatchPartyService.get_session."""

    @pytest.mark.asyncio
    async def test_get_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Get"))
        result = await service.get_session(created.guid)
        assert result is not None
        assert result.guid == created.guid
        assert result.name == "Get"

    @pytest.mark.asyncio
    async def test_get_nonexistent_session(self, db_session: AsyncSession):
        service = WatchPartyService(db_session)
        result = await service.get_session(uuid.uuid4())
        assert result is None


class TestWatchPartyServiceUserSessions:
    """Tests for WatchPartyService.get_user_sessions."""

    @pytest.mark.asyncio
    async def test_get_user_sessions(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        await service.create_session(test_user.guid, WatchPartyCreate(name="S1"))
        await service.create_session(test_user.guid, WatchPartyCreate(name="S2"))
        sessions = await service.get_user_sessions(test_user.guid)
        assert len(sessions) == 2
        names = {s.name for s in sessions}
        assert "S1" in names
        assert "S2" in names

    @pytest.mark.asyncio
    async def test_user_sessions_excludes_ended(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        await service.create_session(test_user.guid, WatchPartyCreate(name="Active"))
        s2 = await service.create_session(test_user.guid, WatchPartyCreate(name="Ended"))
        await service.end_session(s2.guid)

        sessions = await service.get_user_sessions(test_user.guid)
        names = [s.name for s in sessions]
        assert "Active" in names
        assert "Ended" not in names

    @pytest.mark.asyncio
    async def test_user_sessions_includes_joined(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="Joined"))
        await service.join_session(test_user2.guid, created.party_code)

        sessions = await service.get_user_sessions(test_user2.guid)
        assert len(sessions) == 1
        assert sessions[0].is_owner is False

    @pytest.mark.asyncio
    async def test_user_sessions_empty(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        sessions = await service.get_user_sessions(test_user.guid)
        assert sessions == []


class TestWatchPartyServiceHeartbeat:
    """Tests for WatchPartyService.heartbeat."""

    @pytest.mark.asyncio
    async def test_heartbeat_updates_timestamp(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="HB"))

        await service.heartbeat(created.guid, test_user.guid)

        stmt = select(WatchPartyMember).where(
            WatchPartyMember.party_id == created.guid,
            WatchPartyMember.user_id == test_user.guid,
        )
        result = await db_session.execute(stmt)
        member = result.scalar_one()
        assert member.last_heartbeat is not None

    @pytest.mark.asyncio
    async def test_heartbeat_nonexistent_member(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="HBN"))
        # Should not raise
        await service.heartbeat(created.guid, uuid.uuid4())


class TestWatchPartyServiceFriends:
    """Tests for WatchPartyService.get_friends_sessions."""

    @pytest.mark.asyncio
    async def test_friends_sessions(self, db_session: AsyncSession, test_user: User, test_user2: User):
        # Create friendship
        friendship = Friendship(
            requester_id=test_user.guid,
            addressee_id=test_user2.guid,
            status=FriendshipStatus.accepted,
        )
        db_session.add(friendship)
        await db_session.commit()

        service = WatchPartyService(db_session)
        await service.create_session(test_user2.guid, WatchPartyCreate(name="Friend Party"))

        sessions = await service.get_friends_sessions(test_user.guid)
        assert len(sessions) == 1
        assert sessions[0].name == "Friend Party"
        assert sessions[0].is_owner is False

    @pytest.mark.asyncio
    async def test_friends_sessions_reverse_direction(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        # Friendship where test_user2 is requester
        friendship = Friendship(
            requester_id=test_user2.guid,
            addressee_id=test_user.guid,
            status=FriendshipStatus.accepted,
        )
        db_session.add(friendship)
        await db_session.commit()

        service = WatchPartyService(db_session)
        await service.create_session(test_user2.guid, WatchPartyCreate(name="Rev"))

        sessions = await service.get_friends_sessions(test_user.guid)
        assert len(sessions) == 1

    @pytest.mark.asyncio
    async def test_no_friends(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        sessions = await service.get_friends_sessions(test_user.guid)
        assert sessions == []

    @pytest.mark.asyncio
    async def test_friends_sessions_excludes_ended(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        friendship = Friendship(
            requester_id=test_user.guid,
            addressee_id=test_user2.guid,
            status=FriendshipStatus.accepted,
        )
        db_session.add(friendship)
        await db_session.commit()

        service = WatchPartyService(db_session)
        created = await service.create_session(test_user2.guid, WatchPartyCreate(name="FE"))
        await service.end_session(created.guid)

        sessions = await service.get_friends_sessions(test_user.guid)
        assert sessions == []


class TestWatchPartyServiceAdmin:
    """Tests for WatchPartyService admin methods."""

    @pytest.mark.asyncio
    async def test_get_all_active_sessions(self, db_session: AsyncSession, test_user: User, test_user2: User):
        service = WatchPartyService(db_session)
        await service.create_session(test_user.guid, WatchPartyCreate(name="A1"))
        await service.create_session(test_user2.guid, WatchPartyCreate(name="A2"))

        all_sessions = await service.get_all_active_sessions()
        names = {s.name for s in all_sessions}
        assert "A1" in names
        assert "A2" in names

    @pytest.mark.asyncio
    async def test_admin_end_session(self, db_session: AsyncSession, test_user: User):
        service = WatchPartyService(db_session)
        created = await service.create_session(test_user.guid, WatchPartyCreate(name="AE"))

        await service.admin_end_session(created.guid)

        stmt = select(WatchParty).where(WatchParty.guid == created.guid)
        result = await db_session.execute(stmt)
        party = result.scalar_one()
        assert party.is_active is False

    @pytest.mark.asyncio
    async def test_admin_end_nonexistent(self, db_session: AsyncSession):
        service = WatchPartyService(db_session)
        with pytest.raises(ValueError, match="not found"):
            await service.admin_end_session(uuid.uuid4())
