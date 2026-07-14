"""Trickplay sprite cache.

Sprites used to be generated per *streaming session* into ``/temp``, so every
play of the same file paid for the same sheets again and they vanished with the
session. They are cached per *source file* instead: the key is derived from the
file path, so any session playing that file reuses them, and they are dropped
together with the file they describe (see :func:`purge`).

A sheet is only trusted once the generator has written the ``.complete`` marker
— an interrupted run leaves a partial set of sheets behind, and reusing that
would leave the tail of the seek bar blank forever.
"""

import hashlib
import logging
import os
import shutil
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

#: Written by the generator container after FFmpeg exits successfully.
COMPLETE_MARKER = ".complete"

SPRITE_GLOB = "sprite_*.webp"


def cache_key(file_path: str) -> str:
    """Stable per-file cache key.

    Derived from the path rather than the media-file GUID so that the cache can
    be located (and purged) by callers that only hold a path — every deletion
    site does, not all of them hold the row.
    """
    return hashlib.sha256(str(file_path).encode()).hexdigest()[:32]


def _root() -> Path:
    """Cache root as this process can see it."""
    if os.path.exists("/.dockerenv"):
        return Path("/cache/trickplay")

    from streamarr.services.computing import _data_root

    return Path(f"{_data_root()}/cache/trickplay")


def cache_dir(file_path: str) -> Path:
    """Directory holding the sprite sheets for ``file_path``."""
    return _root() / cache_key(file_path)


def host_cache_dir(file_path: str, data_root: str) -> str:
    """The same directory as the Docker daemon sees it (for sibling binds)."""
    return f"{data_root}/cache/trickplay/{cache_key(file_path)}"


def sprites(file_path: str) -> list[Path]:
    """Sorted sprite sheets for ``file_path`` (empty when none were generated)."""
    directory = cache_dir(file_path)
    if not directory.is_dir():
        return []
    return sorted(directory.glob(SPRITE_GLOB))


def is_complete(file_path: str) -> bool:
    """True when a finished set of sheets is cached for ``file_path``."""
    directory = cache_dir(file_path)
    return (directory / COMPLETE_MARKER).exists() and bool(sprites(file_path))


def purge(file_path: str) -> bool:
    """Drop the cached sheets for ``file_path``. Safe to call for unknown files."""
    directory = cache_dir(file_path)
    if not directory.is_dir():
        return False
    try:
        shutil.rmtree(directory)
        logger.info("Dropped trickplay cache for %s", file_path)
        return True
    except OSError as e:
        logger.warning("Failed to drop trickplay cache %s: %s", directory, e)
        return False


def purge_orphans(known_paths: Iterable[str]) -> dict[str, int]:
    """Drop cache entries that no longer belong to any known media file.

    Deleting a file drops its sprites right away (see :func:`purge`); this
    catches the entries no deletion hook ever sees — a file moved or renamed
    outside the app, or one removed while the backend was down. The key is
    derived from the path, so those entries are simply no longer claimed by
    anybody.

    Args:
        known_paths: Every media file path currently in the library.
    """
    result = {"scanned": 0, "deleted": 0, "bytes_freed": 0, "failed": 0}

    root = _root()
    if not root.is_dir():
        return result

    keep = {cache_key(path) for path in known_paths if path}

    for entry in root.iterdir():
        if not entry.is_dir():
            continue
        result["scanned"] += 1
        if entry.name in keep:
            continue
        try:
            size = sum(f.stat().st_size for f in entry.glob("*") if f.is_file())
            shutil.rmtree(entry)
            result["deleted"] += 1
            result["bytes_freed"] += size
        except OSError as e:
            result["failed"] += 1
            logger.warning("Failed to drop orphaned trickplay cache %s: %s", entry, e)

    if result["deleted"]:
        logger.info(
            "Dropped %s orphaned trickplay cache entries (%.1f MB)",
            result["deleted"],
            result["bytes_freed"] / 1_048_576,
        )
    return result
