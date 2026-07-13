"""Tests for the InviteService."""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.invite import Invite
from streamarr.models.user import User
from streamarr.schemas.invite import InviteCreate, InviteUpdate
from streamarr.services.invite import InviteService


class TestInviteCRUD:
    """Test basic CRUD operations for invites."""

    @pytest.mark.asyncio
    async def test_create_invite(self, db_session: AsyncSession, test_user: User):
        """Test creating an invite."""
        service = InviteService(db_session)

        invite_data = InviteCreate(
            description="Test invite",
            max_uses=5,
        )
        expires_at = datetime.now(UTC) + timedelta(hours=72)

        invite = await service.create(
            invite_create=invite_data,
            created_by_user_id=test_user.guid,
            token="test-token-abc123",
            expires_at=expires_at,
        )

        assert invite is not None
        assert invite.token == "test-token-abc123"
        assert invite.description == "Test invite"
        assert invite.max_uses == 5
        assert invite.current_uses == 0
        assert invite.is_active is True
        assert invite.is_used is False
        assert invite.created_by_user_id == test_user.guid

    @pytest.mark.asyncio
    async def test_get_by_id(self, db_session: AsyncSession, test_user: User):
        """Test getting an invite by ID."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(description="Test"),
            created_by_user_id=test_user.guid,
            token="token-get-test",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        retrieved = await service.get_by_id(invite.guid)

        assert retrieved is not None
        assert retrieved.guid == invite.guid
        assert retrieved.token == "token-get-test"

    @pytest.mark.asyncio
    async def test_get_by_id_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent invite."""
        service = InviteService(db_session)

        result = await service.get_by_id(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_by_token(self, db_session: AsyncSession, test_user: User):
        """Test getting an invite by token string."""
        service = InviteService(db_session)
        await service.create(
            InviteCreate(description="Token lookup test"),
            created_by_user_id=test_user.guid,
            token="unique-token-xyz",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        result = await service.get_by_token("unique-token-xyz")

        assert result is not None
        assert result.description == "Token lookup test"

    @pytest.mark.asyncio
    async def test_get_by_token_not_found(self, db_session: AsyncSession):
        """Test getting an invite with invalid token."""
        service = InviteService(db_session)

        result = await service.get_by_token("nonexistent-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_update_invite(self, db_session: AsyncSession, test_user: User):
        """Test updating an invite."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(description="Original"),
            created_by_user_id=test_user.guid,
            token="update-test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        updated = await service.update(
            invite.guid,
            InviteUpdate(description="Updated", max_uses=10),
        )

        assert updated is not None
        assert updated.description == "Updated"
        assert updated.max_uses == 10

    @pytest.mark.asyncio
    async def test_update_nonexistent_invite(self, db_session: AsyncSession):
        """Test updating a non-existent invite."""
        service = InviteService(db_session)

        result = await service.update(
            uuid.uuid4(), InviteUpdate(description="Nope")
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_invite(self, db_session: AsyncSession, test_user: User):
        """Test deleting an invite."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="delete-test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        result = await service.delete(invite.guid)

        assert result is True
        deleted = await service.get_by_id(invite.guid)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_invite(self, db_session: AsyncSession):
        """Test deleting a non-existent invite."""
        service = InviteService(db_session)

        result = await service.delete(uuid.uuid4())

        assert result is False


class TestInviteValidation:
    """Test invite validation logic."""

    @pytest.mark.asyncio
    async def test_get_valid_by_token(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting a valid invite by token."""
        service = InviteService(db_session)
        await service.create(
            InviteCreate(max_uses=5),
            created_by_user_id=test_user.guid,
            token="valid-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        result = await service.get_valid_by_token("valid-token")

        assert result is not None
        assert result.token == "valid-token"

    @pytest.mark.asyncio
    async def test_get_valid_by_token_expired(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that expired invites are not returned as valid."""
        service = InviteService(db_session)
        await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="expired-token",
            expires_at=datetime.now(UTC) - timedelta(hours=1),  # Already expired
        )

        result = await service.get_valid_by_token("expired-token")

        assert result is None

    @pytest.mark.asyncio
    async def test_get_valid_by_token_deactivated(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that deactivated invites are not returned as valid."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="deactivated-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )
        await service.deactivate(invite.guid)

        result = await service.get_valid_by_token("deactivated-token")

        assert result is None


class TestInviteUsage:
    """Test invite usage tracking."""

    @pytest.mark.asyncio
    async def test_use_invite(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test using an invite."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(max_uses=3),
            created_by_user_id=test_user.guid,
            token="use-test-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        used = await service.use_invite(invite.guid, test_user2.guid)

        assert used is not None
        assert used.current_uses == 1
        assert used.used_by_user_id == test_user2.guid
        assert used.is_used is False  # Still has uses left

    @pytest.mark.asyncio
    async def test_use_invite_exhausted(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test using the last use of an invite."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(max_uses=1),
            created_by_user_id=test_user.guid,
            token="single-use-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        used = await service.use_invite(invite.guid, test_user2.guid)

        assert used.current_uses == 1
        assert used.is_used is True
        assert used.used_at is not None

    @pytest.mark.asyncio
    async def test_use_nonexistent_invite(self, db_session: AsyncSession):
        """Test using a non-existent invite."""
        service = InviteService(db_session)

        result = await service.use_invite(uuid.uuid4(), uuid.uuid4())

        assert result is None


class TestInviteDeactivation:
    """Test invite deactivation."""

    @pytest.mark.asyncio
    async def test_deactivate_invite(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test deactivating an invite."""
        service = InviteService(db_session)
        invite = await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="deactivate-me",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        result = await service.deactivate(invite.guid)

        assert result is not None
        assert result.is_active is False

    @pytest.mark.asyncio
    async def test_deactivate_nonexistent_invite(self, db_session: AsyncSession):
        """Test deactivating a non-existent invite."""
        service = InviteService(db_session)

        result = await service.deactivate(uuid.uuid4())

        assert result is None


class TestInviteListing:
    """Test invite listing and pagination."""

    @pytest.mark.asyncio
    async def test_get_by_user(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting invites created by a specific user."""
        service = InviteService(db_session)

        # Create invites for different users
        await service.create(
            InviteCreate(description="User 1 invite"),
            created_by_user_id=test_user.guid,
            token="user1-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )
        await service.create(
            InviteCreate(description="User 2 invite"),
            created_by_user_id=test_user2.guid,
            token="user2-token",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        user1_invites = await service.get_by_user(test_user.guid)

        assert len(user1_invites) == 1
        assert user1_invites[0].description == "User 1 invite"

    @pytest.mark.asyncio
    async def test_get_by_user_paginated(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test paginated invite listing for a user."""
        service = InviteService(db_session)

        for i in range(5):
            await service.create(
                InviteCreate(description=f"Invite {i}"),
                created_by_user_id=test_user.guid,
                token=f"token-{i}",
                expires_at=datetime.now(UTC) + timedelta(hours=72),
            )

        invites, total = await service.get_by_user_paginated(
            test_user.guid, skip=0, limit=2
        )

        assert total == 5
        assert len(invites) == 2

    @pytest.mark.asyncio
    async def test_get_all(self, db_session: AsyncSession, test_user: User):
        """Test getting all non-expired invites."""
        service = InviteService(db_session)

        # Create a valid invite
        await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="valid-inv",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )
        # Create an expired invite
        await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="expired-inv",
            expires_at=datetime.now(UTC) - timedelta(hours=1),
        )

        non_expired = await service.get_all(include_expired=False)
        all_invites = await service.get_all(include_expired=True)

        assert len(non_expired) == 1
        assert len(all_invites) == 2

    @pytest.mark.asyncio
    async def test_get_all_paginated(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test paginated listing of all invites."""
        service = InviteService(db_session)

        for i in range(5):
            await service.create(
                InviteCreate(),
                created_by_user_id=test_user.guid,
                token=f"all-token-{i}",
                expires_at=datetime.now(UTC) + timedelta(hours=72),
            )

        invites, total = await service.get_all_paginated(skip=0, limit=3)

        assert total == 5
        assert len(invites) == 3


class TestInviteCleanup:
    """Test expired invite cleanup."""

    @pytest.mark.asyncio
    async def test_cleanup_expired(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test cleaning up expired invites."""
        service = InviteService(db_session)

        # Create expired invites
        for i in range(3):
            await service.create(
                InviteCreate(),
                created_by_user_id=test_user.guid,
                token=f"expired-{i}",
                expires_at=datetime.now(UTC) - timedelta(hours=1),
            )
        # Create a valid invite
        await service.create(
            InviteCreate(),
            created_by_user_id=test_user.guid,
            token="still-valid",
            expires_at=datetime.now(UTC) + timedelta(hours=72),
        )

        deleted_count = await service.cleanup_expired()

        assert deleted_count == 3
        remaining = await service.get_all(include_expired=True)
        assert len(remaining) == 1
        assert remaining[0].token == "still-valid"
