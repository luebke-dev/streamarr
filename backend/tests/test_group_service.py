"""Tests for the GroupService."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.group import Group, UserGroupLink
from pyrate.models.user import User
from pyrate.schemas.group import GroupCreate, GroupUpdate
from pyrate.services.group import GroupService


class TestGroupCRUD:
    """Test basic CRUD operations for groups."""

    @pytest.mark.asyncio
    async def test_create_group(self, db_session: AsyncSession):
        """Test creating a group."""
        service = GroupService(db_session)

        group_data = GroupCreate(
            name="Premium",
            description="Premium users",
            allowed_libraries=["movies", "shows"],
            max_concurrent_streams=3,
            max_video_quality="uhd",
            max_audio_quality="lossless",
        )
        group = await service.create_group(group_data)

        assert group is not None
        assert group.name == "Premium"
        assert group.description == "Premium users"
        assert group.allowed_libraries == ["movies", "shows"]
        assert group.max_concurrent_streams == 3
        assert group.is_active is True

    @pytest.mark.asyncio
    async def test_get_group(self, db_session: AsyncSession):
        """Test getting a group by ID."""
        service = GroupService(db_session)
        group_data = GroupCreate(name="Basic")
        created = await service.create_group(group_data)

        retrieved = await service.get_group(created.guid)

        assert retrieved is not None
        assert retrieved.guid == created.guid
        assert retrieved.name == "Basic"

    @pytest.mark.asyncio
    async def test_get_group_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent group."""
        service = GroupService(db_session)

        result = await service.get_group(uuid.uuid4())

        assert result is None

    @pytest.mark.asyncio
    async def test_get_group_by_name(self, db_session: AsyncSession):
        """Test getting a group by name."""
        service = GroupService(db_session)
        await service.create_group(GroupCreate(name="VIP"))

        result = await service.get_group_by_name("VIP")

        assert result is not None
        assert result.name == "VIP"

    @pytest.mark.asyncio
    async def test_get_group_by_name_not_found(self, db_session: AsyncSession):
        """Test getting a non-existent group by name."""
        service = GroupService(db_session)

        result = await service.get_group_by_name("Nonexistent")

        assert result is None

    @pytest.mark.asyncio
    async def test_list_groups(self, db_session: AsyncSession):
        """Test listing all active groups."""
        service = GroupService(db_session)

        await service.create_group(GroupCreate(name="Group A"))
        await service.create_group(GroupCreate(name="Group B"))
        await service.create_group(GroupCreate(name="Group C"))

        groups = await service.list_groups()

        assert len(groups) == 3

    @pytest.mark.asyncio
    async def test_list_groups_excludes_inactive(self, db_session: AsyncSession):
        """Test that inactive groups are excluded by default."""
        service = GroupService(db_session)

        await service.create_group(GroupCreate(name="Active Group"))
        inactive = await service.create_group(
            GroupCreate(name="Inactive Group", is_active=False)
        )

        active_groups = await service.list_groups()
        all_groups = await service.list_groups(include_inactive=True)

        assert len(active_groups) == 1
        assert len(all_groups) == 2

    @pytest.mark.asyncio
    async def test_update_group(self, db_session: AsyncSession):
        """Test updating a group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="Basic"))

        updated = await service.update_group(
            group.guid,
            GroupUpdate(
                name="Premium",
                description="Upgraded to premium",
                max_concurrent_streams=5,
            ),
        )

        assert updated is not None
        assert updated.name == "Premium"
        assert updated.description == "Upgraded to premium"
        assert updated.max_concurrent_streams == 5

    @pytest.mark.asyncio
    async def test_update_group_partial(self, db_session: AsyncSession):
        """Test partial group update."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(name="Basic", description="Original")
        )

        updated = await service.update_group(
            group.guid, GroupUpdate(description="Updated")
        )

        assert updated.name == "Basic"
        assert updated.description == "Updated"

    @pytest.mark.asyncio
    async def test_update_nonexistent_group(self, db_session: AsyncSession):
        """Test updating a non-existent group."""
        service = GroupService(db_session)

        result = await service.update_group(uuid.uuid4(), GroupUpdate(name="Nope"))

        assert result is None

    @pytest.mark.asyncio
    async def test_delete_group(self, db_session: AsyncSession):
        """Test deleting a group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="ToDelete"))

        result = await service.delete_group(group.guid)

        assert result is True
        deleted = await service.get_group(group.guid)
        assert deleted is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_group(self, db_session: AsyncSession):
        """Test deleting a non-existent group."""
        service = GroupService(db_session)

        result = await service.delete_group(uuid.uuid4())

        assert result is False


class TestGroupMembership:
    """Test group membership operations."""

    @pytest.mark.asyncio
    async def test_add_user_to_group(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test adding a user to a group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))

        link = await service.add_user_to_group(test_user.guid, group.guid)

        assert link is not None
        assert link.user_id == test_user.guid
        assert link.group_id == group.guid

    @pytest.mark.asyncio
    async def test_add_user_to_group_idempotent(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that adding the same user twice returns existing link."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))

        link1 = await service.add_user_to_group(test_user.guid, group.guid)
        link2 = await service.add_user_to_group(test_user.guid, group.guid)

        assert link1.guid == link2.guid

    @pytest.mark.asyncio
    async def test_remove_user_from_group(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test removing a user from a group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))
        await service.add_user_to_group(test_user.guid, group.guid)

        result = await service.remove_user_from_group(test_user.guid, group.guid)

        assert result is True

    @pytest.mark.asyncio
    async def test_remove_user_not_in_group(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test removing a user who is not in the group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))

        result = await service.remove_user_from_group(test_user.guid, group.guid)

        assert result is False

    @pytest.mark.asyncio
    async def test_get_user_groups(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test getting all groups for a user."""
        service = GroupService(db_session)
        group1 = await service.create_group(GroupCreate(name="Group A"))
        group2 = await service.create_group(GroupCreate(name="Group B"))

        await service.add_user_to_group(test_user.guid, group1.guid)
        await service.add_user_to_group(test_user.guid, group2.guid)

        groups = await service.get_user_groups(test_user.guid)

        assert len(groups) == 2
        group_names = {g.name for g in groups}
        assert "Group A" in group_names
        assert "Group B" in group_names

    @pytest.mark.asyncio
    async def test_get_group_members(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test getting all members of a group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))

        await service.add_user_to_group(test_user.guid, group.guid)
        await service.add_user_to_group(test_user2.guid, group.guid)

        members = await service.get_group_members(group.guid)

        assert len(members) == 2
        member_emails = {m.email for m in members}
        assert test_user.email in member_emails
        assert test_user2.email in member_emails

    @pytest.mark.asyncio
    async def test_get_group_member_count(
        self, db_session: AsyncSession, test_user: User, test_user2: User
    ):
        """Test counting group members."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="TestGroup"))

        await service.add_user_to_group(test_user.guid, group.guid)
        await service.add_user_to_group(test_user2.guid, group.guid)

        count = await service.get_group_member_count(group.guid)

        assert count == 2

    @pytest.mark.asyncio
    async def test_get_group_member_count_empty(self, db_session: AsyncSession):
        """Test counting members of empty group."""
        service = GroupService(db_session)
        group = await service.create_group(GroupCreate(name="EmptyGroup"))

        count = await service.get_group_member_count(group.guid)

        assert count == 0


class TestUserPermissions:
    """Test user permission computation."""

    @pytest.mark.asyncio
    async def test_permissions_no_groups(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test permissions when user has no groups."""
        service = GroupService(db_session)

        permissions = await service.compute_user_permissions(test_user.guid)

        assert permissions.user_id == test_user.guid
        assert permissions.allowed_libraries == []
        assert permissions.max_concurrent_streams == 0
        assert permissions.max_video_quality is None
        assert permissions.max_audio_quality is None
        assert permissions.group_names == []

    @pytest.mark.asyncio
    async def test_permissions_single_group(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test permissions from a single group."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(
                name="Premium",
                allowed_libraries=["movies", "shows"],
                max_concurrent_streams=3,
                max_video_quality="fhd",
                max_audio_quality="lossless",
                max_concurrent_transcodings=2,
            )
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        permissions = await service.compute_user_permissions(test_user.guid)

        assert sorted(permissions.allowed_libraries) == ["movies", "shows"]
        assert permissions.max_concurrent_streams == 3
        assert permissions.max_video_quality == "fhd"
        assert permissions.max_audio_quality == "lossless"
        assert permissions.max_concurrent_transcodings == 2
        assert "Premium" in permissions.group_names

    @pytest.mark.asyncio
    async def test_permissions_multiple_groups_merge(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test that permissions from multiple groups are merged correctly."""
        service = GroupService(db_session)

        group1 = await service.create_group(
            GroupCreate(
                name="Movies Only",
                allowed_libraries=["movies"],
                max_concurrent_streams=1,
                max_video_quality="hd",
                max_audio_quality="lossy",
            )
        )
        group2 = await service.create_group(
            GroupCreate(
                name="Shows Plus",
                allowed_libraries=["shows", "music"],
                max_concurrent_streams=3,
                max_video_quality="uhd",
                max_audio_quality="lossless",
            )
        )

        await service.add_user_to_group(test_user.guid, group1.guid)
        await service.add_user_to_group(test_user.guid, group2.guid)

        permissions = await service.compute_user_permissions(test_user.guid)

        # Libraries should be merged
        assert sorted(permissions.allowed_libraries) == ["movies", "music", "shows"]
        # Max concurrent streams should take the highest
        assert permissions.max_concurrent_streams == 3
        # Video quality should take the highest rank
        assert permissions.max_video_quality == "uhd"
        # Audio quality should take the highest rank
        assert permissions.max_audio_quality == "lossless"
        # Both group names should be present
        assert len(permissions.group_names) == 2

    @pytest.mark.asyncio
    async def test_check_library_access_allowed(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test checking library access when allowed."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(
                name="Full Access",
                allowed_libraries=["movies", "shows", "music"],
            )
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        assert await service.check_library_access(test_user.guid, "movies") is True
        assert await service.check_library_access(test_user.guid, "shows") is True

    @pytest.mark.asyncio
    async def test_check_library_access_denied(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test checking library access when denied."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(
                name="Limited",
                allowed_libraries=["movies"],
            )
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        assert await service.check_library_access(test_user.guid, "games") is False

    @pytest.mark.asyncio
    async def test_check_video_quality_access(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test checking video quality access."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(name="HD Group", max_video_quality="fhd")
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        # FHD and below should be allowed
        assert (
            await service.check_video_quality_access(test_user.guid, "sd") is True
        )
        assert (
            await service.check_video_quality_access(test_user.guid, "hd") is True
        )
        assert (
            await service.check_video_quality_access(test_user.guid, "fhd") is True
        )
        # UHD should be denied
        assert (
            await service.check_video_quality_access(test_user.guid, "uhd") is False
        )

    @pytest.mark.asyncio
    async def test_check_audio_quality_access(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test checking audio quality access."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(name="Lossy Group", max_audio_quality="lossy")
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        assert (
            await service.check_audio_quality_access(test_user.guid, "lossy") is True
        )
        assert (
            await service.check_audio_quality_access(test_user.guid, "lossless")
            is False
        )

    @pytest.mark.asyncio
    async def test_check_transcoding_allowed(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test checking transcoding limits."""
        service = GroupService(db_session)
        group = await service.create_group(
            GroupCreate(name="TC Group", max_concurrent_transcodings=2)
        )
        await service.add_user_to_group(test_user.guid, group.guid)

        assert await service.check_transcoding_allowed(test_user.guid, 1) is True
        assert await service.check_transcoding_allowed(test_user.guid, 2) is True
        assert await service.check_transcoding_allowed(test_user.guid, 3) is False

    @pytest.mark.asyncio
    async def test_check_video_quality_no_groups(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test video quality check when user has no groups."""
        service = GroupService(db_session)

        assert (
            await service.check_video_quality_access(test_user.guid, "sd") is False
        )

    @pytest.mark.asyncio
    async def test_check_audio_quality_no_groups(
        self, db_session: AsyncSession, test_user: User
    ):
        """Test audio quality check when user has no groups."""
        service = GroupService(db_session)

        assert (
            await service.check_audio_quality_access(test_user.guid, "lossy") is False
        )
