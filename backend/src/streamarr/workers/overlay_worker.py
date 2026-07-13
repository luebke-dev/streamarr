"""Taskiq workers driving the overlay engine."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy import select

from streamarr.database import sessionmanager
from streamarr.models.media import MediaItem
from streamarr.models.overlay import (
    OverlayApplication,
    OverlayMediaScope,
    OverlayTarget,
    OverlayTemplate,
)
from streamarr.overlays import OverlayService
from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)


_SCOPE_TO_MEDIA_TYPES = {
    OverlayMediaScope.MOVIE: ("MOVIES",),
    OverlayMediaScope.SHOW: ("SHOWS",),
    OverlayMediaScope.BOTH: ("MOVIES", "SHOWS"),
}


async def _overlays_enabled() -> bool:
    async with sessionmanager.session() as db:
        return bool(await SettingsService(db).get("overlays.enabled", True))


async def render_overlay_for_item_impl(
    media_guid: str,
    target: str = OverlayTarget.POSTER.value,
) -> dict[str, Any]:
    """Render overlays for a single item, returning a JSON-friendly result."""
    if not await _overlays_enabled():
        return {"skipped": True, "reason": "overlays-disabled"}

    try:
        guid = uuid.UUID(media_guid)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid media_guid {media_guid!r}") from exc
    target_enum = OverlayTarget(target)

    async with sessionmanager.session() as db:
        service = await OverlayService.from_settings(db)
        try:
            result = await service.apply(guid, target=target_enum)
        finally:
            await service.close()

    return {
        "media_guid": str(result.media_guid),
        "target": result.target.value,
        "rendered": result.rendered,
        "templates_evaluated": result.templates_evaluated,
        "templates_applied": result.templates_applied,
        "output_path": result.output_path,
        "source_hash": result.source_hash,
        "skipped_reason": result.skipped_reason,
    }


async def tick_render_missing_overlays_impl(batch: int = 200) -> int:
    """Backstop: queue overlay renders for items that don't have one yet.

    Catches anything the import/probe hooks missed (e.g. items that
    already existed before a template was added). Runs on a slow cron
    (every 30 min) and processes up to ``batch`` items per pass to keep
    Redis queue depth bounded.
    """
    if not await _overlays_enabled():
        return 0

    async with sessionmanager.session() as db:
        # Items that *should* have an overlay (movie/show, top-level,
        # have a poster) but for which we've never written an
        # OverlayApplication row.
        rows = await db.execute(
            select(MediaItem.guid)
            .outerjoin(
                OverlayApplication,
                OverlayApplication.media_item_guid == MediaItem.guid,
            )
            .where(MediaItem.media_type.in_(("MOVIES", "SHOWS")))
            .where(MediaItem.parent_guid.is_(None))
            .where(MediaItem.poster_path.isnot(None))
            .where(OverlayApplication.media_item_guid.is_(None))
            .limit(batch)
        )
        guids = [row[0] for row in rows.all()]

    if not guids:
        return 0
    from streamarr.worker import render_overlay_for_item  # noqa: WPS433

    for guid in guids:
        await render_overlay_for_item.kiq(str(guid), "POSTER")
    logger.info(
        "overlay backstop tick: enqueued %d missing item renders", len(guids)
    )
    return len(guids)


async def bulk_rerender_for_template_impl(template_guid: str) -> int:
    """Re-render every item that *might* match a single template.

    Called whenever an admin saves an edit to a template. Filters to the
    media types the template's scope allows, queues a render task per
    item, and returns the count enqueued. The renderer's hash check
    means unaffected items will short-circuit cheaply.
    """
    try:
        guid = uuid.UUID(template_guid)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Invalid template_guid {template_guid!r}") from exc

    async with sessionmanager.session() as db:
        template = await db.get(OverlayTemplate, guid)
        if template is None:
            return 0
        media_types = _SCOPE_TO_MEDIA_TYPES.get(
            template.media_scope, ("MOVIES", "SHOWS")
        )

        rows = await db.execute(
            select(MediaItem.guid)
            .where(MediaItem.media_type.in_(media_types))
            .where(MediaItem.poster_path.isnot(None))
            .where(MediaItem.parent_guid.is_(None))
        )
        guids = [row[0] for row in rows.all()]
        target_value = template.target.value

    from streamarr.worker import render_overlay_for_item  # noqa: WPS433

    for media_guid in guids:
        await render_overlay_for_item.kiq(str(media_guid), target_value)
    if guids:
        logger.info(
            "overlay bulk re-render: enqueued %d items for template %s",
            len(guids),
            guid,
        )
    return len(guids)
