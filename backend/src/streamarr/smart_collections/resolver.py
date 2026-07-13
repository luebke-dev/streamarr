"""Resolve external refs to local MediaItem rows.

Lookup order for each ``ExternalRef``:

1. ``provider == "local"`` — ``external_id`` is already a ``MediaItem.guid``.
2. Direct ``MediaExternalId`` match on ``(provider, external_id)``.
3. Optional title+year fallback (when both are present on the ref).

Refs are looked up in batches grouped by provider to keep round-trips low.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field

from sqlalchemy import extract, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.metadata.list_sources import ExternalRef, ListSourceMediaType
from streamarr.models.media import MediaExternalId, MediaItem


_MEDIA_TYPE_TOKENS = {
    ListSourceMediaType.MOVIE: "MOVIES",
    ListSourceMediaType.SHOW: "SHOWS",
}


@dataclass(slots=True)
class ResolveResult:
    """Output of one resolve pass."""

    resolved: list[tuple[ExternalRef, MediaItem]] = field(default_factory=list)
    unresolved: list[ExternalRef] = field(default_factory=list)


class RefResolver:
    """Look up MediaItem rows for external refs."""

    def __init__(
        self,
        db: AsyncSession,
        *,
        enable_title_year_fallback: bool = True,
    ) -> None:
        self.db = db
        self.enable_title_year_fallback = enable_title_year_fallback

    async def resolve(
        self,
        refs: list[ExternalRef],
        *,
        media_type: ListSourceMediaType,
    ) -> ResolveResult:
        if not refs:
            return ResolveResult()

        token = _MEDIA_TYPE_TOKENS[media_type]
        result = ResolveResult()
        seen_guids: set[uuid.UUID] = set()

        # Pass 1: local refs short-circuit.
        remaining: list[ExternalRef] = []
        local_guids: list[uuid.UUID] = []
        local_ref_by_guid: dict[uuid.UUID, ExternalRef] = {}
        for ref in refs:
            if ref.provider == "local":
                try:
                    guid = uuid.UUID(ref.external_id)
                except (ValueError, AttributeError):
                    result.unresolved.append(ref)
                    continue
                local_guids.append(guid)
                local_ref_by_guid[guid] = ref
            else:
                remaining.append(ref)

        if local_guids:
            items = await self._load_items(local_guids, token)
            for item in items:
                if item.guid in seen_guids:
                    continue
                seen_guids.add(item.guid)
                ref = local_ref_by_guid.pop(item.guid, None)
                if ref is not None:
                    result.resolved.append((ref, item))
            for ref in local_ref_by_guid.values():
                result.unresolved.append(ref)

        # Pass 2: batched MediaExternalId lookup grouped by provider.
        by_provider: dict[str, list[ExternalRef]] = defaultdict(list)
        for ref in remaining:
            by_provider[ref.provider].append(ref)

        unresolved_after_pass2: list[ExternalRef] = []
        for provider, prov_refs in by_provider.items():
            external_ids = [r.external_id for r in prov_refs]
            stmt = (
                select(MediaExternalId.external_id, MediaItem)
                .join(MediaItem, MediaItem.guid == MediaExternalId.media_item_guid)
                .options(
                    selectinload(MediaItem.genres),
                    selectinload(MediaItem.files),
                )
                .where(MediaExternalId.provider == provider)
                .where(MediaExternalId.external_id.in_(external_ids))
                .where(MediaItem.media_type == token)
            )
            rows = (await self.db.execute(stmt)).all()
            item_by_external_id: dict[str, MediaItem] = {}
            for external_id, item in rows:
                # If the same item has multiple external ids of the same
                # provider (rare but possible), keep the first.
                item_by_external_id.setdefault(external_id, item)

            for ref in prov_refs:
                item = item_by_external_id.get(ref.external_id)
                if item is None or item.guid in seen_guids:
                    unresolved_after_pass2.append(ref)
                    continue
                seen_guids.add(item.guid)
                result.resolved.append((ref, item))

        # Pass 3: title+year fallback (cheap LIKE-on-lower with year match).
        if self.enable_title_year_fallback:
            for ref in unresolved_after_pass2:
                item = await self._title_year_lookup(ref, token, seen_guids)
                if item is None:
                    result.unresolved.append(ref)
                    continue
                seen_guids.add(item.guid)
                result.resolved.append((ref, item))
        else:
            result.unresolved.extend(unresolved_after_pass2)

        return result

    async def _load_items(
        self, guids: list[uuid.UUID], token: str
    ) -> list[MediaItem]:
        stmt = (
            select(MediaItem)
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.files),
            )
            .where(MediaItem.guid.in_(guids))
            .where(MediaItem.media_type == token)
        )
        return list((await self.db.execute(stmt)).scalars().all())

    async def _title_year_lookup(
        self,
        ref: ExternalRef,
        token: str,
        seen_guids: set[uuid.UUID],
    ) -> MediaItem | None:
        if not ref.title or ref.year is None:
            return None
        stmt = (
            select(MediaItem)
            .options(
                selectinload(MediaItem.genres),
                selectinload(MediaItem.files),
            )
            .where(MediaItem.media_type == token)
            .where(func.lower(MediaItem.title) == ref.title.lower())
            .where(extract("year", MediaItem.release_date) == int(ref.year))
            .limit(2)
        )
        rows = (await self.db.execute(stmt)).scalars().all()
        if len(rows) != 1:
            # Ambiguous title+year (multiple matches) → treat as unresolved
            # so we don't accidentally add the wrong film. The admin can
            # always create a manual ListItem.
            return None
        item = rows[0]
        if item.guid in seen_guids:
            return None
        return item
