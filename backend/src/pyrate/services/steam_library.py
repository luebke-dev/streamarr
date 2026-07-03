"""Read a logged-in Steam home directory into a list of owned/installed games.

This is a pure local-file *reader*: it never touches the Steam Web API and
needs no API key.  It parses the Valve KeyValues (VDF/ACF) text files that a
running Steam client leaves behind on disk:

* ``steamapps/appmanifest_*.acf`` — one file per *installed* game.
* ``steamapps/libraryfolders.vdf`` — extra library folders on other disks.
* ``userdata/<accountid>/config/localconfig.vdf`` — every *owned* app id.

The module is deliberately dependency free: a small, tolerant KeyValues
parser lives right here (do not add the third-party ``vdf`` package).
"""

import logging
import os
import re
from collections.abc import Iterator
from pathlib import Path

logger = logging.getLogger(__name__)


# Sub-paths, relative to the persistent home dir (container's /home/retro),
# under which a Steam install may live.  Both common Linux layouts plus the
# occasional case-variant are covered; results are de-duplicated by realpath.
_STEAM_SUBPATHS: tuple[str, ...] = (
    ".local/share/Steam",
    ".steam/steam",
    ".steam/root",
    ".steam/Steam",
    "Steam",
)

# App ids that Steam lists like games but are really runtimes / redistributables.
# A small denylist is enough; anything missed is caught by the name heuristic
# below (for installed entries, which have a name).
_NON_GAME_APP_IDS: frozenset[str] = frozenset(
    {
        "228980",  # Steamworks Common Redistributables
        "1070560",  # Steam Linux Runtime 1.0 (scout)
        "1391110",  # Steam Linux Runtime 2.0 (soldier)
        "1628350",  # Steam Linux Runtime 3.0 (sniper)
        "1493710",  # Proton Experimental
        "1580130",  # Proton 6.3
        "1887720",  # Proton 7.0
        "2180100",  # Proton 8.0
        "2348590",  # Proton 9.0
        "1054830",  # Proton 5.0
        "961940",  # Proton 4.11
        "930400",  # Proton 4.2
        "858280",  # Proton 3.16
    }
)

# Matches the *names* of infrastructure apps (Proton builds, Steam Linux
# Runtime, redistributables) so we still skip versions not in the id denylist.
# Anchored + requiring a qualifier so a game literally named "Proton" survives.
_NON_GAME_NAME_RE = re.compile(
    r"^(?:steamworks common redistributables"
    r"|steam linux runtime(?:\b.*)?"
    r"|proton\s+(?:experimental|hotfix|easyanticheat[\w\s]*|\d.*))\s*$",
    re.IGNORECASE,
)

# Keys that appear at the top level of the *old* libraryfolders.vdf format and
# are metadata rather than a library path.
_LIBFOLDER_META_KEYS: frozenset[str] = frozenset(
    {"timenextstatsreport", "contentstatsid"}
)


# ---------------------------------------------------------------------------
# Tolerant Valve KeyValues (VDF / ACF) parser
# ---------------------------------------------------------------------------


def _tokenize(text: str) -> Iterator[tuple[str, str]]:
    """Yield ``(kind, value)`` tokens from VDF text.

    ``kind`` is one of ``"str"``, ``"lbrace"`` or ``"rbrace"``.  Handles quoted
    strings (with ``\\`` escapes), bare unquoted tokens, ``//`` line comments
    and arbitrary whitespace.
    """
    i = 0
    n = len(text)
    escapes = {"n": "\n", "t": "\t", "r": "\r", "\\": "\\", '"': '"'}
    while i < n:
        c = text[i]
        if c in " \t\r\n":
            i += 1
            continue
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            nl = text.find("\n", i)
            i = n if nl == -1 else nl + 1
            continue
        if c == "{":
            yield ("lbrace", "{")
            i += 1
            continue
        if c == "}":
            yield ("rbrace", "}")
            i += 1
            continue
        if c == '"':
            i += 1
            buf: list[str] = []
            while i < n:
                ch = text[i]
                if ch == "\\" and i + 1 < n:
                    buf.append(escapes.get(text[i + 1], text[i + 1]))
                    i += 2
                    continue
                if ch == '"':
                    i += 1
                    break
                buf.append(ch)
                i += 1
            yield ("str", "".join(buf))
            continue
        # Unquoted token: read until whitespace, brace or quote.
        j = i
        while j < n and text[j] not in ' \t\r\n{}"':
            j += 1
        yield ("str", text[i:j])
        i = j


