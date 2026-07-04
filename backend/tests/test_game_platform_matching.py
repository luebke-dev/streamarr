"""Platform-aware game release matching (the Ocarina/N64 regression).

An N64 game's indexer search returned both a fan-made "N64 PC-Port" and the
real N64 ROMs, but the ROMs (no-intro naming: "Legend of Zelda, The - … (Europe)")
fell below the fuzzy threshold and only the PC port matched. Two guards now
exist: a platform gate (reject releases whose named platform isn't one of the
game's) and no-intro token-containment recovery. Lock both.
"""

from pyrate.services.game_platforms import (
    is_retro_platform,
    normalize_platforms,
    platform_from_release_title,
    retro_core_for,
)
from pyrate.services.release_matcher import ReleaseMatcher

GAME = "The Legend of Zelda: Ocarina of Time"
# Ocarina's IGDB platforms.
OCARINA_PLATFORMS = normalize_platforms(["Wii", "Wii U", "Nintendo 64", "64DD"])

PC_PORT = "The.Legend.of.Zelda.Ocarina.of.Time.N64.PC-Port.MULTi3-x.X.RIDDICK.X.x"
N64_ROM = "Legend of Zelda, The - Ocarina of Time & Master Quest (Europe) (En,Fr,De)"


def test_platform_normalization():
    assert OCARINA_PLATFORMS == {"n64", "wii", "wiiu"}
    assert normalize_platforms(["Super Nintendo Entertainment System"]) == {"snes"}
    assert normalize_platforms(["PC (Microsoft Windows)"]) == {"pc"}


def test_release_platform_parsing():
    # PC-Port wins even though the title also says N64.
    assert platform_from_release_title(PC_PORT) == "pc"
    # A no-intro ROM name has no platform tag.
    assert platform_from_release_title(N64_ROM) is None
    assert platform_from_release_title("Super Mario 64 (USA)") is None


def test_pc_port_rejected_for_n64_game():
    m = ReleaseMatcher.match_game_release(PC_PORT, GAME, 1998, game_platforms=OCARINA_PLATFORMS)
    assert m.is_match is False


def test_n64_rom_matches_via_token_containment():
    m = ReleaseMatcher.match_game_release(N64_ROM, GAME, 1998, game_platforms=OCARINA_PLATFORMS)
    assert m.is_match is True


def test_without_platforms_falls_back_to_title():
    # No platform info -> don't reject; title still has to match.
    m = ReleaseMatcher.match_game_release(N64_ROM, GAME, 1998, game_platforms=None)
    assert m.is_match is True


def test_retro_core_mapping():
    assert retro_core_for("n64") == "mupen64plus_next"
    assert is_retro_platform("n64") is True
    assert is_retro_platform("pc") is False
    assert is_retro_platform("ps5") is False
