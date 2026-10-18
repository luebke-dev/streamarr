"""Warm the on-disk artwork cache for the items a user is about to look at.

``/api/media/images/proxy`` already caches bytes per URL, so a *warm* cache
turns a poster into a 9 ms disk read while a cold one is an upstream fetch
(~0.5 s from a home connection to the TMDB CDN). A restart, a cache prune or
a fresh import therefore makes the first library page visibly slower.

Warming is deliberately bounded to a small, predictable window:

* the newest movie/show items (they are what the home row and "latest"
  sections show), and
* the items a scan just touched,

never the whole library. A 45k-item library would otherwise pull gigabytes
through the proxy for artwork no one has asked for yet.
"""

from __future__ import annotations

import logging
import os
import uuid
from collections.abc import Iterable, Sequence
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaItem, MediaType

logger = logging.getLogger(__name__)

TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

# Poster variants the web client really renders, in the order it asks for
# them: w780 for cards/detail pages (the overlay route resolves posters at
# that size), w500 for home/search rows that carry no local media type.
_POSTER_SIZES: tuple[str, ...] = ("w780", "w500")
_BACKDROP_SIZE = "w1280"
_URLS_PER_ITEM = len(_POSTER_SIZES) + 1

# Stored local artwork is served by us, not by a provider CDN; expanding it to
# a TMDB URL would only produce 404s.
_LOCAL_PATH_PREFIXES = ("/api/", "/icons/", "/images/", "/artwork/", "/cache/")

_DEFAULT_ITEMS = 40


def warmup_item_limit() -> int:
    """How many items to warm per run (``STREAMARR_ARTWORK_WARMUP_ITEMS``)."""
    raw = os.getenv("STREAMARR_ARTWORK_WARMUP_ITEMS")
    if raw is None:
        return _DEFAULT_ITEMS
    try:
        return max(0, int(raw))
    except ValueError:
        logger.warning(
            "Ignoring invalid STREAMARR_ARTWORK_WARMUP_ITEMS=%r", raw
        )
        return _DEFAULT_ITEMS


def _provider_urls(value: Any, size: str) -> list[str]:
    """Expand one stored image reference into the URL(s) the web client uses."""
    if not isinstance(value, str) or not value.strip():
        return []
    value = value.strip()
    if value.startswith(("http://", "https://")):
        return [value]
    if value.startswith("/") and not value.startswith("//"):
        if value.startswith(_LOCAL_PATH_PREFIXES):
            return []
        return [f"{TMDB_IMAGE_BASE}/{size}{value}"]
    return []


def artwork_urls_for_item(item: MediaItem) -> list[str]:
    """Remote artwork URLs a browser would request for ``item``.

    Mirrors the frontend's ``getMediaImageUrl``: the same poster sizes and the
    same backdrop size, so a warmed entry is the exact cache key the browser
    hits instead of a near miss.
    """
    poster = getattr(item, "poster_url", None) or item.poster_path
    urls: list[str] = []
    if isinstance(poster, str) and poster.startswith(("http://", "https://")):
        urls.append(poster)
    else:
        for size in _POSTER_SIZES:
            urls.extend(_provider_urls(poster, size))
    urls.extend(_provider_urls(item.backdrop_path, _BACKDROP_SIZE))

    seen: set[str] = set()
    return [url for url in urls if not (url in seen or seen.add(url))]


def artwork_urls_for_items(items: Iterable[MediaItem]) -> list[str]:
    seen: set[str] = set()
    urls: list[str] = []
    for item in items:
        for url in artwork_urls_for_item(item):
            if url not in seen:
                seen.add(url)
                urls.append(url)
    return urls


async def _warm(urls: Sequence[str], *, item_count: int) -> dict[str, int]:
    # Imported lazily: the fetch/cache primitive lives next to the proxy
    # endpoint, and this service is also called from worker tasks (the same
    # worker -> api.v1.media edge page_layouts already uses).
    from streamarr.api.v1.media import warm_artwork_cache_urls

    warmed = await warm_artwork_cache_urls(urls, limit=item_count * _URLS_PER_ITEM)
    return {"items": item_count, "urls": len(urls), "warmed": warmed}


async def warm_recent_artwork(
    db: AsyncSession,
    *,
    limit_items: int | None = None,
) -> dict[str, int]:
    """Warm the newest top-level movie/show posters and backdrops."""
    items = warmup_item_limit() if limit_items is None else max(0, limit_items)
    if items == 0:
        return {"items": 0, "urls": 0, "warmed": 0}

    rows = (
        await db.execute(
            select(MediaItem)
            .where(MediaItem.media_type.in_((MediaType.MOVIES, MediaType.SHOWS)))
            .where(MediaItem.parent_guid.is_(None))
            .where(MediaItem.poster_path.isnot(None))
            .order_by(MediaItem.created_at.desc())
            .limit(items)
        )
    ).scalars().all()

    return await _warm(artwork_urls_for_items(rows), item_count=len(rows))


async def warm_scanned_artwork(
    db: AsyncSession,
    media_item_guids: Iterable[str | uuid.UUID],
    *,
    limit_items: int = 20,
) -> dict[str, int]:
    """Warm artwork for the items a library scan just added or updated.

    Best effort and capped: a scan that adds 5000 episodes should not turn
    into 15000 upstream fetches. Items that have no poster yet are skipped —
    their artwork only appears once the queued metadata refresh has run, and
    ``warm_recent_artwork`` picks them up afterwards.
    """
    guids: list[uuid.UUID] = []
    for raw in media_item_guids:
        try:
            guids.append(raw if isinstance(raw, uuid.UUID) else uuid.UUID(str(raw)))
        except (TypeError, ValueError):
            continue
    if not guids:
        return {"items": 0, "urls": 0, "warmed": 0}

    rows = (
        await db.execute(
            select(MediaItem)
            .where(MediaItem.guid.in_(guids))
            .where(MediaItem.parent_guid.is_(None))
            .where(MediaItem.poster_path.isnot(None))
            .order_by(MediaItem.created_at.desc())
            .limit(max(0, limit_items))
        )
    ).scalars().all()

    return await _warm(artwork_urls_for_items(rows), item_count=len(rows))
