"""Retro (libretro) launch resolution: pinned core + BIOS system mount.

Two things the container cannot work out on its own:

* **The core.** ``run.sh`` guesses it from the ROM extension, but ``.bin`` is an
  Atari 2600 ROM *and* a Mega Drive ROM *and* a raw PSX track — guessing booted
  841 Atari games on ``genesis_plus_gx``. Only the backend knows which ROM set a
  file came from, so it must pin ``RETRO_CORE``.
* **The BIOS.** PSX / Mega-CD / 3DO cores refuse to boot without one, and
  RetroArch looks it up by bare filename in its system directory. Nothing ever
  mounted ``/system``, so those systems could not start at all.

Both are locked here end-to-end through ``resolve_launch_config``.
"""

import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.container_profile import ContainerProfile  # noqa: F401
from streamarr.models.media import (
    AvailabilityStatus,
    MediaFile,
    MediaItem,
    MediaType,
)
from streamarr.services import container_profiles as cp

RETRO_IMAGE = "ghcr.io/luebke-dev/pyrate-retro:latest"


@pytest_asyncio.fixture
async def retro_profile(db_session: AsyncSession) -> ContainerProfile:
    """The builtin libretro profile, as its migration seeds it."""
    return await cp.create(
        db_session,
        name="retro",
        kind="libretro",
        docker_image=RETRO_IMAGE,
        runtime_profile="gow-app",
        env={"RETRO_ROM": "{app_ref}", "RETRO_SYSTEM_DIR": "/system"},
        state_scope="game",
    )


async def _game_with_rom(db: AsyncSession, rom_path: str) -> MediaItem:
    """A GAMES item whose single MediaFile lives at ``rom_path``."""
    item = MediaItem(
        guid=uuid.uuid4(),
        title="Test Game",
        media_type=MediaType.GAMES,
        availability_status=AvailabilityStatus.AVAILABLE,
        extra_data={"lightrays": {"profile": "retro"}},
    )
    db.add(item)
    await db.flush()
    db.add(
        MediaFile(
            guid=uuid.uuid4(),
            media_item_guid=item.guid,
            file_path=rom_path,
            file_name=rom_path.rsplit("/", 1)[-1],
        )
    )
    await db.commit()
    await db.refresh(item)
    return item


def _mount_for(cfg: dict, container_dir: str) -> dict | None:
    return next(
        (m for m in cfg["app_mounts"] if m["container"] == container_dir), None
    )


class TestCoreIsPinned:
    """``RETRO_CORE`` must come from the ROM's path, not the container's guess."""

    @pytest.mark.parametrize(
        ("rom_path", "expected_core"),
        [
            # The regression: identical extension, three different cores.
            ("/library/games/roms/atari2600/Moon Patrol.bin", "stella"),
            ("/library/games/roms/megadrive/Sonic.bin", "genesis_plus_gx"),
            ("/library/games/roms/psx/Some Game.bin", "pcsx_rearmed"),
            # Newly registered systems.
            ("/library/games/roms/3do/Strahl.7z", "opera"),
            ("/library/games/roms/megacd/Sonic CD.chd", "genesis_plus_gx"),
            # Game Gear split back out of mastersystem.
            ("/library/games/roms/gamegear/Sonic.gg", "genesis_plus_gx"),
            # Unambiguous extensions keep working.
            ("/library/games/roms/n64/Mario.z64", "mupen64plus_next"),
            ("/library/games/roms/nes/Zelda.nes", "nestopia"),
            ("/library/games/roms/snes/Chrono.sfc", "snes9x"),
        ],
    )
    @pytest.mark.asyncio
    async def test_core_pinned_from_rom_path(
        self, db_session: AsyncSession, retro_profile, rom_path, expected_core
    ):
        game = await _game_with_rom(db_session, rom_path)

        cfg = await cp.resolve_launch_config(db_session, game)

        assert cfg["app_env"]["RETRO_CORE"] == expected_core
        assert cfg["docker_image"] == RETRO_IMAGE

    @pytest.mark.asyncio
    async def test_rom_is_mounted_and_referenced(
        self, db_session: AsyncSession, retro_profile
    ):
        game = await _game_with_rom(
            db_session, "/library/games/roms/n64/Super Mario 64.z64"
        )

        cfg = await cp.resolve_launch_config(db_session, game)

        rom_mount = _mount_for(cfg, "/rom")
        assert rom_mount is not None
        assert rom_mount["ro"] is True
        # RETRO_ROM is the profile's {app_ref} filled with the in-container path.
        assert cfg["app_env"]["RETRO_ROM"] == "/rom/Super Mario 64.z64"

    @pytest.mark.asyncio
    async def test_explicit_per_game_env_wins(
        self, db_session: AsyncSession, retro_profile
    ):
        # An admin override must not be clobbered by the derived core.
        game = await _game_with_rom(
            db_session, "/library/games/roms/atari2600/Moon Patrol.bin"
        )
        game.extra_data = {
            "lightrays": {"profile": "retro", "env": {"RETRO_CORE": "stella_custom"}}
        }
        await db_session.commit()

        cfg = await cp.resolve_launch_config(db_session, game)

        assert cfg["app_env"]["RETRO_CORE"] == "stella_custom"


