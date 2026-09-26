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
# ``retro_core`` is the libretro core basename in the streamarr-retro image when
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
        ("sega master system", "master system", "sms"),
        "genesis_plus_gx",
    ),
    "gamegear": (
        ("sega game gear", "game gear", "gamegear", "gg"),
        "genesis_plus_gx",
    ),
    "megacd": (
        ("sega cd", "mega-cd", "mega cd", "megacd", "sega mega-cd", "scd"),
        "genesis_plus_gx",
    ),
    "atari2600": (
        ("atari 2600", "atari2600", "2600", "vcs", "atari vcs"),
        "stella",
    ),
    "pcengine": (
        ("pc engine", "turbografx-16", "turbografx", "tg16", "turbografx-16/pc engine", "pce"),
        "mednafen_pce_fast",
    ),
    "psx": (("playstation", "sony playstation", "ps1", "psx", "ps one", "psone"), "pcsx_rearmed"),
    "arcade": (("arcade", "mame", "neo geo", "neogeo", "fbneo", "fba"), "fbneo"),
    "3do": (("3do", "3do interactive multiplayer", "panasonic 3do"), "opera"),
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
    (re.compile(r"\b(mega[ ._-]?cd|megacd|sega[ ._-]?cd|scd)\b", re.IGNORECASE), "megacd"),
    (re.compile(r"\b(gg|game[ ._-]?gear|gamegear)\b", re.IGNORECASE), "gamegear"),
    (re.compile(r"\b(sms|master[ ._-]?system)\b", re.IGNORECASE), "mastersystem"),
    (re.compile(r"\b(atari[ ._-]?2600|a2600|vcs)\b", re.IGNORECASE), "atari2600"),
    (re.compile(r"\b(3do)\b", re.IGNORECASE), "3do"),
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
    """Whether the platform is emulatable in the streamarr-retro container."""
    return retro_core_for(slug) is not None


# Human display labels for the platform picker.
_PLATFORM_LABELS: dict[str, str] = {
    "nes": "NES", "snes": "Super Nintendo", "n64": "Nintendo 64",
    "gb": "Game Boy", "gbc": "Game Boy Color", "gba": "Game Boy Advance",
    "genesis": "Sega Genesis", "mastersystem": "Master System",
    "gamegear": "Game Gear", "megacd": "Sega Mega-CD",
    "atari2600": "Atari 2600", "3do": "3DO",
    "pcengine": "PC Engine", "psx": "PlayStation", "arcade": "Arcade",
    "pc": "PC", "ps2": "PlayStation 2", "ps3": "PlayStation 3",
    "ps4": "PlayStation 4", "ps5": "PlayStation 5", "xbox": "Xbox",
    "switch": "Nintendo Switch", "wii": "Wii", "wiiu": "Wii U",
    "3ds": "Nintendo 3DS", "ds": "Nintendo DS", "gamecube": "GameCube",
    "dreamcast": "Dreamcast", "saturn": "Sega Saturn",
}


def platform_label(slug: str | None) -> str:
    """Human label for a platform slug (falls back to the slug)."""
    return _PLATFORM_LABELS.get(slug or "", (slug or "").upper())


# File extension → platform slug. THE single source of truth for which
# extensions are game files and what platform they belong to. ``ROM_EXTENSIONS``
# (the console-ROM subset the library scanner ingests) is derived from this, so
# the two can never drift — a launchable extension always resolves a platform.
_EXT_TO_PLATFORM: dict[str, str] = {
    ".nes": "nes", ".fds": "nes", ".unf": "nes",
    ".sfc": "snes", ".smc": "snes", ".swc": "snes", ".fig": "snes", ".bs": "snes",
    ".n64": "n64", ".z64": "n64", ".v64": "n64", ".ndd": "n64",
    ".gb": "gb", ".dmg": "gb", ".gbc": "gbc",
    ".gba": "gba",
    ".md": "genesis", ".gen": "genesis", ".smd": "genesis", ".sgd": "genesis",
    ".68k": "genesis",
    ".sms": "mastersystem", ".sg": "mastersystem",
    ".gg": "gamegear",
    ".pce": "pcengine", ".sgx": "pcengine",
    ".cue": "psx", ".pbp": "psx", ".m3u": "psx",
    ".nds": "ds", ".3ds": "3ds",
    ".zip": "arcade", ".7z": "arcade",
    ".exe": "pc", ".msi": "pc",
    # Ambiguous across systems (see _AMBIGUOUS_EXTENSIONS) — these defaults only
    # apply when the path carries no directory/release platform hint.
    ".bin": "genesis",
    ".chd": "psx",
}

