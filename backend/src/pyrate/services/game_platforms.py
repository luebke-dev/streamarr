"""Canonical game-platform normalisation.

The single source of truth for turning the many spellings of a platform —
IGDB names ("Nintendo 64"), release-title tags ("N64", "PC-Port"), ROM
extensions (".z64") — into one canonical slug, and for knowing which
platforms the retro (libretro) container can actually run and with which core.

Used by release matching/scoring (does this release's platform belong to the
game?) and, going forward, by the launch resolver (which core to boot).
"""

import re

# Canonical platform registry.
#   slug -> (aliases, retro_core)
# ``retro_core`` is the libretro core basename in the pyrate-retro image when
# the platform is emulatable here, else ``None`` (streamed/PC/modern console).
# Aliases are matched case-insensitively after normalisation.
_PLATFORMS: dict[str, tuple[tuple[str, ...], str | None]] = {
    "nes": (("nintendo entertainment system", "famicom", "nes", "fc"), "nestopia"),
    "snes": (
        ("super nintendo entertainment system", "super famicom", "super nintendo", "snes", "sfc"),
        "snes9x",
    ),
    "n64": (("nintendo 64", "n64", "64dd", "nintendo 64dd"), "mupen64plus_next"),
    "gb": (("game boy", "gameboy", "gb"), "gambatte"),
    "gbc": (("game boy color", "gameboy color", "gbc"), "gambatte"),
    "gba": (("game boy advance", "gameboy advance", "gba"), "mgba"),
    "genesis": (
        ("sega mega drive/genesis", "sega mega drive", "mega drive", "megadrive", "sega genesis", "genesis", "md"),
        "genesis_plus_gx",
    ),
    "mastersystem": (
        ("sega master system", "master system", "sms", "sega game gear", "game gear", "gamegear", "gg"),
        "genesis_plus_gx",
    ),
    "pcengine": (
        ("pc engine", "turbografx-16", "turbografx", "tg16", "turbografx-16/pc engine", "pce"),
        "mednafen_pce_fast",
    ),
    "psx": (("playstation", "sony playstation", "ps1", "psx", "ps one", "psone"), "pcsx_rearmed"),
    "arcade": (("arcade", "mame", "neo geo", "neogeo", "fbneo", "fba"), "fbneo"),
    # Non-emulated here (streamed native / modern) — no retro core.
    "pc": (("pc (microsoft windows)", "pc", "microsoft windows", "windows", "win", "linux", "mac", "macos", "dos"), None),
    "ps2": (("playstation 2", "ps2"), None),
    "ps3": (("playstation 3", "ps3"), None),
    "ps4": (("playstation 4", "ps4"), None),
    "ps5": (("playstation 5", "ps5"), None),
    "xbox": (("xbox", "xbox 360", "xbox one", "xbox series", "xb0x"), None),
    "switch": (("nintendo switch", "switch", "nsw"), None),
    "wii": (("wii",), None),
    "wiiu": (("wii u", "wiiu"), None),
    "3ds": (("nintendo 3ds", "3ds"), None),
    "ds": (("nintendo ds", "nds", "ds"), None),
    "gamecube": (("nintendo gamecube", "gamecube", "ngc", "gcn"), None),
    "dreamcast": (("dreamcast", "sega dreamcast", "dc"), None),
    "saturn": (("sega saturn", "saturn"), None),
}

# Reverse alias lookup, longest-alias-first so "super nintendo" wins over "nintendo".
_ALIAS_TO_SLUG: list[tuple[str, str]] = sorted(
    ((alias, slug) for slug, (aliases, _core) in _PLATFORMS.items() for alias in aliases),
    key=lambda kv: len(kv[0]),
    reverse=True,
)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text).strip().lower())