class TestBiosSystemMount:
    """PSX / Mega-CD / 3DO need their BIOS mounted flat at ``/system``."""

    @pytest.mark.asyncio
    async def test_psx_gets_bios_mount(
        self, db_session: AsyncSession, retro_profile, monkeypatch
    ):
        monkeypatch.setattr(cp.os.path, "isdir", lambda _p: True)
        game = await _game_with_rom(db_session, "/library/games/roms/psx/Jet Moto.pbp")

        cfg = await cp.resolve_launch_config(db_session, game)

        system_mount = _mount_for(cfg, "/system")
        assert system_mount is not None
        assert system_mount["ro"] is True
        # Mounted flat: the per-system folder itself, so the core finds
        # "scph1001.bin" directly inside /system.
        assert system_mount["host"].endswith("/roms/bios/psx")

    @pytest.mark.asyncio
    async def test_megacd_gets_bios_mount(
        self, db_session: AsyncSession, retro_profile, monkeypatch
    ):
        monkeypatch.setattr(cp.os.path, "isdir", lambda _p: True)
        game = await _game_with_rom(
            db_session, "/library/games/roms/megacd/Sonic CD.chd"
        )

        cfg = await cp.resolve_launch_config(db_session, game)

        assert _mount_for(cfg, "/system")["host"].endswith("/roms/bios/megacd")

    @pytest.mark.parametrize(
        "rom_path",
        [
            "/library/games/roms/n64/Mario.z64",
            "/library/games/roms/nes/Zelda.nes",
            "/library/games/roms/atari2600/Moon Patrol.bin",
            "/library/games/roms/gamegear/Sonic.gg",
        ],
    )
    @pytest.mark.asyncio
    async def test_cartridge_systems_get_no_bios_mount(
        self, db_session: AsyncSession, retro_profile, monkeypatch, rom_path
    ):
        # Even when a BIOS directory exists, a cartridge system must not get one.
        monkeypatch.setattr(cp.os.path, "isdir", lambda _p: True)
        game = await _game_with_rom(db_session, rom_path)

        cfg = await cp.resolve_launch_config(db_session, game)

        assert _mount_for(cfg, "/system") is None

    @pytest.mark.asyncio
    async def test_missing_bios_dir_is_skipped_not_fatal(
        self, db_session: AsyncSession, retro_profile, monkeypatch
    ):
        # A collection without BIOS files still launches (the core then reports
        # the missing BIOS) rather than failing on a non-existent bind source.
        monkeypatch.setattr(cp.os.path, "isdir", lambda _p: False)
        game = await _game_with_rom(db_session, "/library/games/roms/psx/Jet Moto.pbp")

        cfg = await cp.resolve_launch_config(db_session, game)

        assert _mount_for(cfg, "/system") is None
        assert _mount_for(cfg, "/rom") is not None
        assert cfg["app_env"]["RETRO_CORE"] == "pcsx_rearmed"


class TestNonRetroUnaffected:
    @pytest.mark.asyncio
    async def test_steam_game_gets_no_rom_or_bios(self, db_session: AsyncSession):
        await cp.create(
            db_session,
            name="steam",
            kind="steam",
            docker_image="ghcr.io/games-on-whales/steam:edge",
            runtime_profile="gow-app",
            state_scope="user",
        )
        steam_game = SimpleNamespace(
            extra_data={"lightrays": {"profile": "steam", "app_ref": "440"}}
        )

        cfg = await cp.resolve_launch_config(db_session, steam_game)

        assert cfg["app_mounts"] == []
        assert "RETRO_CORE" not in cfg["app_env"]
