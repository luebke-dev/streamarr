"""Tests for the PermissionService."""

import uuid

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.group import Group, UserGroupLink
from streamarr.models.setting import Setting
from streamarr.models.user import User
from streamarr.services.permission import PermissionService


@pytest_asyncio.fixture
async def permission_user(db_session: AsyncSession) -> User:
    """Create a test user for permission tests."""
    user = User(
        guid=uuid.uuid4(),
        email="perm_test@example.com",
        first_name="Perm",
        last_name="Test",
        is_active=True,
        is_superuser=False,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def superuser(db_session: AsyncSession) -> User:
    """Create a superuser for permission tests."""
    user = User(
        guid=uuid.uuid4(),
        email="perm_admin@example.com",
        first_name="Admin",
        last_name="Test",
        is_active=True,
        is_superuser=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _create_group(
    db_session: AsyncSession, name: str, **kwargs
) -> Group:
    group = Group(guid=uuid.uuid4(), name=name, **kwargs)
    db_session.add(group)
    await db_session.commit()
    await db_session.refresh(group)
    return group


async def _assign_user_to_group(
    db_session: AsyncSession, user_id: uuid.UUID, group_id: uuid.UUID
) -> None:
    link = UserGroupLink(guid=uuid.uuid4(), user_id=user_id, group_id=group_id)
    db_session.add(link)
    await db_session.commit()


async def _set_global_setting(
    db_session: AsyncSession, key: str, value
) -> None:
    setting = Setting(id=uuid.uuid4(), key=key, value=value)
    db_session.add(setting)
    await db_session.commit()


class TestUserWithoutGroup:
    """User without any group should get global defaults."""

    async def test_gets_global_default_libraries(
        self, db_session: AsyncSession, permission_user: User
    ):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        # Default global allows all libraries
        assert "movies" in perms.allowed_libraries
        assert "series" in perms.allowed_libraries
        assert "games" in perms.allowed_libraries
        assert "books" in perms.allowed_libraries
        assert "music" in perms.allowed_libraries

    async def test_gets_global_default_streams(
        self, db_session: AsyncSession, permission_user: User
    ):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_concurrent_streams == 3  # Global default
        assert perms.max_video_quality == "uhd"
        assert perms.max_audio_quality == "lossless"

    async def test_source_is_global(
        self, db_session: AsyncSession, permission_user: User
    ):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.source == "global"


class TestUserWithGroup:
    """User with group should get group permissions capped by global."""

    async def test_group_libraries(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "Basic",
            allowed_libraries=["movies", "series"],
            max_concurrent_streams=2,
            max_video_quality="fhd",
            max_audio_quality="lossy",
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.allowed_libraries == ["movies", "series"]
        assert perms.max_concurrent_streams == 2
        assert perms.max_video_quality == "fhd"
        assert perms.max_audio_quality == "lossy"
        assert perms.source == "group"

    async def test_group_capped_by_global(
        self, db_session: AsyncSession, permission_user: User
    ):
        """Group gives more than global allows — should be capped."""
        # Set global cap to 1 stream
        await _set_global_setting(
            db_session, "permissions.max_concurrent_streams", 1
        )
        group = await _create_group(
            db_session,
            "Premium",
            allowed_libraries=["movies"],
            max_concurrent_streams=5,
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_concurrent_streams == 1  # Capped by global

    async def test_group_quality_capped_by_global(
        self, db_session: AsyncSession, permission_user: User
    ):
        """Group gives uhd but global caps at fhd."""
        await _set_global_setting(
            db_session, "permissions.max_video_quality", "fhd"
        )
        group = await _create_group(
            db_session,
            "UHD Group",
            allowed_libraries=["movies"],
            max_video_quality="uhd",
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_video_quality == "fhd"  # Capped by global


class TestUserOverride:
    """User-level overrides take precedence over group."""

    async def test_override_streams(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "Standard",
            allowed_libraries=["movies"],
            max_concurrent_streams=2,
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        # Set user override
        permission_user.max_concurrent_streams = 1
        await db_session.commit()

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_concurrent_streams == 1  # Override wins

    async def test_override_libraries(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "All Access",
            allowed_libraries=["movies", "series", "games"],
            max_concurrent_streams=3,
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        # User override restricts to movies only
        permission_user.allowed_libraries = ["movies"]
        await db_session.commit()

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.allowed_libraries == ["movies"]

    async def test_override_capped_by_global(
        self, db_session: AsyncSession, permission_user: User
    ):
        """User override exceeding global cap gets capped."""
        await _set_global_setting(
            db_session, "permissions.max_concurrent_streams", 2
        )

        permission_user.max_concurrent_streams = 10
        await db_session.commit()

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_concurrent_streams == 2  # Capped by global

    async def test_override_quality(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "HD Group",
            allowed_libraries=["movies"],
            max_video_quality="uhd",
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        permission_user.max_video_quality = "hd"
        await db_session.commit()

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert perms.max_video_quality == "hd"  # Override wins


class TestGlobalDisabledLibrary:
    """Globally disabled libraries should always be removed."""

    async def test_disabled_library_removed(
        self, db_session: AsyncSession, permission_user: User
    ):
        # Disable movies globally
        await _set_global_setting(db_session, "plugin.movies.enabled", False)

        group = await _create_group(
            db_session,
            "Movies Group",
            allowed_libraries=["movies", "series"],
            max_concurrent_streams=2,
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert "movies" not in perms.allowed_libraries
        assert "series" in perms.allowed_libraries

    async def test_disabled_library_removed_from_user_override(
        self, db_session: AsyncSession, permission_user: User
    ):
        await _set_global_setting(db_session, "plugin.games.enabled", False)

        permission_user.allowed_libraries = ["movies", "games"]
        await db_session.commit()

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(permission_user.guid)

        assert "games" not in perms.allowed_libraries
        assert "movies" in perms.allowed_libraries


class TestSuperuser:
    """Superusers should get maximum permissions."""

    async def test_superuser_gets_all_libraries(
        self, db_session: AsyncSession, superuser: User
    ):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(superuser.guid)

        assert "movies" in perms.allowed_libraries
        assert "series" in perms.allowed_libraries
        assert perms.source == "superuser"

    async def test_superuser_unlimited_streams(
        self, db_session: AsyncSession, superuser: User
    ):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(superuser.guid)

        assert perms.max_concurrent_streams == 999
        assert perms.max_video_quality == "uhd"
        assert perms.max_audio_quality == "lossless"
        assert perms.playback_limit is None  # Unlimited

    async def test_superuser_ignores_disabled_library(
        self, db_session: AsyncSession, superuser: User
    ):
        """Even superusers shouldn't access disabled libraries."""
        await _set_global_setting(db_session, "plugin.games.enabled", False)

        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(superuser.guid)

        assert "games" not in perms.allowed_libraries


class TestNonExistentUser:
    """Non-existent user gets empty permissions."""

    async def test_empty_permissions(self, db_session: AsyncSession):
        service = PermissionService(db_session)
        perms = await service.resolve_user_permissions(uuid.uuid4())

        assert perms.allowed_libraries == []
        assert perms.max_concurrent_streams == 0
        assert perms.max_video_quality is None


class TestConvenienceChecks:
    """Test convenience check methods."""

    async def test_check_library_access_allowed(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "Movie Fans",
            allowed_libraries=["movies"],
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        assert await service.check_library_access(permission_user.guid, "movies") is True
        assert await service.check_library_access(permission_user.guid, "games") is False

    async def test_check_video_quality(
        self, db_session: AsyncSession, permission_user: User
    ):
        group = await _create_group(
            db_session,
            "HD Only",
            allowed_libraries=["movies"],
            max_video_quality="hd",
        )
        await _assign_user_to_group(db_session, permission_user.guid, group.guid)

        service = PermissionService(db_session)
        assert await service.check_video_quality(permission_user.guid, "sd") is True
        assert await service.check_video_quality(permission_user.guid, "hd") is True
        assert await service.check_video_quality(permission_user.guid, "fhd") is False
        assert await service.check_video_quality(permission_user.guid, "uhd") is False
