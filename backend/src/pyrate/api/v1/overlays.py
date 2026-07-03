"""Overlay template admin API + overlay-aware artwork serving."""

from __future__ import annotations

import os
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse, RedirectResponse, Response
from sqlalchemy import select

from pyrate.api.dependencies import (
    CurrentSuperuser,
    CurrentUser,
    DatabaseSession,
)
from pyrate.models.media import MediaItem
from pyrate.models.overlay import (
    OverlayApplication,
    OverlayTarget,
    OverlayTemplate,
)
from pyrate.overlays import OverlayService
from pyrate.overlays.renderer import iter_template_entries
from pyrate.overlays.context import build_render_context
from pyrate.overlays.service import _resolve_image_url
from pyrate.schemas.overlay import (
    BulkRerenderResponse,
    OverlayApplyResponse,
    OverlayTemplateCreate,
    OverlayTemplateRead,
    OverlayTemplateUpdate,
)
from pyrate.services.image_cache import ImageCacheError

router = APIRouter()


# ---------------------------------------------------------------------------
# Template CRUD
# ---------------------------------------------------------------------------


@router.get("", response_model=list[OverlayTemplateRead])
async def list_templates(
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    enabled: bool | None = Query(default=None),
    target: OverlayTarget | None = Query(default=None),
):
    stmt = select(OverlayTemplate).order_by(
        OverlayTemplate.is_system.desc(),
        OverlayTemplate.z_order.asc(),
        OverlayTemplate.name.asc(),
    )
    if enabled is not None:
        stmt = stmt.where(OverlayTemplate.enabled.is_(enabled))
    if target is not None:
        stmt = stmt.where(OverlayTemplate.target == target)
    return list((await db.execute(stmt)).scalars().all())