def normalize_platform(name: str | None) -> str | None:
    """Map an IGDB/free-text platform name to a canonical slug, or ``None``."""
    if not name:
        return None
    n = _norm(name)
    for alias, slug in _ALIAS_TO_SLUG:
        if n == alias:
            return slug
    # Loose contains match as a fallback (e.g. "Nintendo 64 (NA)").
    for alias, slug in _ALIAS_TO_SLUG:
        if re.search(rf"\b{re.escape(alias)}\b", n):
            return slug
    return None


def normalize_platforms(names) -> set[str]:
    """Normalise a collection of platform names to a set of canonical slugs."""
    out: set[str] = set()
    for name in names or []:
        slug = normalize_platform(name)
        if slug:
            out.add(slug)
    return out


# Release-title platform tags. A "PC-Port"/"PC Port" is a PC release even when
# the title also names the original console (e.g. "...N64.PC-Port..."), so the
# PC patterns are checked FIRST and win.
_PC_PORT_RE = re.compile(r"\bpc[-_. ]?port\b", re.IGNORECASE)
_RELEASE_TAG_PATTERNS: list[tuple[re.Pattern, str]] = [
    (re.compile(r"\b(n64|nintendo[ ._-]?64)\b", re.IGNORECASE), "n64"),
    (re.compile(r"\b(snes|super[ ._-]?nintendo|super[ ._-]?famicom|sfc)\b", re.IGNORECASE), "snes"),
    (re.compile(r"\b(nes|famicom)\b", re.IGNORECASE), "nes"),
    (re.compile(r"\b(gba|game[ ._-]?boy[ ._-]?advance)\b", re.IGNORECASE), "gba"),
    (re.compile(r"\b(gbc|game[ ._-]?boy[ ._-]?color)\b", re.IGNORECASE), "gbc"),
    (re.compile(r"\b(gb|game[ ._-]?boy)\b", re.IGNORECASE), "gb"),
    (re.compile(r"\b(genesis|mega[ ._-]?drive|megadrive|smd)\b", re.IGNORECASE), "genesis"),
    (re.compile(r"\b(sms|master[ ._-]?system|game[ ._-]?gear)\b", re.IGNORECASE), "mastersystem"),
    (re.compile(r"\b(pc[ ._-]?engine|turbografx|tg16|pce)\b", re.IGNORECASE), "pcengine"),
    (re.compile(r"\b(psx|ps1|playstation)\b", re.IGNORECASE), "psx"),
    (re.compile(r"\b(ps2)\b", re.IGNORECASE), "ps2"),
    (re.compile(r"\b(switch|nsw)\b", re.IGNORECASE), "switch"),
    (re.compile(r"\b(wii[ ._-]?u)\b", re.IGNORECASE), "wiiu"),
    (re.compile(r"\b(wii)\b", re.IGNORECASE), "wii"),
    (re.compile(r"\b(3ds)\b", re.IGNORECASE), "3ds"),
    (re.compile(r"\b(nds)\b", re.IGNORECASE), "ds"),
    (re.compile(r"\b(gamecube|ngc)\b", re.IGNORECASE), "gamecube"),
    (re.compile(r"\b(iso|gog|repack|steam|codex|plaza|skidrow|fitgirl|dodi|rune|reloaded|win64|win32)\b", re.IGNORECASE), "pc"),
]


def platform_from_release_title(title: str | None) -> str | None:
    """Best-effort parse of the platform a release targets, or ``None``.

    ``None`` means the title carries no platform hint (common for no-intro ROM
    names like "Game (Europe)") — the caller should then fall back to title
    matching rather than rejecting the release.
    """
    if not title:
        return None
    if _PC_PORT_RE.search(title):
        return "pc"
    for pattern, slug in _RELEASE_TAG_PATTERNS:
        if pattern.search(title):
            return slug
    return None


def retro_core_for(slug: str | None) -> str | None:
    """The libretro core that runs this platform in the retro container, or None."""
    if not slug:
        return None
    entry = _PLATFORMS.get(slug)
    return entry[1] if entry else None


def is_retro_platform(slug: str | None) -> bool:
    """Whether the platform is emulatable in the pyrate-retro container."""
    return retro_core_for(slug) is not None
