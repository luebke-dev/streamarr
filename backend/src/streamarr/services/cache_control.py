"""Cache maintenance helpers for rendered layouts and artwork."""

from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

import redis.asyncio as redis_async
from redis.exceptions import RedisError

from streamarr.config import settings
from streamarr.services.observability import (
    record_layout_cache_invalidation,
    set_artwork_cache_stats,
)

logger = logging.getLogger(__name__)

RENDER_CACHE_PREFIX = "streamarr:page-layout:rendered:"
RENDER_STALE_PREFIX = "streamarr:page-layout:rendered-stale:"


def env_flag(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def artwork_cache_enabled() -> bool:
    return env_flag("STREAMARR_ARTWORK_CACHE_ENABLED", False)


def artwork_cache_root(create: bool = False) -> Path:
    root = Path(os.getenv("STREAMARR_ARTWORK_CACHE_DIR", "/cache/artwork"))
    if create:
        root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


async def clear_rendered_layout_cache(reason: str = "manual") -> dict[str, int]:
    """Clear all rendered page layout Redis entries."""
    client = redis_async.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    deleted = 0
    try:
        for prefix in (RENDER_CACHE_PREFIX, RENDER_STALE_PREFIX):
            async for key in client.scan_iter(match=f"{prefix}*"):
                deleted += await client.delete(key)
        record_layout_cache_invalidation(reason)
        logger.info(
            "Cleared rendered layout cache",
            extra={"reason": reason, "deleted": deleted},
        )
    except RedisError as exc:
        logger.debug("Failed to clear rendered layout cache: %s", exc)
    finally:
        await client.aclose()
    return {"deleted": deleted}


async def rendered_layout_cache_stats() -> dict[str, int]:
    """Return a lightweight count of fresh/stale rendered layout cache keys."""
    client = redis_async.from_url(
        settings.redis_url,
        encoding="utf-8",
        decode_responses=True,
    )
    fresh = 0
    stale = 0
    try:
        async for _key in client.scan_iter(match=f"{RENDER_CACHE_PREFIX}*"):
            fresh += 1
        async for _key in client.scan_iter(match=f"{RENDER_STALE_PREFIX}*"):
            stale += 1
    except RedisError as exc:
        logger.debug("Failed to inspect rendered layout cache: %s", exc)
    finally:
        await client.aclose()
    return {"fresh_entries": fresh, "stale_entries": stale}


def artwork_cache_stats() -> dict[str, Any]:
    root = artwork_cache_root(create=False)
    files = [path for path in root.glob("*") if path.is_file()] if root.exists() else []
    total_bytes = sum(path.stat().st_size for path in files)
    set_artwork_cache_stats(len(files), total_bytes)
    return {
        "enabled": artwork_cache_enabled(),
        "path": str(root),
        "files": len(files),
        "bytes": total_bytes,
    }


def cleanup_artwork_cache(
    *,
    max_bytes: int | None = None,
    max_age_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Remove old artwork cache files by max age and/or LRU size cap."""
    root = artwork_cache_root(create=False)
    if not root.exists():
        return {
            "path": str(root),
            "deleted_files": 0,
            "deleted_bytes": 0,
            "remaining_files": 0,
            "remaining_bytes": 0,
            "dry_run": dry_run,
        }

    files = [path for path in root.glob("*") if path.is_file()]
    now = time.time()
    delete_set: set[Path] = set()
    if max_age_days is not None and max_age_days > 0:
        cutoff = now - (max_age_days * 86400)
        delete_set.update(path for path in files if path.stat().st_mtime < cutoff)

    remaining = [path for path in files if path not in delete_set]
    remaining_size = sum(path.stat().st_size for path in remaining)
    if max_bytes is not None and max_bytes > 0 and remaining_size > max_bytes:
        for path in sorted(remaining, key=lambda item: item.stat().st_mtime):
            if remaining_size <= max_bytes:
                break
            delete_set.add(path)
            remaining_size -= path.stat().st_size

    deleted_files = 0
    deleted_bytes = 0
    for path in delete_set:
        size = path.stat().st_size
        if not dry_run:
            try:
                path.unlink()
            except FileNotFoundError:
                continue
        deleted_files += 1
        deleted_bytes += size

    stats = artwork_cache_stats()
    logger.info(
        "Artwork cache cleanup completed",
        extra={
            "deleted_files": deleted_files,
            "deleted_bytes": deleted_bytes,
            "remaining_files": stats["files"],
            "remaining_bytes": stats["bytes"],
            "dry_run": dry_run,
        },
    )
    return {
        "path": str(root),
        "deleted_files": deleted_files,
        "deleted_bytes": deleted_bytes,
        "remaining_files": stats["files"],
        "remaining_bytes": stats["bytes"],
        "dry_run": dry_run,
    }