def _parse_vdf(text: str) -> dict:
    """Parse VDF text into a nested ``dict``.

    Values are either ``str`` (a scalar) or ``dict`` (a nested block).  The
    parser is intentionally lenient: stray braces and dangling keys are
    tolerated so a malformed file degrades to a partial result instead of
    raising.
    """
    tokens = _tokenize(text)

    def parse_block(top: bool) -> dict:
        result: dict = {}
        pending_key: str | None = None
        for kind, value in tokens:
            if kind == "rbrace":
                if top:
                    # Unbalanced close at top level — ignore and keep going.
                    pending_key = None
                    continue
                return result
            if kind == "lbrace":
                key = pending_key if pending_key is not None else ""
                result[key] = parse_block(top=False)
                pending_key = None
                continue
            # kind == "str"
            if pending_key is None:
                pending_key = value
            else:
                result[pending_key] = value
                pending_key = None
        # End of input (only reached for the top-level block or a truncated
        # file).  A trailing key with no value is dropped.
        return result

    return parse_block(top=True)


def _get_ci(mapping: object, key: str) -> object:
    """Case-insensitive ``dict`` lookup; returns ``None`` if absent/not a dict."""
    if not isinstance(mapping, dict):
        return None
    if key in mapping:
        return mapping[key]
    lowered = key.lower()
    for k, v in mapping.items():
        if isinstance(k, str) and k.lower() == lowered:
            return v
    return None


def _navigate(mapping: object, *keys: str) -> object:
    """Walk a chain of case-insensitive keys, returning ``None`` on any miss."""
    current: object = mapping
    for key in keys:
        current = _get_ci(current, key)
        if current is None:
            return None
    return current


