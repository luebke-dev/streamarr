"""RSS sync (Subsystem 3).

Polls RSS-enabled indexers' latest feed and, for each *unseen* item whose
title matches a monitored favorite root, accelerates acquisition by
enqueuing the proven per-root backfill (which monitors the subtree and
fans out search + auto-download for missing leaves). Upgrades of items
that already have a file are handled by the periodic upgrade scan.

Design choice (v1, safety-first): the feed is a *trigger signal*, not a
grab source — we never grab a raw feed item directly. All real matching,
scoring and grabbing flows through the existing strict pipeline
(ReleaseSearchService + AutoDownloadService + ReleaseMatcher), so a noisy
feed cannot cause a false grab. A Redis seen-set (TTL) keeps each feed
item from re-triggering.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

import redis.asyncio as redis_async
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.config import settings
from streamarr.models.indexer import Indexer
from streamarr.parsers.release_parser import ReleaseParser
from streamarr.services.indexer import IndexerService
from streamarr.services.monitoring import MonitoringService
from streamarr.services.settings import SettingsService

logger = logging.getLogger(__name__)


@dataclass
class RssSyncResult:
    indexers_polled: int = 0
    feed_items: int = 0
    unseen: int = 0
    matched_roots: int = 0
    triggered: int = 0
    skipped_disabled: bool = False
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "indexers_polled": self.indexers_polled,
            "feed_items": self.feed_items,
            "unseen": self.unseen,
            "matched_roots": self.matched_roots,
            "triggered": self.triggered,
            "skipped_disabled": self.skipped_disabled,
            "errors": self.errors,
        }


class RssSyncService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def _redis(self) -> redis_async.Redis | None:
        try:
            return redis_async.from_url(
                settings.redis_url, encoding="utf-8", decode_responses=True
            )
        except Exception as exc:  # pragma: no cover
            logger.warning("rss-sync redis unavailable: %s", exc)
            return None

    @staticmethod
    def _seen_key(indexer_id: str, guid: str) -> str:
        h = hashlib.sha1(f"{indexer_id}|{guid}".encode()).hexdigest()
        return f"rss:seen:{h}"

    async def run_once(self) -> RssSyncResult:
        res = RssSyncResult()
        sset = SettingsService(self.db)

        if not await sset.get("automation.rss_sync_enabled", False):
            res.skipped_disabled = True
            return res

        min_interval = int(
            await sset.get("automation.rss_min_interval_minutes", 15) or 15
        )
        seen_ttl = int(
            await sset.get("automation.rss_seen_ttl_seconds", 1209600) or 1209600
        )
        grab_enabled = bool(
            await sset.get("automation.favorites_autodownload_enabled", False)
        )

        indexer_service = IndexerService(self.db)
        all_rss = await indexer_service.get_rss_indexers()
        now = datetime.now(UTC)

        def _due(ix: Indexer) -> bool:
            last = ix.last_rss_sync_at
            if last is None:
                return True
            if last.tzinfo is None:
                last = last.replace(tzinfo=UTC)
            return now - last >= timedelta(minutes=min_interval)

        due = [ix for ix in all_rss if _due(ix)]
        if not due:
            return res
        res.indexers_polled = len(due)

        try:
            feed = await indexer_service.fetch_recent_releases(due)
        except Exception as exc:
            res.errors.append(str(exc))
            feed = []
        res.feed_items = len(feed)

        # Stamp last_rss_sync_at for the polled indexers regardless of outcome.
        await self.db.execute(
            update(Indexer)
            .where(Indexer.guid.in_([ix.guid for ix in due]))
            .values(last_rss_sync_at=now)
        )
        await self.db.commit()

        if not feed:
            return res

        # Normalized-title index of monitored favorite roots.
        mon = MonitoringService(self.db)
        root_index: dict[str, str] = {}
        async for root in mon.iter_monitored_roots():
            norm = ReleaseParser.normalize_title(root.title or "")
            if len(norm) >= 2:
                root_index.setdefault(norm, str(root.guid))

        rds = await self._redis()
        matched_root_guids: set[str] = set()
        try:
            for item in feed:
                guid = str(item.get("guid") or item.get("title") or "").strip()
                indexer_id = str(item.get("indexer_id") or "")
                if not guid:
                    continue
                # Claim unseen (skip if already evaluated).
                if rds is not None:
                    try:
                        claimed = await rds.set(
                            self._seen_key(indexer_id, guid),
                            "1",
                            ex=seen_ttl,
                            nx=True,
                        )
                        if not claimed:
                            continue
                    except Exception:
                        pass
                res.unseen += 1

                title = str(item.get("title") or "")
                if not title:
                    continue
                feed_norm = ReleaseParser.normalize_title(title)
                if not feed_norm:
                    continue
                # High-precision match: release titles begin with the
                # content title. Equality or a word-boundary prefix only.
                for root_norm, root_guid in root_index.items():
                    if feed_norm == root_norm or feed_norm.startswith(
                        root_norm + " "
                    ):
                        matched_root_guids.add(root_guid)
                        break
        finally:
            if rds is not None:
                try:
                    await rds.close()
                except Exception:
                    pass

        res.matched_roots = len(matched_root_guids)
        if matched_root_guids and grab_enabled:
            from streamarr.worker import backfill_favorite_monitored

            for rg in matched_root_guids:
                try:
                    await backfill_favorite_monitored.kiq(rg)
                    res.triggered += 1
                except Exception as exc:
                    res.errors.append(f"enqueue {rg}: {exc}")

        return res
