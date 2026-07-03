"""End-to-end overlay orchestration: DB ↔ ImageCache ↔ Renderer."""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Sequence

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from pyrate.models.media import MediaItem
from pyrate.models.overlay import (
    OverlayApplication,
    OverlayMediaScope,
    OverlayTarget,
    OverlayTemplate,
)
from pyrate.overlays.conditions import evaluate_condition
from pyrate.overlays.context import build_render_context
from pyrate.overlays.renderer import (
    OverlayRenderError,
    OverlayRenderer,
    iter_template_entries,
)
from pyrate.services.image_cache import ImageCacheError, ImageCacheService

logger = logging.getLogger(__name__)


_MEDIA_SCOPE_TOKENS = {
    "MOVIES": OverlayMediaScope.MOVIE,
    "SHOWS": OverlayMediaScope.SHOW,
}


@dataclass(slots=True)
class OverlayApplyResult:
    """Outcome of an :class:`OverlayService.apply` call."""

    media_guid: uuid.UUID
    target: OverlayTarget
    rendered: bool
    output_path: str | None = None
    source_hash: str | None = None
    templates_evaluated: int = 0
    templates_applied: int = 0
    skipped_reason: str | None = None
    debug: dict[str, Any] = field(default_factory=dict)


class OverlayService:
    """Compute and persist overlay outputs for a single media item.

    The service is stateless beyond the injected ``ImageCacheService``
    and ``OverlayRenderer``. One instance per request/task is fine.
    """

    def __init__(
        self,
        db: AsyncSession,
        *,
        image_cache: ImageCacheService | None = None,
        renderer: OverlayRenderer | None = None,
    ) -> None:
        self.db = db
        self.image_cache = image_cache or ImageCacheService()
        self.renderer = renderer or OverlayRenderer()

    @classmethod
    async def from_settings(cls, db: AsyncSession) -> "OverlayService":
        """Construct with cache_dir resolved from the settings table.

        Centralises the lookup so worker tasks and API routes don't each
        reach into SettingsService.
        """
        # Local import to avoid a circular dep when the service module
        # is imported during app boot.
        from pyrate.services.settings import SettingsService

        cache_dir = await SettingsService(db).get(
            "overlays.cache_dir", None
        )
        image_cache = ImageCacheService(cache_root=cache_dir) if cache_dir else None
        return cls(db, image_cache=image_cache)

    async def close(self) -> None:
        await self.image_cache.close()

    # ------------------------------------------------------------------
    # Public entry points
    # ------------------------------------------------------------------

    async def apply(
        self,
        media_guid: uuid.UUID,
        target: OverlayTarget = OverlayTarget.POSTER,
    ) -> OverlayApplyResult:
        """Render & cache the appropriate overlays for one item.

        Idempotent: when the precomputed ``source_hash`` already matches
        what's stored, no rendering happens and the existing application
        row is returned untouched.
        """
        item = await self._load_item(media_guid)
        if item is None:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                skipped_reason="item-not-found",
            )

        scope = _MEDIA_SCOPE_TOKENS.get(
            getattr(item.media_type, "value", str(item.media_type)),
        )
        if scope is None:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                skipped_reason="media-type-out-of-scope",
            )

        source_url = self._pick_source_url(item, target)
        if not source_url:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                skipped_reason="no-source-url",
            )

        context = build_render_context(item)
        templates = await self._load_templates(scope, target)
        applicable = [
            t for t in templates if evaluate_condition(t.condition, context)
        ]

        if not applicable:
            await self._clear_applications(media_guid, target)
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                templates_evaluated=len(templates),
                templates_applied=0,
                skipped_reason="no-applicable-templates",
            )

        try:
            original_path = await self.image_cache.get_original(
                media_guid, source_url
            )
            base_bytes = original_path.read_bytes()
        except ImageCacheError as exc:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                templates_evaluated=len(templates),
                templates_applied=len(applicable),
                skipped_reason=f"original-unavailable: {exc}",
            )

        entries = iter_template_entries(applicable)
        precomputed_hash = self.renderer.compute_hash(base_bytes, entries, context)

        existing = await self._existing_application(media_guid, target)
        if (
            existing is not None
            and existing.source_hash == precomputed_hash
        ):
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                output_path=existing.output_path,
                source_hash=existing.source_hash,
                templates_evaluated=len(templates),
                templates_applied=len(applicable),
                skipped_reason="cache-hit",
            )

        try:
            render = await asyncio.to_thread(
                self.renderer.render, base_bytes, entries, context
            )
        except OverlayRenderError as exc:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                templates_evaluated=len(templates),
                templates_applied=len(applicable),
                skipped_reason=f"render-failed: {exc}",
            )

        if render.error_count:
            return OverlayApplyResult(
                media_guid=media_guid,
                target=target,
                rendered=False,
                templates_evaluated=len(templates),
                templates_applied=len(applicable),
                skipped_reason=f"element-error: {render.error_count} element(s) failed",
            )

        output_path = await self.image_cache.write_overlay(
            media_guid, render.source_hash, render.data
        )

        await self._upsert_application(
            media_guid=media_guid,
            target=target,
            applicable=applicable,
            output_path=str(output_path),
            source_hash=render.source_hash,
        )
        await self.image_cache.prune_overlays_for_item(
            media_guid, {render.source_hash}
        )

        return OverlayApplyResult(
            media_guid=media_guid,
            target=target,
            rendered=True,
            output_path=str(output_path),
            source_hash=render.source_hash,
            templates_evaluated=len(templates),
            templates_applied=len(applicable),
            debug=render.debug,
        )

    async def list_applicable_templates(
        self, media_guid: uuid.UUID, target: OverlayTarget
    ) -> list[OverlayTemplate]:
        """Return the templates that *would* render for this item."""
        item = await self._load_item(media_guid)
        if item is None:
            return []
        scope = _MEDIA_SCOPE_TOKENS.get(
            getattr(item.media_type, "value", str(item.media_type)),
        )
        if scope is None:
            return []
        context = build_render_context(item)
        templates = await self._load_templates(scope, target)
        return [t for t in templates if evaluate_condition(t.condition, context)]

    # ------------------------------------------------------------------
    # DB helpers
    # ------------------------------------------------------------------

    async def _load_item(self, media_guid: uuid.UUID) -> MediaItem | None:
        stmt = (
            select(MediaItem)
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.files),
            )
            .where(MediaItem.guid == media_guid)
        )
        return (await self.db.execute(stmt)).scalar_one_or_none()

    async def _load_templates(
        self, scope: OverlayMediaScope, target: OverlayTarget
    ) -> list[OverlayTemplate]:
        stmt = (
            select(OverlayTemplate)
            .where(OverlayTemplate.enabled.is_(True))
            .where(OverlayTemplate.target == target)
            .where(
                OverlayTemplate.media_scope.in_(
                    (scope, OverlayMediaScope.BOTH)
                )
            )
            .order_by(OverlayTemplate.z_order.asc(), OverlayTemplate.guid)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def _existing_application(
        self, media_guid: uuid.UUID, target: OverlayTarget
    ) -> OverlayApplication | None:
        stmt = select(OverlayApplication).where(
            OverlayApplication.media_item_guid == media_guid,
            OverlayApplication.target == target,
        )
        return (await self.db.execute(stmt)).scalars().first()

    async def _clear_applications(
        self, media_guid: uuid.UUID, target: OverlayTarget
    ) -> None:
        await self.db.execute(
            sa_delete(OverlayApplication).where(
                OverlayApplication.media_item_guid == media_guid,
                OverlayApplication.target == target,
            )
        )
        await self.db.commit()

    async def _upsert_application(
        self,
        *,
        media_guid: uuid.UUID,
        target: OverlayTarget,
        applicable: Sequence[OverlayTemplate],
        output_path: str,
        source_hash: str,
    ) -> None:
        # The OverlayApplication PK is (media_item_guid, template_guid,
        # target). The renderer produces one composite per (item, target),
        # so we want a single row per (item, target) regardless of how
        # many templates went into it. We collapse to "first applicable
        # template" — the cache key (source_hash) already encodes the
        # full set, and the admin UI surfaces detail via the template list.
        primary_template = applicable[0]
        await self.db.execute(
            sa_delete(OverlayApplication).where(
                OverlayApplication.media_item_guid == media_guid,
                OverlayApplication.target == target,
            )
        )
        self.db.add(
            OverlayApplication(
                media_item_guid=media_guid,
                template_guid=primary_template.guid,
                target=target,
                output_path=output_path,
                source_hash=source_hash,
                rendered_at=datetime.now(UTC),
            )
        )
        await self.db.commit()

    @staticmethod
    def _pick_source_url(
        item: MediaItem, target: OverlayTarget
    ) -> str | None:
        raw = (
            getattr(item, "backdrop_path", None)
            if target == OverlayTarget.BACKDROP
            else getattr(item, "poster_path", None)
        )
        return _resolve_image_url(raw, target)


def _resolve_image_url(
    raw: str | None, target: OverlayTarget
) -> str | None:
    """Expand a stored image reference to a fetchable absolute URL.

    pyrate stores TMDB images as bare paths (``/abc.jpg``) and the
    frontend prepends the TMDB CDN at render time. The overlay renderer
    has to download the original, so we do the same expansion here.
    Non-TMDB references (full http(s) URLs, local filesystem paths)
    pass through unchanged.
    """
    if not raw:
        return None
    if raw.startswith(("http://", "https://")):
        return raw
    if raw.startswith("/") and not raw.startswith("//"):
        # TMDB-style relative path. Use a quality high enough to preserve
        # text legibility on Retina displays without blowing through the
        # 8 MB cap in ImageCacheService.
        size = "w780" if target == OverlayTarget.POSTER else "w1280"
        return f"https://image.tmdb.org/t/p/{size}{raw}"
    return raw