@router.get("/{template_guid}", response_model=OverlayTemplateRead)
async def get_template(
    template_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    template = await db.get(OverlayTemplate, template_guid)
    if template is None:
        raise HTTPException(404, detail="Overlay template not found")
    return template


@router.post("", response_model=OverlayTemplateRead, status_code=201)
async def create_template(
    payload: OverlayTemplateCreate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    template = OverlayTemplate(
        name=payload.name,
        description=payload.description,
        media_scope=payload.media_scope,
        target=payload.target,
        condition=payload.condition,
        elements=payload.elements,
        z_order=payload.z_order,
        enabled=payload.enabled,
        is_system=False,
        version=1,
    )
    db.add(template)
    await db.commit()
    await db.refresh(template)
    return template


@router.patch("/{template_guid}", response_model=OverlayTemplateRead)
async def update_template(
    template_guid: uuid.UUID,
    payload: OverlayTemplateUpdate,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    template = await db.get(OverlayTemplate, template_guid)
    if template is None:
        raise HTTPException(404, detail="Overlay template not found")

    changes = payload.model_dump(exclude_unset=True)
    if template.is_system and set(changes) - {"enabled"}:
        raise HTTPException(
            422,
            detail="System templates are read-only except for the 'enabled' toggle",
        )

    bump_version = any(
        key in changes
        for key in ("condition", "elements", "target", "media_scope", "z_order")
    )
    for key, value in changes.items():
        setattr(template, key, value)
    if bump_version:
        template.version = (template.version or 1) + 1
    template.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(template)
    return template


@router.delete("/{template_guid}", status_code=204)
async def delete_template(
    template_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    template = await db.get(OverlayTemplate, template_guid)
    if template is None:
        raise HTTPException(404, detail="Overlay template not found")
    if template.is_system:
        raise HTTPException(
            422, detail="System templates cannot be deleted; disable instead"
        )
    await db.delete(template)
    await db.commit()


# ---------------------------------------------------------------------------
# Apply / preview / rerender
# ---------------------------------------------------------------------------


@router.post(
    "/apply/{media_guid}",
    response_model=OverlayApplyResponse,
)
async def apply_to_item(
    media_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    target: OverlayTarget = Query(default=OverlayTarget.POSTER),
):
    service = await OverlayService.from_settings(db)
    try:
        result = await service.apply(media_guid, target=target)
    finally:
        await service.close()
    return OverlayApplyResponse(
        media_guid=result.media_guid,
        target=result.target,
        rendered=result.rendered,
        output_path=result.output_path,
        source_hash=result.source_hash,
        templates_evaluated=result.templates_evaluated,
        templates_applied=result.templates_applied,
        skipped_reason=result.skipped_reason,
    )


@router.get("/preview/{media_guid}")
async def preview_item(
    media_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
    target: OverlayTarget = Query(default=OverlayTarget.POSTER),
):
    """Render the overlay inline and stream the resulting JPEG.

    Useful for the admin UI to show live preview without persisting the
    cache file. Falls back to the original poster when no template
    matches.
    """
    service = await OverlayService.from_settings(db)
    try:
        from pyrate.models.media import MediaItem

        item = await service._load_item(media_guid)  # noqa: SLF001 — public-by-intent helper
        if item is None:
            raise HTTPException(404, detail="Media item not found")
        source_url = service._pick_source_url(item, target)  # noqa: SLF001
        if not source_url:
            raise HTTPException(404, detail="No source image for this target")

        try:
            original_path = await service.image_cache.get_original(
                media_guid, source_url
            )
        except ImageCacheError as exc:
            raise HTTPException(502, detail=str(exc))
        base_bytes = original_path.read_bytes()

        templates = await service.list_applicable_templates(media_guid, target)
        if not templates:
            # No template applies — return the original.
            return Response(content=base_bytes, media_type="image/jpeg")

        entries = iter_template_entries(templates)
        context = build_render_context(item)
        rendered = service.renderer.render(base_bytes, entries, context)
        return Response(content=rendered.data, media_type="image/jpeg")
    finally:
        await service.close()


@router.post(
    "/{template_guid}/rerender",
    response_model=BulkRerenderResponse,
    status_code=202,
)
async def rerender_template(
    template_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentSuperuser,  # noqa: ARG001
):
    template = await db.get(OverlayTemplate, template_guid)
    if template is None:
        raise HTTPException(404, detail="Overlay template not found")

    from pyrate.worker import bulk_rerender_overlays_for_template

    await bulk_rerender_overlays_for_template.kiq(str(template_guid))
    return BulkRerenderResponse(template_guid=template_guid, enqueued=-1)


# ---------------------------------------------------------------------------
# Public overlay-aware artwork serving
# ---------------------------------------------------------------------------


@router.get("/serve/{media_guid}")
async def serve_overlay_artwork(
    media_guid: uuid.UUID,
    db: DatabaseSession,
    current_user: CurrentUser,  # noqa: ARG001 — auth dependency
    target: OverlayTarget = Query(default=OverlayTarget.POSTER),
):
    """Stream a pre-rendered overlay image, falling back to the original.

    Behaviour:
      * Cache HIT — there is an ``OverlayApplication`` row and the file
        exists on disk → serve it (``image/jpeg``) with a long
        ``Cache-Control`` so the browser caches across page loads.
      * Cache MISS — no application row yet, or the file vanished. We
        enqueue a background render and respond with a 302 redirect to
        the item's original ``poster_path`` / ``backdrop_path`` so the
        browser shows *something* immediately. ``Cache-Control`` on the
        redirect is short so the next page hit asks again.

    This route is intentionally cheap on the hot path: never invokes
    PIL synchronously. Pre-rendering happens via worker tasks triggered
    at import/probe/template-save time and via ``tick_render_missing_overlays``.
    """
    item = await db.get(MediaItem, media_guid)
    if item is None:
        raise HTTPException(404, detail="Media item not found")

    application = (
        await db.execute(
            select(OverlayApplication).where(
                OverlayApplication.media_item_guid == media_guid,
                OverlayApplication.target == target,
            )
        )
    ).scalars().first()

    if application and application.output_path and os.path.exists(
        application.output_path
    ):
        return FileResponse(
            application.output_path,
            media_type="image/jpeg",
            headers={
                # Hash is encoded in the filename, so a different output
                # path means a different URL. Aggressive cache is safe.
                "Cache-Control": "public, max-age=86400, immutable",
                "X-Overlay-Source": "cache",
            },
        )

    # Cache miss — queue a render in the background and redirect to the
    # original poster URL so the user sees *something* instantly.
    raw_source = (
        item.poster_path if target == OverlayTarget.POSTER else item.backdrop_path
    )
    source_url = _resolve_image_url(raw_source, target)
    if not source_url:
        raise HTTPException(404, detail="No source artwork for this item")

    try:
        from pyrate.worker import render_overlay_for_item

        await render_overlay_for_item.kiq(str(media_guid), target.value)
    except Exception:
        # Best effort — a queue failure shouldn't break the redirect.
        pass

    return RedirectResponse(
        url=source_url,
        status_code=302,
        headers={
            # Short TTL so the next hit re-asks and may pick up the
            # freshly rendered overlay.
            "Cache-Control": "public, max-age=15",
            "X-Overlay-Source": "fallback",
        },
    )
