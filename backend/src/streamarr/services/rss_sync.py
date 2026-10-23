"""RSS sync (Subsystem 3).

Polls RSS-enabled indexers' latest feed and, for each *unseen* item whose
title matches a monitored favorite root, acquires the release it announces:
the feed title is parsed for its season/episode, resolved to that leaf item and
searched. Only the announced episode is fetched - not the whole show - because a
feed hit means "this episode is out now", which is exactly what Sonarr acts on.
Missing older episodes are the reconcile sweep's job.

Design choice (safety-first): the feed is a *trigger signal*, not a grab source -
we never grab a raw feed item directly. All real matching, scoring and grabbing
flows through the existing strict pipeline (ReleaseSearchService +
AutoDownloadService + ReleaseMatcher), so a noisy feed cannot cause a false grab.
A Redis seen-set (TTL) keeps each feed item from re-triggering.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

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
        feed_limit = int(await sset.get("automation.rss_feed_limit", 100) or 100)
        max_grabs = int(
            await sset.get("automation.rss_max_grabs_per_tick", 3) or 3
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
            feed = await indexer_service.fetch_recent_releases(
                due, per_indexer_limit=feed_limit
            )
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
        matched: dict[str, list[str]] = {}
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
                        matched.setdefault(root_guid, []).append(title)
                        break
        finally:
            if rds is not None:
                try:
                    await rds.close()
                except Exception:
                    pass

        res.matched_roots = len(matched)
        if matched and grab_enabled:
            leaves = await self._resolve_announced_leaves(matched)
            if len(leaves) > max_grabs:
                logger.info(
                    "RSS: %d announced episodes, grabbing the first %d this tick",
                    len(leaves), max_grabs,
                )
                leaves = leaves[:max_grabs]
            if leaves:
                from streamarr.worker import (
                    auto_download_media_item,
                    search_media_item_releases,
                )

                for leaf_guid in leaves:
                    try:
                        await search_media_item_releases.kiq(
                            str(leaf_guid), None, force=True
                        )
                        await auto_download_media_item.kiq(
                            str(leaf_guid), None, None, backfill=True
                        )
                        res.triggered += 1
                    except Exception as exc:
                        res.errors.append(f"enqueue {leaf_guid}: {exc}")

        return res

    async def _resolve_announced_leaves(
        self, matched: dict[str, list[str]]
    ) -> list[Any]:
        """Map matched feed titles to the concrete item they announce.

        A series release carries SxxEyy, so the announced episode can be looked
        up under the matched show. Movies are their own leaf. Anything that
        cannot be resolved is skipped on purpose: fanning out to the whole show
        because of a single feed item would queue every missing episode at once.
        """
        from sqlalchemy import select

        from streamarr.models.media import MediaItem, MediaType

        leaves: list[Any] = []
        seen: set[str] = set()

        async def _has_file(guid: Any) -> bool:
            from streamarr.models.media import MediaFile

            return bool(
                await self.db.scalar(
                    select(MediaFile.guid).where(MediaFile.media_item_guid == guid).limit(1)
                )
            )

        for root_guid, titles in matched.items():
            try:
                root_uuid = uuid.UUID(str(root_guid))
            except (ValueError, TypeError):
                logger.warning("RSS: ignoring malformed root guid %r", root_guid)
                continue
            root = await self.db.get(MediaItem, root_uuid)
            if root is None:
                continue

            if root.media_type == MediaType.MOVIES:
                if not await _has_file(root.guid):
                    leaves.append(root.guid)
                continue

            root_norm = ReleaseParser.normalize_title(root.title or "")
            for title in titles:
                parsed = ReleaseParser.parse_show_release(title)
                season_number, episode_number = parsed.season, parsed.episode
                if season_number is None or episode_number is None:
                    logger.debug(
                        "RSS: '%s' announces no episode for %s, skipping",
                        title, root.title,
                    )
                    continue
                season = await self.db.scalar(
                    select(MediaItem)
                    .where(MediaItem.parent_guid == root.guid)
                    .where(MediaItem.sequence_number == season_number)
                )
                if season is None:
                    logger.debug(
                        "RSS: %s has no season %s", root.title, season_number
                    )
                    continue
                episode = await self.db.scalar(
                    select(MediaItem)
                    .where(MediaItem.parent_guid == season.guid)
                    .where(MediaItem.sequence_number == episode_number)
                )
                if episode is None:
                    logger.debug(
                        "RSS: %s S%s has no episode %s",
                        root.title, season_number, episode_number,
                    )
                    continue
                if await _has_file(episode.guid):
                    logger.debug(
                        "RSS: %s S%02dE%02d already has a file (%s)",
                        root_norm, season_number, episode_number, title,
                    )
                    continue
                if str(episode.guid) in seen:
                    continue
                seen.add(str(episode.guid))
                leaves.append(episode.guid)

        return leaves