def _read_vdf_file(path: Path) -> dict:
    """Read and parse a VDF file, returning ``{}`` on any I/O or parse error."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        logger.debug("Could not read VDF file %s: %s", path, exc)
        return {}
    try:
        return _parse_vdf(text)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("Failed to parse VDF file %s: %s", path, exc)
        return {}


# ---------------------------------------------------------------------------
# Steam directory discovery
# ---------------------------------------------------------------------------


def _find_steam_dirs(home: Path) -> list[Path]:
    """Return existing Steam install roots under ``home``, de-duped by realpath."""
    candidates: list[Path] = [home / sub for sub in _STEAM_SUBPATHS]
    # The caller may also point us straight at a Steam dir (or a bare library).
    candidates.append(home)

    found: list[Path] = []
    seen: set[str] = set()
    for cand in candidates:
        if not cand.is_dir():
            continue
        # Only keep dirs that actually look like a Steam install / library.
        if not (
            (cand / "steamapps").is_dir()
            or (cand / "SteamApps").is_dir()
            or (cand / "userdata").is_dir()
        ):
            continue
        real = os.path.realpath(cand)
        if real in seen:
            continue
        seen.add(real)
        found.append(cand)
    return found


def _steamapps_dir(base: Path) -> Path | None:
    """Return the ``steamapps`` sub-dir of ``base`` (case tolerant), if present."""
    for name in ("steamapps", "SteamApps"):
        candidate = base / name
        if candidate.is_dir():
            return candidate
    return None


def _iter_library_paths(vdf: dict) -> Iterator[str]:
    """Yield library root paths from a parsed ``libraryfolders.vdf``.

    Supports both the modern nested format (each entry is a block with a
    ``path``) and the legacy flat format (numeric key -> path string).
    """
    root = _get_ci(vdf, "libraryfolders")
    if root is None:
        root = _get_ci(vdf, "LibraryFolders")
    if not isinstance(root, dict):
        return
    for key, value in root.items():
        if isinstance(value, dict):
            path = _get_ci(value, "path")
            if isinstance(path, str) and path.strip():
                yield path.strip()
        elif isinstance(value, str):
            # Legacy flat format: only numeric keys carry a real path.
            if isinstance(key, str) and key.isdigit() and value.strip():
                if key.lower() not in _LIBFOLDER_META_KEYS:
                    yield value.strip()


def _collect_steamapps_dirs(steam_dirs: list[Path]) -> list[Path]:
    """All ``steamapps`` dirs to scan: primary ones plus extra libraries."""
    result: list[Path] = []
    seen: set[str] = set()

    def _add(candidate: Path | None) -> None:
        if candidate is None or not candidate.is_dir():
            return
        real = os.path.realpath(candidate)
        if real in seen:
            return
        seen.add(real)
        result.append(candidate)

    for steam_dir in steam_dirs:
        primary = _steamapps_dir(steam_dir)
        _add(primary)
        # libraryfolders.vdf usually lives in steamapps/, older Steam in config/.
        for vdf_path in (
            (primary / "libraryfolders.vdf") if primary else None,
            steam_dir / "config" / "libraryfolders.vdf",
        ):
            if vdf_path is None or not vdf_path.is_file():
                continue
            for lib_path in _iter_library_paths(_read_vdf_file(vdf_path)):
                _add(_steamapps_dir(Path(lib_path)))

    return result


# ---------------------------------------------------------------------------
# Source parsers
# ---------------------------------------------------------------------------


def _parse_appmanifest(path: Path) -> dict | None:
    """Extract ``{app_id, name, installed}`` from an ``appmanifest_*.acf``."""
    state = _get_ci(_read_vdf_file(path), "AppState")
    if not isinstance(state, dict):
        return None
    app_id = _get_ci(state, "appid")
    if not isinstance(app_id, str):
        return None
    app_id = app_id.strip()
    if not app_id.isdigit():
        return None
    raw_name = _get_ci(state, "name")
    name = raw_name.strip() if isinstance(raw_name, str) and raw_name.strip() else None
    return {"app_id": app_id, "name": name, "installed": True}


def _collect_owned_app_ids(steam_dir: Path) -> Iterator[str]:
    """Yield owned app ids from every ``localconfig.vdf`` under ``userdata``."""
    userdata = steam_dir / "userdata"
    if not userdata.is_dir():
        return
    for account_dir in sorted(userdata.iterdir()):
        localconfig = account_dir / "config" / "localconfig.vdf"
        if not localconfig.is_file():
            continue
        data = _read_vdf_file(localconfig)
        store = _get_ci(data, "UserLocalConfigStore")
        if store is None:
            # Fall back to the single root block whatever it is named.
            store = next(
                (v for v in data.values() if isinstance(v, dict)),
                None,
            )
        apps = _navigate(store, "Software", "Valve", "Steam", "apps")
        if not isinstance(apps, dict):
            continue
        for app_id in apps:
            if isinstance(app_id, str) and app_id.isdigit():
                yield app_id


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _is_non_game(app_id: str, name: str | None) -> bool:
    """True if the entry is a runtime/redistributable rather than a real game."""
    if app_id in _NON_GAME_APP_IDS:
        return True
    if name and _NON_GAME_NAME_RE.match(name):
        return True
    return False


def _sort_key(game: dict) -> tuple:
    name = game["name"]
    app_id = game["app_id"]
    # Named games first (alphabetical), then unnamed (owned-only) by app id.
    id_key = (0, int(app_id)) if app_id.isdigit() else (1, app_id)
    return (name is None, (name or "").lower(), id_key)


def read_steam_library(steam_home: str | os.PathLike) -> list[dict]:
    """Read a Steam home directory into a de-duplicated list of games.

    ``steam_home`` is the persistent state dir that maps to the container's
    ``/home/retro`` — Steam files live under e.g.
    ``{steam_home}/.local/share/Steam`` and/or ``{steam_home}/.steam/steam``.

    Returns a list of ``{"app_id": str, "name": str | None, "installed": bool}``
    dicts, de-duplicated by ``app_id`` and sorted by name then app id.  Installed
    (appmanifest) entries win over owned-only entries.  Returns ``[]`` when the
    directory holds nothing readable.
    """
    home = Path(steam_home)
    steam_dirs = _find_steam_dirs(home)
    if not steam_dirs:
        return []

    games: dict[str, dict] = {}

    # 1) Installed games from appmanifest_*.acf across every library folder.
    for steamapps in _collect_steamapps_dirs(steam_dirs):
        for acf in sorted(steamapps.glob("appmanifest_*.acf")):
            entry = _parse_appmanifest(acf)
            if entry is None:
                continue
            app_id = entry["app_id"]
            name = entry["name"]
            # If a previous manifest already supplied a name, keep it.
            existing = games.get(app_id)
            if existing and existing.get("installed") and name is None:
                name = existing.get("name")
            games[app_id] = {"app_id": app_id, "name": name, "installed": True}

    # 2) Owned games from localconfig.vdf; never override an installed entry.
    for steam_dir in steam_dirs:
        for app_id in _collect_owned_app_ids(steam_dir):
            if app_id in games:
                continue
            games[app_id] = {"app_id": app_id, "name": None, "installed": False}

    result = [
        game
        for app_id, game in games.items()
        if not _is_non_game(app_id, game["name"])
    ]
    result.sort(key=_sort_key)
    return result
