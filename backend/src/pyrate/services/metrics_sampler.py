"""Periodic Prometheus gauge sampler for database-backed pyrate metrics."""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import time
from collections import defaultdict
from pathlib import Path

import redis.asyncio as redis_async
from sqlalchemy import func, select, text

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.models.device import Device
from pyrate.models.downloader import Downloader
from pyrate.models.downloads import Download
from pyrate.models.favorite import Favorite
from pyrate.models.indexer import Indexer
from pyrate.models.library import Library
from pyrate.models.list import List
from pyrate.models.media import MediaFile, MediaItem, MediaRelease
from pyrate.models.notification import Notification
from pyrate.models.user import User
from pyrate.models.viewing_history import ViewingHistory
from pyrate.services.download_status import download_phase, download_status_value
from pyrate.services.downloader import DownloaderService
from pyrate.services.elasticsearch import elasticsearch_service
from pyrate.services.observability import (
    clear_downloader_client_stats,
    record_downloader_client_poll,
    record_metrics_sampler,
    set_downloader_client_health,
    set_downloader_client_jobs,
    set_inventory_stats,
    set_service_health,
    set_storage_stats,
)

logger = logging.getLogger(__name__)


def _sampler_interval() -> float:
    raw = os.getenv("PYRATE_METRICS_SAMPLE_INTERVAL_SECONDS", "30")
    try:
        return max(5.0, float(raw))
    except ValueError:
        return 30.0


def _string(value: object | None) -> str:
    if value is None:
        return "unknown"
    return str(getattr(value, "value", value)).strip() or "unknown"


def _bool(value: object) -> str:
    return str(bool(value)).lower()


def _configured_storage_paths() -> dict[str, Path]:
    paths = {
        "cache": Path(os.getenv("PYRATE_ARTWORK_CACHE_DIR", "/cache/artwork")).parent,
        "downloads": Path("/downloads"),
        "usenet_downloads": Path("/usenet-downloads"),
        "torrent_downloads": Path("/torrent-downloads"),
        "spotdl_downloads": Path("/spotdl-downloads"),
        "library_movies": Path("/library/movies"),
        "library_shows": Path("/library/shows"),
        "library_music": Path("/library/music"),
        "library_books": Path("/library/books"),
    }
    return {name: path for name, path in paths.items() if path.exists()}


async def _sample_service_health(db) -> None:
    try:
        await db.execute(text("SELECT 1"))
    except Exception:
        set_service_health("database", False)
    else:
        set_service_health("database", True)

    redis_client = redis_async.from_url(settings.redis_url)
    try:
        await redis_client.ping()
    except Exception:
        set_service_health("redis", False)
    else:
        set_service_health("redis", True)
    finally:
        await redis_client.aclose()

    try:
        healthy = bool(
            elasticsearch_service.client and await elasticsearch_service.client.ping()
        )
    except Exception:
        healthy = False
    set_service_health("elasticsearch", healthy)


async def _sample_downloader_clients(db) -> None:
    clear_downloader_client_stats()
    result = await db.execute(select(Downloader))
    downloaders = result.scalars().all()
    service = DownloaderService(db)
    for downloader in downloaders:
        downloader_type = _string(downloader.type).lower()
        downloader_label = _string(downloader.label)
        started = time.perf_counter()
        client = None
        try:
            client = service.get_client(downloader)
            jobs = await client.get_downloads()
        except Exception:
            record_downloader_client_poll(
                downloader_type=downloader_type,
                downloader_label=downloader_label,
                status="error",
                duration_seconds=time.perf_counter() - started,
            )
            set_downloader_client_health(
                downloader_type=downloader_type,
                downloader_label=downloader_label,
                healthy=False,
            )
            logger.debug(
                "Failed to poll downloader client metrics for %s",
                downloader_label,
                exc_info=True,
            )
        else:
            status_counts: dict[str, int] = defaultdict(int)
            for job in jobs:
                status_counts[download_status_value(job.get("status")) or "unknown"] += 1
            set_downloader_client_health(
                downloader_type=downloader_type,
                downloader_label=downloader_label,
                healthy=True,
            )
            set_downloader_client_jobs(
                downloader_type=downloader_type,
                downloader_label=downloader_label,
                statuses=dict(status_counts),
            )
            record_downloader_client_poll(
                downloader_type=downloader_type,
                downloader_label=downloader_label,
                status="success",
                duration_seconds=time.perf_counter() - started,
            )
        finally:
            close = getattr(client, "close", None)
            if close:
                try:
                    await close()
                except Exception:
                    logger.debug("Failed to close downloader client", exc_info=True)