# Extensions shared by several systems, so the extension alone cannot decide the
# platform: ``.bin`` is an Atari 2600 ROM *and* a Mega Drive ROM *and* a raw PSX
# track; ``.chd`` is Mega-CD *and* PSX. For these the directory / release context
# must win — see ``platform_from_path``.
_AMBIGUOUS_EXTENSIONS: frozenset[str] = frozenset({".bin", ".chd", ".cue", ".iso", ".zip", ".7z"})

# Console-ROM extensions the games library scanner/importer ingests. Derived
# from _EXT_TO_PLATFORM minus PC installers, so a scannable ROM always has a
# resolvable platform (previously ROM_EXTENSIONS lived in libraries/games.py
# and had silently drifted — .nds/.3ds/.zip resolved to no platform).
ROM_EXTENSIONS: frozenset[str] = frozenset(
    ext for ext, plat in _EXT_TO_PLATFORM.items() if plat != "pc"
)


def platform_from_extension(path: str | None) -> str | None:
    """Platform slug implied by a file's extension, or ``None``.

    Extension-only resolution. For ambiguous extensions (``.bin``, ``.chd``, …)
    this returns the conservative default; prefer :func:`platform_from_path`,
    which lets the enclosing ROM-set directory override it.
    """
    if not path:
        return None
    import os

    return _EXT_TO_PLATFORM.get(os.path.splitext(path)[1].lower())


# Directory names that must NOT be treated as games at all. ROM sets ship BIOS
# images next to the ROMs (``roms/bios/megacd/bios_CD_U.bin``, and the variant
# ``roms/psx/BIOS Files/scph1001.bin``); they are not playable titles and would
# otherwise land in the library as "bios CD U" / "scph1001".
_NON_GAME_DIRS: frozenset[str] = frozenset(
    {"bios", "bioses", "bios files", "firmware", "system", "system files"}
)


def is_non_game_path(path: str | None) -> bool:
    """Whether a path is support data (BIOS/firmware) rather than a game."""
    if not path:
        return False

    # Only *directory* components count, so a game legitimately called
    # "System.nes" is not mistaken for firmware.
    dirs = {p.lower() for p in str(path).replace("\\", "/").split("/")[:-1]}
    return bool(dirs & _NON_GAME_DIRS)


def platform_from_path(path: str | None) -> str | None:
    """Platform slug for a ROM path, using directory context then extension.

    ROM collections are laid out one directory per system
    (``roms/atari2600/…``, ``roms/megacd/…``), which is far more reliable than
    the extension for the systems that share one: an ``.bin`` under
    ``atari2600/`` is an Atari 2600 ROM, not a Mega Drive one. Unambiguous
    extensions still win over the directory so a stray ``.z64`` in the wrong
    folder resolves correctly.
    """
    if not path:
        return None
    import os

    ext = os.path.splitext(path)[1].lower()
    ext_slug = _EXT_TO_PLATFORM.get(ext)

    # Unambiguous extension: trust it over the directory name.
    if ext_slug and ext not in _AMBIGUOUS_EXTENSIONS:
        return ext_slug

    # Ambiguous (or unknown) extension: let the ROM-set directory decide.
    for part in reversed(str(path).replace("\\", "/").split("/")[:-1]):
        dir_slug = normalize_platform(part)
        if dir_slug:
            return dir_slug

    return ext_slug


def profile_for_platform(slug: str | None) -> str | None:
    """Container profile that runs a given platform, or ``None`` if unrunnable.

    Console platforms map to the ``retro`` (libretro) profile; ``pc`` maps to
    the Wine profile. Modern consoles we can't emulate here return ``None``.
    """
    if slug is None:
        return None
    if is_retro_platform(slug):
        return "retro"
    if slug == "pc":
        return "wine"
    return None


# Platforms whose libretro core cannot boot without a BIOS/firmware image, and
# the ROM-set directory that holds it. Cartridge systems (NES/SNES/N64/GB/…)
# need none and are absent here on purpose.
#
# The value is the sub-directory under the collection's ``bios/`` root, because
# a core looks its BIOS up by bare filename inside RetroArch's system directory
# (``scph1001.bin``, ``bios_CD_E.bin``), so each system's files have to be
# mounted flat — not nested one level down.
_BIOS_DIRS: dict[str, str] = {
    "psx": "psx",
    "megacd": "megacd",
    "3do": "3do",
    "arcade": "arcade",
}


def bios_dir_for(slug: str | None) -> str | None:
    """ROM-set ``bios/`` sub-directory a platform needs, or ``None``.

    ``None`` means the platform boots straight from the ROM (every cartridge
    system), so no system directory has to be mounted for it.
    """
    if not slug:
        return None
    return _BIOS_DIRS.get(slug)


def requires_bios(slug: str | None) -> bool:
    """Whether a platform's core needs a BIOS image to boot at all."""
    return bios_dir_for(slug) is not None
