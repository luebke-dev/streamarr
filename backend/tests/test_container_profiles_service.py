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
    """Seed the builtin default ``steam`` profile (as the migration would).

    The migration marks the builtin steam profile ``state_scope="user"`` so a
    user's Steam games share one persistent ``/home/retro`` (single login +
    library); the fixture mirrors that.
    """
    return await cp.create(
        db_session,
        name="steam",
        kind="steam",
        docker_image=STEAM_IMAGE,
        runtime_profile="gow-app",
        env={},
        is_builtin=True,
        state_scope="user",
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
    async def test_create_state_scope(self, db_session: AsyncSession):
        # Defaults to "game"; an explicit "user" scope is persisted.
        default = await cp.create(
            db_session, name="sg", kind="generic", docker_image="repo/a:1"
        )
        assert default.state_scope == "game"

        user_scoped = await cp.create(
            db_session,
            name="su",
            kind="steam",
            docker_image="repo/a:1",
            state_scope="user",
        )
        assert user_scoped.state_scope == "user"

    @pytest.mark.asyncio
    async def test_update_state_scope(self, db_session: AsyncSession):
        profile = await cp.create(
            db_session, name="ss", kind="generic", docker_image="repo/a:1"
        )
        assert profile.state_scope == "game"
        updated = await cp.update(db_session, profile, state_scope="user")
        assert updated.state_scope == "user"

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
        # profile → same image/runtime_profile as today, and its user-scoped
        # state_scope/profile_name surface for the app_id computation.
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg == {
            "docker_image": STEAM_IMAGE,
            "runtime_profile": "gow-app",
            "app_env": {},
            "app_mounts": [],
            "state_scope": "user",
            "profile_name": "steam",
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
            "app_mounts": [],
            "state_scope": "game",
            "profile_name": None,
        }

        cfg2 = await cp.resolve_launch_config(
            db_session, _media({"docker_image": "custom/img:tag", "env": {"K": "v"}})
        )
        assert cfg2 == {
            "docker_image": "custom/img:tag",
            "runtime_profile": None,
            "app_env": {"K": "v"},
            "app_mounts": [],
            "state_scope": "game",
            "profile_name": None,
        }


class TestAppRefTemplate:
    """The profile holds the launch command once via `{app_ref}`; each game
    supplies only its own id (or none → template dropped)."""

    @staticmethod
    async def _steam_with_template(db_session: AsyncSession) -> ContainerProfile:
        return await cp.create(
            db_session,
            name="steam",
            kind="steam",
            docker_image=STEAM_IMAGE,
            runtime_profile="gow-app",
            env={"STEAM_STARTUP_FLAGS": "-bigpicture steam://rungameid/{app_ref}"},
            is_builtin=True,
        )

    @pytest.mark.asyncio
    async def test_app_ref_substituted(self, db_session: AsyncSession):
        await self._steam_with_template(db_session)
        cfg = await cp.resolve_launch_config(db_session, _media({"app_ref": "440"}))
        assert cfg["app_env"] == {
            "STEAM_STARTUP_FLAGS": "-bigpicture steam://rungameid/440"
        }

    @pytest.mark.asyncio
    async def test_missing_app_ref_drops_template(self, db_session: AsyncSession):
        # No app_ref: the placeholder can't be filled, so the entry is dropped
        # (falls back to the container's default, e.g. Steam Big Picture) —
        # existing games without an app id must not regress.
        await self._steam_with_template(db_session)
        cfg = await cp.resolve_launch_config(db_session, _media({}))
        assert "STEAM_STARTUP_FLAGS" not in cfg["app_env"]
        assert cfg["app_env"] == {}

    @pytest.mark.asyncio
    async def test_per_game_env_still_merges_with_app_ref(self, db_session: AsyncSession):
        await self._steam_with_template(db_session)
        cfg = await cp.resolve_launch_config(
            db_session, _media({"app_ref": "70", "env": {"EXTRA": "1"}})
        )
        assert cfg["app_env"] == {
            "STEAM_STARTUP_FLAGS": "-bigpicture steam://rungameid/70",
            "EXTRA": "1",
        }


# ── app_mounts resolution ────────────────────────────────────────────────────


class TestResolveAppMounts:
    """`resolve_launch_config` surfaces sanctioned host→container bind mounts
    under ``app_mounts`` — profile-level mounts first, per-game mounts after,
    each normalised to ``{host,container,ro}`` with invalid entries dropped."""

    @pytest.mark.asyncio
    async def test_empty_when_no_mounts(
        self, db_session: AsyncSession, steam_profile
    ):
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg["app_mounts"] == []

    @pytest.mark.asyncio
    async def test_game_mounts_normalised(
        self, db_session: AsyncSession, steam_profile
    ):
        cfg = await cp.resolve_launch_config(
            db_session,
            _media(
                {
                    "mounts": [
                        {"host": "/srv/games/wine", "container": "/games/wine"},
                        {
                            "host": "/srv/games/ro",
                            "container": "/games/ro",
                            "ro": True,
                        },
                    ]
                }
            ),
        )
        assert cfg["app_mounts"] == [
            {"host": "/srv/games/wine", "container": "/games/wine", "ro": False},
            {"host": "/srv/games/ro", "container": "/games/ro", "ro": True},
        ]

    @pytest.mark.asyncio
    async def test_ro_defaults_false(self, db_session: AsyncSession, steam_profile):
        cfg = await cp.resolve_launch_config(
            db_session,
            _media({"mounts": [{"host": "/a", "container": "/b"}]}),
        )
        assert cfg["app_mounts"] == [{"host": "/a", "container": "/b", "ro": False}]

    @pytest.mark.asyncio
    async def test_aliases_accepted(self, db_session: AsyncSession, steam_profile):
        cfg = await cp.resolve_launch_config(
            db_session,
            _media(
                {
                    "mounts": [
                        {
                            "source": "/host/wine",
                            "target": "/games/wine",
                            "read_only": True,
                        }
                    ]
                }
            ),
        )
        assert cfg["app_mounts"] == [
            {"host": "/host/wine", "container": "/games/wine", "ro": True}
        ]

    @pytest.mark.asyncio
    async def test_invalid_entries_dropped(
        self, db_session: AsyncSession, steam_profile
    ):
        cfg = await cp.resolve_launch_config(
            db_session,
            _media(
                {
                    "mounts": [
                        {"host": "", "container": "/b"},  # empty host
                        {"host": "/a"},  # missing container
                        {"container": "/b"},  # missing host
                        {"host": "relative/path", "container": "/b"},  # not abs
                        {"host": "/a", "container": "rel/dir"},  # container not abs
                        "not-a-dict",  # wrong type
                        {"host": "/ok", "container": "/ok"},  # valid → kept
                    ]
                }
            ),
        )
        assert cfg["app_mounts"] == [{"host": "/ok", "container": "/ok", "ro": False}]

    @pytest.mark.asyncio
    async def test_no_profile_still_returns_game_mounts(
        self, db_session: AsyncSession
    ):
        # Empty DB (no profile resolves): app_mounts still carries the game's
        # own mounts.
        cfg = await cp.resolve_launch_config(
            db_session,
            _media({"mounts": [{"host": "/a", "container": "/b"}]}),
        )
        assert cfg["app_mounts"] == [{"host": "/a", "container": "/b", "ro": False}]

    @pytest.mark.asyncio
    async def test_profile_mounts_precede_game_mounts(
        self, db_session: AsyncSession
    ):
        # A profile that carries mounts (via a duck-typed attribute the model
        # may grow later) contributes them first; per-game mounts follow.
        profile = await cp.create(
            db_session, name="withmounts", kind="generic", docker_image="repo/a:1"
        )
        # Simulate a future profile-level mounts field via a plain attribute.
        profile.mounts = [{"host": "/profile/dir", "container": "/shared"}]
        cfg = await cp.resolve_launch_config(
            db_session,
            _media(
                {
                    "profile": "withmounts",
                    "mounts": [{"host": "/game/dir", "container": "/game"}],
                }
            ),
        )
        assert cfg["app_mounts"] == [
            {"host": "/profile/dir", "container": "/shared", "ro": False},
            {"host": "/game/dir", "container": "/game", "ro": False},
        ]


# ── state_scope resolution ───────────────────────────────────────────────────


class TestResolveStateScope:
    @pytest.mark.asyncio
    async def test_user_scope_for_steam_profile(
        self, db_session: AsyncSession, steam_profile
    ):
        # The user-scoped (steam) profile surfaces state_scope="user" and its
        # canonical name for the per-user state key.
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg["state_scope"] == "user"
        assert cfg["profile_name"] == "steam"

    @pytest.mark.asyncio
    async def test_game_scope_for_generic_profile(self, db_session: AsyncSession):
        # A profile created without an explicit scope is "game"-scoped.
        await cp.create(
            db_session, name="generic", kind="generic", docker_image="repo/g:1"
        )
        cfg = await cp.resolve_launch_config(
            db_session, _media({"profile": "generic"})
        )
        assert cfg["state_scope"] == "game"
        assert cfg["profile_name"] == "generic"

    @pytest.mark.asyncio
    async def test_game_scope_when_no_profile_resolves(self, db_session: AsyncSession):
        # Empty DB: no profile → default "game" scope, no profile name.
        cfg = await cp.resolve_launch_config(db_session, _media(None))
        assert cfg["state_scope"] == "game"
        assert cfg["profile_name"] is None


# ── app_id (persistent-state key) computation ────────────────────────────────


class TestComputeAppId:
    USER = "11111111-1111-1111-1111-111111111111"
    GAME = "22222222-2222-2222-2222-222222222222"

    def test_game_scope_keeps_per_game_key(self):
        assert (
            cp.compute_app_id(self.USER, self.GAME, "game")
            == f"{self.USER}-{self.GAME}"
        )

    def test_game_scope_ignores_profile_name(self):
        # Profile name is irrelevant when scope is per-game.
        assert (
            cp.compute_app_id(self.USER, self.GAME, "game", profile_name="steam")
            == f"{self.USER}-{self.GAME}"
        )

    def test_user_scope_drops_game_guid(self):
        # A stable per-user key that does NOT include the game guid, so all of
        # the user's games on this profile share one state.
        key = cp.compute_app_id(self.USER, self.GAME, "user", profile_name="steam")
        assert key == f"{self.USER}-steam"
        assert self.GAME not in key

    def test_user_scope_shared_across_games(self):
        other_game = "33333333-3333-3333-3333-333333333333"
        a = cp.compute_app_id(self.USER, self.GAME, "user", profile_name="steam")
        b = cp.compute_app_id(self.USER, other_game, "user", profile_name="steam")
        assert a == b

    def test_user_scope_fallback_when_no_name(self):
        assert (
            cp.compute_app_id(self.USER, self.GAME, "user", profile_name=None)
            == f"{self.USER}-app"
        )

    def test_user_scope_name_slugged_ascii_safe(self):
        # Admin-authored names are slugged to an ascii-safe, deterministic
        # token before use as a mount key.
        key = cp.compute_app_id(
            self.USER, self.GAME, "user", profile_name="Mön Steam!"
        )
        assert key == f"{self.USER}-MnSteam"
        assert all(ch.isascii() for ch in key)

    def test_user_scope_all_stripped_name_falls_back(self):
        # A name with no allowed chars slugs to empty → "app".
        assert (
            cp.compute_app_id(self.USER, self.GAME, "user", profile_name="の")
            == f"{self.USER}-app"
        )