def _sample_storage() -> None:
    for name, path in _configured_storage_paths().items():
        try:
            usage = shutil.disk_usage(path)
        except OSError:
            continue
        set_storage_stats(
            name,
            total=usage.total,
            used=usage.used,
            free=usage.free,
        )


async def sample_inventory_metrics() -> None:
    """Refresh database-backed Prometheus gauges."""
    async with sessionmanager.session() as db:
        await _sample_service_health(db)
        media_items: dict[tuple[str, str], int] = {}
        result = await db.execute(
            select(
                MediaItem.media_type,
                MediaItem.availability_status,
                func.count(MediaItem.guid),
            ).group_by(MediaItem.media_type, MediaItem.availability_status)
        )
        for media_type, availability_status, count in result.all():
            media_items[(_string(media_type), _string(availability_status))] = int(count)

        media_files: dict[str, int] = {}
        result = await db.execute(
            select(MediaItem.media_type, func.count(MediaFile.guid))
            .join(MediaItem, MediaFile.media_item_guid == MediaItem.guid)
            .group_by(MediaItem.media_type)
        )
        for media_type, count in result.all():
            media_files[_string(media_type)] = int(count)

        media_releases: dict[str, int] = {}
        result = await db.execute(
            select(MediaItem.media_type, func.count(MediaRelease.guid))
            .join(MediaItem, MediaRelease.media_item_guid == MediaItem.guid)
            .group_by(MediaItem.media_type)
        )
        for media_type, count in result.all():
            media_releases[_string(media_type)] = int(count)

        downloads: dict[tuple[str, str, str, str], int] = {}
        result = await db.execute(
            select(
                Download.status,
                Download.type,
                Downloader.type,
                func.count(Download.guid),
            )
            .join(Downloader, Download.downloader_id == Downloader.guid)
            .group_by(Download.status, Download.type, Downloader.type)
        )
        for status, media_type, downloader_type, count in result.all():
            normalized_status = download_status_value(status) or "unknown"
            downloads[
                (
                    normalized_status,
                    download_phase(status) or "unknown",
                    _string(media_type),
                    _string(downloader_type),
                )
            ] = int(count)

        progress_sum: dict[str, float] = defaultdict(float)
        progress_count: dict[str, int] = defaultdict(int)
        result = await db.execute(
            select(Download.status, Download.progress).where(Download.progress.is_not(None))
        )
        for status, progress in result.all():
            normalized_status = download_status_value(status) or "unknown"
            progress_sum[normalized_status] += float(progress or 0)
            progress_count[normalized_status] += 1
        download_progress = {
            status: progress_sum[status] / progress_count[status]
            for status in progress_count
            if progress_count[status]
        }

        downloaders: dict[str, int] = {}
        result = await db.execute(
            select(Downloader.type, func.count(Downloader.guid)).group_by(Downloader.type)
        )
        for downloader_type, count in result.all():
            downloaders[_string(downloader_type)] = int(count)

        indexers: dict[str, int] = {}
        result = await db.execute(
            select(Indexer.type, func.count(Indexer.guid)).group_by(Indexer.type)
        )
        for indexer_type, count in result.all():
            indexers[_string(indexer_type)] = int(count)

        libraries: dict[tuple[str, str], int] = {}
        result = await db.execute(
            select(Library.type, Library.enabled, func.count(Library.guid)).group_by(
                Library.type, Library.enabled
            )
        )
        for library_type, enabled, count in result.all():
            libraries[(_string(library_type), str(bool(enabled)).lower())] = int(count)

        users: dict[tuple[str, str, str], int] = {}
        result = await db.execute(
            select(
                User.is_active,
                User.is_superuser,
                User.email_verified,
                func.count(User.guid),
            ).group_by(User.is_active, User.is_superuser, User.email_verified)
        )
        for active, superuser, email_verified, count in result.all():
            users[(_bool(active), _bool(superuser), _bool(email_verified))] = int(count)

        devices: dict[tuple[str, str, str], int] = {}
        result = await db.execute(
            select(
                Device.is_active,
                Device.is_trusted,
                Device.is_playing,
                func.count(Device.guid),
            ).group_by(Device.is_active, Device.is_trusted, Device.is_playing)
        )
        for active, trusted, playing, count in result.all():
            devices[(_bool(active), _bool(trusted), _bool(playing))] = int(count)

        favorites: dict[str, int] = {}
        result = await db.execute(
            select(MediaItem.media_type, func.count(Favorite.guid))
            .join(MediaItem, Favorite.media_item_guid == MediaItem.guid)
            .group_by(MediaItem.media_type)
        )
        for media_type, count in result.all():
            favorites[_string(media_type)] = int(count)

        viewing_history: dict[tuple[str, str], int] = {}
        result = await db.execute(
            select(
                MediaItem.media_type,
                ViewingHistory.is_completed,
                func.count(ViewingHistory.guid),
            )
            .join(MediaItem, ViewingHistory.media_item_guid == MediaItem.guid)
            .group_by(MediaItem.media_type, ViewingHistory.is_completed)
        )
        for media_type, completed, count in result.all():
            viewing_history[(_string(media_type), _bool(completed))] = int(count)

        notifications: dict[tuple[str, str], int] = {}
        result = await db.execute(
            select(
                Notification.notification_type,
                Notification.status,
                func.count(Notification.guid),
            ).group_by(Notification.notification_type, Notification.status)
        )
        for notification_type, status, count in result.all():
            notifications[(_string(notification_type), _string(status))] = int(count)

        lists: dict[tuple[str, str, str], int] = {}
        result = await db.execute(
            select(
                List.list_type,
                List.visibility,
                List.is_active,
                func.count(List.guid),
            ).group_by(List.list_type, List.visibility, List.is_active)
        )
        for list_type, visibility, active, count in result.all():
            lists[(_string(list_type), _string(visibility), _bool(active))] = int(count)

        missing_artwork: dict[tuple[str, str], int] = {}
        result = await db.execute(
            select(MediaItem.media_type, func.count(MediaItem.guid))
            .where(MediaItem.poster_path.is_(None))
            .group_by(MediaItem.media_type)
        )
        for media_type, count in result.all():
            missing_artwork[(_string(media_type), "poster")] = int(count)
        result = await db.execute(
            select(MediaItem.media_type, func.count(MediaItem.guid))
            .where(MediaItem.backdrop_path.is_(None))
            .group_by(MediaItem.media_type)
        )
        for media_type, count in result.all():
            missing_artwork[(_string(media_type), "backdrop")] = int(count)

        set_inventory_stats(
            media_items=media_items,
            media_files=media_files,
            media_releases=media_releases,
            downloads=downloads,
            download_progress=download_progress,
            downloaders=downloaders,
            indexers=indexers,
            libraries=libraries,
            users=users,
            devices=devices,
            favorites=favorites,
            viewing_history=viewing_history,
            notifications=notifications,
            lists=lists,
            missing_artwork=missing_artwork,
        )
        await _sample_downloader_clients(db)
        _sample_storage()


async def metrics_sampler_loop(stop_event: asyncio.Event) -> None:
    """Run inventory sampling until the app shuts down."""
    interval = _sampler_interval()
    logger.info("Starting metrics sampler", extra={"interval_seconds": interval})
    while not stop_event.is_set():
        started = time.perf_counter()
        try:
            await sample_inventory_metrics()
        except Exception:
            record_metrics_sampler("error", time.perf_counter() - started)
            logger.warning("Metrics sampler run failed", exc_info=True)
        else:
            record_metrics_sampler("success", time.perf_counter() - started)

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval)
        except TimeoutError:
            pass

    logger.info("Metrics sampler stopped")
