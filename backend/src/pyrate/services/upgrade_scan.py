"""Periodic upgrade scan (Subsystem 3).

Walks monitored leaves (oldest-searched first for fairness), skips those
whose profile cutoff is already met or that have an active download, and
fans out a forced re-search + upgrade attempt. The actual "is this a real
improvement?" decision is enforced downstream by
AutoDownloadService/QualityProfileService — the scan only schedules work.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.downloads import Download, DownloadStatus
from pyrate.models.media import MediaRelease, MediaReleaseLink
from pyrate.services import upgrade_interfaces as ui
from pyrate.services.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class UpgradeScanResult:
    candidates: int = 0
    skipped_cutoff_met: int = 0
    skipped_active_dl: int = 0
    enqueued: int = 0
    skipped_disabled: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "candidates": self.candidates,
            "skipped_cutoff_met": self.skipped_cutoff_met,
            "skipped_active_dl": self.skipped_active_dl,
            "enqueued": self.enqueued,
            "skipped_disabled": self.skipped_disabled,
            "errors": self.errors,
        }


class UpgradeScanService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _has_active_download(self, media_item_guid) -> bool:
        row = await self.db.execute(
            select(MediaRelease.media_item_guid)
            .join(
                MediaReleaseLink,
                MediaReleaseLink.media_release_guid == MediaRelease.guid,
            )
            .join(
                Download,
                Download.media_release_link_guid == MediaReleaseLink.guid,
            )
            .where(MediaRelease.media_item_guid == media_item_guid)
            .where(Download.status.notin_(DownloadStatus.ACTIVE_EXCLUSIONS))
            .limit(1)
        )
        return row.first() is not None

    async def scan_batch(self, limit: int) -> UpgradeScanResult:
        res = UpgradeScanResult()
        sset = SettingsService(self.db)
        if not await sset.get("automation.upgrades_enabled", False):
            res.skipped_disabled = True
            return res

        leaves = await ui.iter_monitored_leaves(
            self.db, limit=limit, order_by_oldest_searched=True
        )
        res.candidates = len(leaves)

        due: list[str] = []
        for mi in leaves:
            if await self._has_active_download(mi.guid):
                res.skipped_active_dl += 1
                continue
            if await ui.cutoff_met(self.db, mi):
                res.skipped_cutoff_met += 1
                continue
            due.append(str(mi.guid))

        if due:
            from pyrate.worker import run_upgrade_search

            for guid in due:
                try:
                    await run_upgrade_search.kiq(guid)
                    res.enqueued += 1
                except Exception as exc:
                    res.errors.append(f"enqueue {guid}: {exc}")
        return res


async def run_upgrade_search_impl(media_item_guid: str) -> dict:
    """Force a fresh release search then attempt a profile-gated upgrade."""
    from pyrate.database import sessionmanager
    from pyrate.services.auto_download import AutoDownloadService
    from pyrate.services.quality_profile import QualityProfileService
    from pyrate.services.release_search import ReleaseSearchService

    async with sessionmanager.session() as db:
        await ReleaseSearchService(db).search_and_store_releases(
            media_item_guid, None, force=True
        )
        # The file we intend to replace = the current best existing file.
        import uuid as _uuid

        replace_guid = None
        try:
            mf = await QualityProfileService(db).best_existing_file(
                _uuid.UUID(media_item_guid)
            )
            if mf is not None:
                replace_guid = str(mf.guid)
        except Exception as exc:
            logger.debug("best_existing_file failed for %s: %s", media_item_guid, exc)

        result = await AutoDownloadService(db).auto_download(
            media_item_guid,
            None,
            None,
            upgrade=True,
            replace_media_file_guid=replace_guid,
        )
    return {"media_item": media_item_guid, "dispatched": bool(result)}
