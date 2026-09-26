"""Platform resolution from ROM paths + the backfill that persists it.

A ROM collection is laid out one directory per system, and several systems share
a file extension (``.bin`` is Atari 2600 *and* Mega Drive *and* a raw PSX track;
``.chd`` is Mega-CD *and* PSX). Resolving purely from the extension therefore
mislabels whole ROM sets — 841 Atari 2600 ``.bin`` files came out as "Sega
Genesis" and booted the wrong libretro core. Lock the directory-aware
resolution, the BIOS exclusion, and the backfill's idempotency.
"""

import pytest

from streamarr.services.game_platforms import (
    bios_dir_for,
    is_non_game_path,
    normalize_platform,
    platform_from_extension,
    platform_from_path,
    platform_label,
    platform_from_release_title,
    requires_bios,
    retro_core_for,
)


class TestDirectoryAwarePlatform:
    """``platform_from_path``: ROM-set directory wins for ambiguous extensions."""

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            # The whole point: same extension, different systems.
            ("/library/games/roms/atari2600/Moon Patrol (1983).bin", "atari2600"),
            ("/library/games/roms/megadrive/Sonic (Europe).bin", "genesis"),
            ("/library/games/roms/psx/Some Game.bin", "psx"),
            # .chd is Mega-CD and PSX.
            ("/library/games/roms/megacd/Sonic CD (Europe).chd", "megacd"),
            ("/library/games/roms/psx/Final Fantasy VII.chd", "psx"),
            # Archives are arcade by default but 3DO ships them too.
            ("/library/games/roms/3do/Road Rash (USA).7z", "3do"),
        ],
    )
    def test_ambiguous_extension_resolved_by_directory(self, path, expected):
        assert platform_from_path(path) == expected

    def test_unambiguous_extension_beats_directory(self):
        # A stray .z64 in the wrong folder is still an N64 ROM.
        assert platform_from_path("/roms/atari2600/misfiled.z64") == "n64"

    @pytest.mark.parametrize(
        ("path", "expected"),
        [
            ("/roms/nes/Zelda (USA).nes", "nes"),
            ("/roms/snes/Rock n' Roll Racing (Europe).sfc", "snes"),
            ("/roms/gb/Balloon Kid (USA, Europe).gb", "gb"),
            ("/roms/gbc/Hugo (Europe).gbc", "gbc"),
            ("/roms/n64/Harvest Moon 64 (U) [!].z64", "n64"),
            ("/roms/gamegear/Sonic (Europe).gg", "gamegear"),
            ("/roms/mastersystem/Alex Kidd.sms", "mastersystem"),
            ("/roms/psx/Shadow Tower.pbp", "psx"),
        ],
    )
    def test_unambiguous_extensions(self, path, expected):
        assert platform_from_path(path) == expected

    def test_no_platform_anywhere(self):
        assert platform_from_path("/roms/unknown/file.qqq") is None
        assert platform_from_path(None) is None

    def test_extension_only_helper_still_available(self):
        # platform_from_extension keeps its extension-only contract; it just
        # can't disambiguate, which is why platform_from_path exists.
        assert platform_from_extension("/roms/atari2600/x.bin") == "genesis"
        assert platform_from_extension("/roms/n64/x.z64") == "n64"


class TestGameGearSplitFromMasterSystem:
    """Game Gear was aliased onto ``mastersystem``, so ``.gg`` lost its identity."""

    def test_game_gear_is_its_own_platform(self):
        assert normalize_platform("gamegear") == "gamegear"
        assert normalize_platform("Game Gear") == "gamegear"
        assert normalize_platform("Sega Game Gear") == "gamegear"
        assert platform_from_path("/roms/gamegear/x.gg") == "gamegear"

    def test_master_system_unchanged(self):
        assert normalize_platform("sms") == "mastersystem"
        assert normalize_platform("Sega Master System") == "mastersystem"

    def test_both_run_on_genesis_plus_gx(self):
        assert retro_core_for("gamegear") == "genesis_plus_gx"
        assert retro_core_for("mastersystem") == "genesis_plus_gx"


