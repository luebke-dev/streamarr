"""Background warmup of the artwork cache."""

from __future__ import annotations

import logging

from streamarr.database import sessionmanager
from streamarr.services.artwork_warmup import warm_recent_artwork

logger = logging.getLogger(__name__)


async def warm_recent_artwork_impl(limit_items: int | None = None) -> dict[str, int]:
    """Warm the newest posters so the first page load after a cold cache is fast.

    Runs on a slow cron. After the first pass every URL it asks for is already
    on disk, so the warmup skips it and the run costs a directory glob instead
    of a fetch.
    """
    try:
        async with sessionmanager.session() as db:
            result = await warm_recent_artwork(db, limit_items=limit_items)
    except Exception as exc:
        logger.warning("Artwork cache warmup failed: %s", exc)
        return {"items": 0, "urls": 0, "warmed": 0}

    if result["warmed"]:
        logger.info(
            "Warmed %d artwork variants for %d items",
            result["warmed"],
            result["items"],
        )
    return result
