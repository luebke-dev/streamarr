"""Backfill game platforms from ROM paths, and prune non-game (BIOS) items.

Games imported before the platform registry knew about a system (or imported
from an Arr-style metadata dump) land in the library with no ``Platform`` rows
at all, which makes every platform-driven surface — the platform picker, the
"Platforms" page section, ``?platform_id=`` filters — come up empty even though
the ROMs are all present and launchable.

Everything needed is already on disk: a ROM collection is laid out one directory
per system (``roms/atari2600/…``, ``roms/n64/…``), so
:func:`~streamarr.services.game_platforms.platform_from_path` resolves the
canonical platform for each file without any external metadata provider. This
module turns that into persisted ``Platform`` rows + ``extra_data.platform``
hints, so it is safe to run on a library with no IGDB credentials configured.

It is idempotent: re-running only adds what is missing.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from streamarr.models.media import MediaFile, MediaItem, MediaType
from streamarr.models.platform import Platform
from streamarr.services.game_platforms import (
    is_non_game_path,
    platform_from_path,
    platform_label,
)

logger = logging.getLogger(__name__)


@dataclass
class BackfillResult:
    """What a backfill run changed."""

    scanned: int = 0
    platforms_assigned: int = 0
    items_with_platform: int = 0
    unresolved: int = 0
    bios_removed: int = 0
    platforms_created: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "scanned": self.scanned,
            "platforms_assigned": self.platforms_assigned,
            "items_with_platform": self.items_with_platform,
            "unresolved": self.unresolved,
            "bios_removed": self.bios_removed,
            "platforms_created": sorted(self.platforms_created),
        }


async def _platform_row(
    db: AsyncSession,
    slug: str,
    cache: dict[str, Platform],
    created: list[str],
) -> Platform:
    """Get-or-create the ``Platform`` row for a canonical slug.

    Rows are keyed by the human label (``Platform.name`` is unique and is what
    the UI shows), so an existing IGDB-created "Nintendo 64" row is reused
    instead of duplicated as "n64".
    """
    if slug in cache:
        return cache[slug]

    name = platform_label(slug)
    row = (
        await db.execute(select(Platform).where(Platform.name == name))
    ).scalars().first()
    if row is None:
        row = Platform(name=name)
        db.add(row)
        await db.flush()
        created.append(name)
        logger.info("Created platform %r", name)

    cache[slug] = row
    return row


async def backfill_game_platforms(
    db: AsyncSession,
    *,
    remove_bios: bool = True,
    dry_run: bool = False,
) -> BackfillResult:
    """Assign platforms to every GAMES item from its ROM file path.

    Args:
        db: Open session; the caller commits unless ``dry_run``.
        remove_bios: Also delete items whose files are BIOS/firmware images
            (``roms/bios/…``). These are not playable titles and only exist in
            the library because the scanner ingested every ROM-extension file.
        dry_run: Compute and report changes without persisting them.

    Returns:
        BackfillResult: counts plus the names of newly created platforms.
    """
    result = BackfillResult()
    cache: dict[str, Platform] = {}

    items = (
        (
            await db.execute(
                select(MediaItem)
                .options(selectinload(MediaItem.platforms))
                .where(MediaItem.media_type == MediaType.GAMES)
            )
        )
        .scalars()
        .all()
    )

    # One query for all game files instead of a per-item lazy load.
    file_rows = (
        await db.execute(
            select(MediaFile.media_item_guid, MediaFile.file_path).where(
                MediaFile.media_item_guid.in_([i.guid for i in items])
            )
        )
    ).all() if items else []

    paths_by_item: dict[object, list[str]] = {}
    for item_guid, file_path in file_rows:
        if file_path:
            paths_by_item.setdefault(item_guid, []).append(file_path)

    bios_guids: list[object] = []

    for item in items:
        result.scanned += 1
        paths = paths_by_item.get(item.guid, [])

        if remove_bios and paths and all(is_non_game_path(p) for p in paths):
            bios_guids.append(item.guid)
            continue

        slugs = {platform_from_path(p) for p in paths} - {None}
        # Fall back to a platform hint an earlier import already stamped.
        if not slugs:
            hinted = (item.extra_data or {}).get("platform") if isinstance(
                item.extra_data, dict
            ) else None
            from streamarr.services.game_platforms import normalize_platform

            hinted_slug = normalize_platform(hinted)
            if hinted_slug:
                slugs = {hinted_slug}

        if not slugs:
            result.unresolved += 1
            continue

        existing = {p.name for p in item.platforms}
        added = False
        for slug in sorted(slugs):
            row = await _platform_row(db, slug, cache, result.platforms_created)
            if row.name not in existing:
                item.platforms.append(row)
                existing.add(row.name)
                result.platforms_assigned += 1
                added = True

        # Keep the free-text hint in sync so the launch resolver and the
        # platform picker agree on one canonical slug.
        primary = sorted(slugs)[0]
        raw = item.extra_data
        data = dict(raw) if isinstance(raw, dict) else {}
        if data.get("platform") != primary:
            data["platform"] = primary
            item.extra_data = data
            added = True

        if added or existing:
            result.items_with_platform += 1

    if bios_guids:
        result.bios_removed = len(bios_guids)
        if not dry_run:
            await db.execute(
                delete(MediaItem).where(MediaItem.guid.in_(bios_guids))
            )

    if dry_run:
        await db.rollback()
    else:
        await db.commit()

    logger.info("Game platform backfill: %s", result.as_dict())
    return result