class TestNewlyRegisteredSystems:
    """Atari 2600 / Mega-CD / 3DO resolved to nothing and were unlaunchable."""

    @pytest.mark.parametrize(
        ("name", "slug", "core", "label"),
        [
            ("Atari 2600", "atari2600", "stella", "Atari 2600"),
            ("atari2600", "atari2600", "stella", "Atari 2600"),
            ("Sega CD", "megacd", "genesis_plus_gx", "Sega Mega-CD"),
            ("megacd", "megacd", "genesis_plus_gx", "Sega Mega-CD"),
            ("3do", "3do", "opera", "3DO"),
        ],
    )
    def test_registered(self, name, slug, core, label):
        assert normalize_platform(name) == slug
        assert retro_core_for(slug) == core
        assert platform_label(slug) == label

    def test_release_titles_parse(self):
        assert platform_from_release_title("Pitfall (Atari 2600) (USA)") == "atari2600"
        assert platform_from_release_title("Sonic CD (Mega-CD) (Europe)") == "megacd"
        assert platform_from_release_title("Road Rash (3DO)") == "3do"


class TestBiosExclusion:
    """BIOS images are not games; they were imported as titles like "scph1001"."""

    @pytest.mark.parametrize(
        "path",
        [
            "/library/games/roms/bios/megacd/bios_CD_U.bin",
            "/library/games/roms/bios/psx/scph1001.bin",
            # The other layout the same collection uses.
            "/library/games/roms/psx/BIOS Files/scph1001.bin",
            "/library/games/roms/firmware/thing.bin",
        ],
    )
    def test_bios_paths_flagged(self, path):
        assert is_non_game_path(path) is True

    @pytest.mark.parametrize(
        "path",
        [
            "/library/games/roms/nes/Zelda (USA).nes",
            # A game legitimately named after a non-game directory keyword must
            # NOT be dropped — only directory components count.
            "/library/games/roms/nes/System.nes",
            "/library/games/roms/snes/BIOS Simulator.sfc",
        ],
    )
    def test_real_games_not_flagged(self, path):
        assert is_non_game_path(path) is False

    def test_none_is_not_bios(self):
        assert is_non_game_path(None) is False


class TestBiosRequirements:
    """Which platforms need a BIOS — drives the ``/system`` mount at launch."""

    @pytest.mark.parametrize(
        ("slug", "bios_dir"),
        [("psx", "psx"), ("megacd", "megacd"), ("3do", "3do"), ("arcade", "arcade")],
    )
    def test_platforms_needing_bios(self, slug, bios_dir):
        assert bios_dir_for(slug) == bios_dir
        assert requires_bios(slug) is True

    @pytest.mark.parametrize(
        "slug",
        ["nes", "snes", "n64", "gb", "gbc", "gba", "genesis", "mastersystem",
         "gamegear", "atari2600", "pcengine"],
    )
    def test_cartridge_systems_need_none(self, slug):
        # A cartridge system boots straight from the ROM; mounting a system dir
        # for it would be pointless (and hides real BIOS problems).
        assert bios_dir_for(slug) is None
        assert requires_bios(slug) is False

    def test_unknown_platform_needs_none(self):
        assert bios_dir_for(None) is None
        assert bios_dir_for("not-a-platform") is None
        assert requires_bios(None) is False


class TestOcarinaRegressionStillHolds:
    """The platform gate that the N64/PC-Port fix introduced must keep working."""

    def test_pc_port_still_wins_over_n64_tag(self):
        title = "The.Legend.of.Zelda.Ocarina.of.Time.N64.PC-Port.MULTi3-x"
        assert platform_from_release_title(title) == "pc"

    def test_no_intro_rom_has_no_platform_tag(self):
        assert platform_from_release_title("Super Mario 64 (USA)") is None
