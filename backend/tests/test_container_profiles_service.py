"""Tests for the container-profile service: CRUD + launch-config merge logic."""

from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

# Import the model at module scope so it registers on Base.metadata before the
# test_db_engine fixture runs create_all().
from pyrate.models.container_profile import ContainerProfile  # noqa: F401
from pyrate.services import container_profiles as cp

STEAM_IMAGE = "ghcr.io/games-on-whales/steam:edge"


def _media(lightrays: dict | None):
    """Build a stub media item with an ``extra_data.lightrays`` block."""
    extra = {"lightrays": lightrays} if lightrays is not None else None
    return SimpleNamespace(extra_data=extra)


@pytest_asyncio.fixture
async def steam_profile(db_session: AsyncSession) -> ContainerProfile:
    """Seed the builtin default ``steam`` profile (as the migration would)."""
    return await cp.create(
        db_session,
        name="steam",
        kind="steam",
        docker_image=STEAM_IMAGE,
        runtime_profile="gow-app",
        env={},
        is_builtin=True,
    )


# ── CRUD ────────────────────────────────────────────────────────────────────


class TestContainerProfileCRUD:
    @pytest.mark.asyncio
    async def test_create_and_get(self, db_session: AsyncSession):
        created = await cp.create(
            db_session,
            name="generic",
            kind="generic",
            docker_image="repo/app:1",
            runtime_profile="gow-app",
            env={"FOO": "bar"},
        )
        assert created.guid is not None
        assert created.is_builtin is False

        by_name = await cp.get_by_name(db_session, "generic")
        assert by_name is not None and by_name.guid == created.guid

        by_guid = await cp.get_by_guid(db_session, created.guid)
        assert by_guid is not None and by_guid.name == "generic"

        # String guid is accepted too.
        by_guid_str = await cp.get_by_guid(db_session, str(created.guid))
        assert by_guid_str is not None

    @pytest.mark.asyncio
    async def test_list_profiles(self, db_session: AsyncSession, steam_profile):
        await cp.create(
            db_session, name="aaa", kind="generic", docker_image="repo/a:1"
        )
        profiles = await cp.list_profiles(db_session)
        names = [p.name for p in profiles]
        assert names == sorted(names)
        assert {"aaa", "steam"} <= set(names)

    @pytest.mark.asyncio
    async def test_update(self, db_session: AsyncSession):
        profile = await cp.create(
            db_session, name="p", kind="generic", docker_image="repo/a:1"
        )
        updated = await cp.update(
            db_session,
            profile,
            docker_image="repo/a:2",
            env={"X": "1"},
            is_builtin=True,  # ignored: not a mutable field
        )
        assert updated.docker_image == "repo/a:2"
        assert updated.env == {"X": "1"}
        assert updated.is_builtin is False

    @pytest.mark.asyncio
    async def test_delete_non_builtin(self, db_session: AsyncSession):
        profile = await cp.create(
            db_session, name="tmp", kind="generic", docker_image="repo/a:1"
        )
        await cp.delete(db_session, profile)
        assert await cp.get_by_name(db_session, "tmp") is None

    @pytest.mark.asyncio
    async def test_delete_builtin_refused(
        self, db_session: AsyncSession, steam_profile
    ):
        with pytest.raises(ValueError):
            await cp.delete(db_session, steam_profile)
        # Still present after refused delete.
        assert await cp.get_by_name(db_session, "steam") is not None


# ── Merge logic (resolve_launch_config) ──────────────────────────────────────


class TestResolveLaunchConfig:
    @pytest.mark.asyncio
    async def test_default_profile_used(
        self, db_session: AsyncSession, steam_profile
    ):
        # A game referencing no profile falls back to the builtin "steam"
        # profile → same image/runtime_profile as today.
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg == {
            "docker_image": STEAM_IMAGE,
            "runtime_profile": "gow-app",
            "app_env": {},
        }

    @pytest.mark.asyncio
    async def test_per_game_image_override(
        self, db_session: AsyncSession, steam_profile
    ):
        cfg = await cp.resolve_launch_config(
            db_session, _media({"docker_image": "custom/img:tag"})
        )
        assert cfg["docker_image"] == "custom/img:tag"
        assert cfg["runtime_profile"] == "gow-app"

    @pytest.mark.asyncio
    async def test_env_merge_order(self, db_session: AsyncSession):
        await cp.create(
            db_session,
            name="withenv",
            kind="generic",
            docker_image="repo/a:1",
            runtime_profile="gow-app",
            env={"A": "1", "B": "2"},
        )
        cfg = await cp.resolve_launch_config(
            db_session,
            _media({"profile": "withenv", "env": {"B": "override", "C": "3"}}),
        )
        # Per-game env wins over profile env; keys union.
        assert cfg["app_env"] == {"A": "1", "B": "override", "C": "3"}

    @pytest.mark.asyncio
    async def test_profile_ref_by_name_and_guid(self, db_session: AsyncSession):
        profile = await cp.create(
            db_session,
            name="generic",
            kind="generic",
            docker_image="repo/g:1",
            runtime_profile="gow-app",
        )
        by_name = await cp.resolve_launch_config(
            db_session, _media({"profile": "generic"})
        )
        assert by_name["docker_image"] == "repo/g:1"

        by_guid = await cp.resolve_launch_config(
            db_session, _media({"profile": str(profile.guid)})
        )
        assert by_guid["docker_image"] == "repo/g:1"

    @pytest.mark.asyncio
    async def test_no_profile_degrades(self, db_session: AsyncSession):
        # Empty DB (no "steam" profile): degrade gracefully — image from the
        # per-game override (or None), runtime_profile None, only game env.
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg == {
            "docker_image": None,
            "runtime_profile": None,
            "app_env": {},
        }

        cfg2 = await cp.resolve_launch_config(
            db_session, _media({"docker_image": "custom/img:tag", "env": {"K": "v"}})
        )
        assert cfg2 == {
            "docker_image": "custom/img:tag",
            "runtime_profile": None,
            "app_env": {"K": "v"},
        }
