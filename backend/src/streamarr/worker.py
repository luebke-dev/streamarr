# worker.py
import asyncio
import logging
import re
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import selectinload

from streamarr.config import settings
from streamarr.database import sessionmanager
from streamarr.models.downloads import Download

# Unified media models
from streamarr.models.media import (
    MediaFile,
    MediaItem,
    MediaRelease,
    MediaReleaseLink,
    MediaType,
)
from streamarr.models.user import User
from streamarr.libraries import get_plugin_instance
from streamarr.metadata.tmdb import TMDB
from streamarr.services import (
    DownloaderService,
    DownloadService,
    IndexerService,
    NotificationService,
    get_tmdb_api_key,
)
from streamarr.services.email import email_service
from streamarr.services.library import LibraryService
from streamarr.services.media import MediaService
from streamarr.services.settings import SettingsService
from streamarr.services.task_events import (
    record_worker_task_event,
)
from streamarr.services.trending import TrendingService
from streamarr.workers.cleanup import StorageCleanupWorker
from streamarr.workers.downloads import DownloadRefreshWorker
from streamarr.workers.playback import TranscodeMonitorWorker
from streamarr.workers.runtime import broker, create_scheduler
from streamarr.workers.mass_operation_worker import (
    run_mass_operation_rule_impl,
    tick_mass_operations_impl,
)
from streamarr.workers.overlay_worker import (
    bulk_rerender_for_template_impl,
    render_overlay_for_item_impl,
    tick_render_missing_overlays_impl,
)
from streamarr.workers.favorites_monitor_worker import (
    backfill_favorite_monitored_impl,
    tick_favorites_reconcile_impl,
    unmonitor_favorite_impl,
)
from streamarr.workers.rss_sync_worker import rss_sync_impl
from streamarr.workers.upgrade_scan_worker import tick_upgrade_scan_impl
# Registers the incremental/delta Elasticsearch sync tasks (and their
# schedule) on the broker so the worker process consumes them.
from streamarr.workers import search_index_worker  # noqa: F401
from streamarr.workers.smart_collection_worker import (
    run_smart_collection_rule_impl,
    tick_smart_collections_impl,
)

logger = logging.getLogger(__name__)


def _get_external_id(media_item: MediaItem, provider: str) -> str | None:
    """Return the first external ID for a provider from a loaded media item."""
    for ext_id in media_item.external_ids:
        if ext_id.provider == provider:
            return ext_id.external_id
    return None


@broker.task(schedule=[{"cron": "* * * * *"}])
async def refresh_downloads() -> None:
    """Refresh downloads from all configured downloaders every 10 seconds.

    Taskiq cron only supports per-minute granularity, so this task
    loops internally and kicks off refresh_downloader tasks every
    10 seconds for the duration of one minute.

    Note: spotdl also sends webhooks for immediate notifications,
    but polling is kept as the primary mechanism for all downloaders.
    """
    await DownloadRefreshWorker(DownloaderService, DownloadService).refresh_downloads(
        refresh_downloader
    )


async def _add_download_impl(
    release_guid: str, media_type: str, user_guid: str | None = None
) -> None:
    """Shared implementation for adding downloads of any media type."""
    async with sessionmanager.session() as db:
        download_service = DownloadService(db)
        downloaders = await DownloaderService(db).get_all()

        uid = uuid.UUID(user_guid) if user_guid else None
        download = await download_service.add_media_download(
            release_guid, downloaders, media_type, uid
        )
        if download:
            logger.info("Successfully added %s download: %s", media_type, download.title)

            # Publish WebSocket event so the UI updates in real-time
            try:
                from streamarr.services.redis_event import get_redis_event_service

                # Resolve media_item_guid from release link chain
                result = await db.execute(
                    select(MediaReleaseLink)
                    .where(MediaReleaseLink.guid == release_guid)
                    .options(
                        selectinload(MediaReleaseLink.release)
                    )
                )
                link = result.scalar_one_or_none()
                if link and link.release:
                    redis_service = get_redis_event_service()
                    await redis_service.publish_media_item_updated(
                        media_item_id=link.release.media_item_guid,
                        update_type="download_updated",
                        data={
                            "download_title": download.title,
                            "download_status": download.status,
                        },
                    )
            except Exception as e:
                logger.debug("Failed to publish download_updated event: %s", e)
        else:
            logger.error("Failed to add %s download for release %s", media_type, release_guid)


@broker.task
async def add_download(release_guid: str, user_guid: str | None = None) -> None:
    """Add a movie download."""
    await _add_download_impl(release_guid, "movie", user_guid)


@broker.task
async def add_show_download(release_guid: str, user_guid: str | None = None) -> None:
    """Add an episode download."""
    await _add_download_impl(release_guid, "show", user_guid)


@broker.task
async def add_music_download(release_guid: str, user_guid: str | None = None) -> None:
    """Add a music download."""
    await _add_download_impl(release_guid, "music", user_guid)


async def _maybe_trigger_intro_detection(db, result: dict) -> None:
    """Auto-trigger intro detection after a TV episode is imported."""
    try:
        media_item_guid = result.get("media_item_guid")
        if not media_item_guid:
            return

        item_result = await db.execute(
            select(MediaItem).where(MediaItem.guid == uuid.UUID(media_item_guid))
        )
        media_item = item_result.scalar_one_or_none()
        if not media_item or not media_item.parent_guid:
            return

        # Check this is an episode (has season parent which has show parent)
        season_result = await db.execute(
            select(MediaItem).where(MediaItem.guid == media_item.parent_guid)
        )
        season = season_result.scalar_one_or_none()
        if not season or not season.parent_guid:
            return

        # Fingerprint is now extracted during episode import in shows.py.
        # Just check if enough episodes have fingerprints to trigger detection.

        # Count episodes with fingerprints in this season
        ep_count = await db.scalar(
            select(func.count(func.distinct(MediaItem.guid)))
            .join(MediaFile, MediaFile.media_item_guid == MediaItem.guid)
            .where(
                MediaItem.parent_guid == season.guid,
                MediaFile.chromaprint_raw.isnot(None),
            )
        )

        if (ep_count or 0) >= 2:
            logger.info(
                "Auto-triggering intro detection for season %s (%d episodes with fingerprints)",
                season.guid, ep_count,
            )
            await detect_intro_outro_season.kiq(str(season.guid))
    except Exception as e:
        logger.warning("Failed to auto-trigger intro detection: %s", e)


async def _maybe_trigger_credits_detection(result: dict) -> None:
    """Auto-trigger credits detection after a movie is imported."""
    try:
        media_item_guid = result.get("media_item_guid")
        # Only trigger for movies (result has movie_title, not season_number)
        if not media_item_guid or "movie_title" not in result:
            return

        logger.info(
            "Auto-triggering credits detection for movie %s",
            result.get("movie_title", media_item_guid),
        )
        await detect_credits_movie.kiq(media_item_guid)
    except Exception as e:
        logger.warning("Failed to auto-trigger credits detection: %s", e)


@broker.task
async def promote_favorite_to_library(media_item_guid: str) -> None:
    """Copy an rclone-registered media_file into /library after favoriting."""
    from streamarr.libraries import get_library_type_for_media_item_type, get_plugin_instance
    from streamarr.models.media import MediaFile, MediaItem

    try:
        async with sessionmanager.session() as db:
            from sqlalchemy import select

            item = await db.get(MediaItem, media_item_guid)
            if not item:
                return

            library_type = get_library_type_for_media_item_type(item.media_type)
            plugin = get_plugin_instance(item.media_type) or (
                get_plugin_instance(library_type) if library_type else None
            )
            if not plugin or not hasattr(plugin, "promote_to_library"):
                return

            files_result = await db.execute(
                select(MediaFile).where(MediaFile.media_item_guid == item.guid)
            )
            for mf in files_result.scalars().all():
                try:
                    await plugin.promote_to_library(mf, db)
                except Exception as e:
                    logger.warning(
                        "promote_to_library failed for %s: %s", mf.file_path, e,
                    )
    except Exception as e:
        logger.error("promote_favorite_to_library failed for %s: %s", media_item_guid, e)


@broker.task(retry_on_error=True, delay=30)
async def handle_completed_download(
    external_id: str, path: str, expected_files: list[str] | None = None,
) -> None:
    """Handle a completed download by its external ID."""
    try:
        async with sessionmanager.session() as db:
            download_service = DownloadService(db)
            result = await download_service.handle_completed_download(
                external_id, path, expected_files=expected_files,
            )

            if result["success"]:
                logger.info(
                    "Handled completed download %s: %s files imported",
                    external_id, result.get('files_imported', 0),
                )

                # Auto-trigger intro detection for TV show episodes
                await _maybe_trigger_intro_detection(db, result)

                # Auto-trigger credits detection for movies
                await _maybe_trigger_credits_detection(result)
            else:
                logger.error(
                    "Failed to handle completed download %s: %s",
                    external_id, result.get('error'),
                )

                # If the release was blacklisted, automatically try the next best release
                retry_info = await download_service.handle_failed_download(result, external_id)
                if retry_info:
                    await auto_download_media_item.kiq(
                        retry_info["media_item_guid"], None, retry_info["user_guid"]
                    )

    except Exception as e:
        logger.error("Failed to handle completed download %s: %s", external_id, e)
        raise


@broker.task()
async def refresh_downloader(downloader_id: str) -> None:
    """Refresh a specific downloader by its ID."""
    await DownloadRefreshWorker(DownloaderService, DownloadService).refresh_downloader(
        downloader_id,
        handle_completed_download_task=handle_completed_download,
        auto_download_media_item_task=auto_download_media_item,
    )

@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def import_trending_movies() -> None:
    """Import trending movies from TMDB and update trending list."""
    logger.info("Starting import of trending movies at %s", datetime.now(UTC))
    try:
        async with sessionmanager.session() as db:
            service = TrendingService(db)
            new_ids = await service.get_new_trending_movie_ids()
            for tmdb_id in new_ids:
                await import_movie.kiq(tmdb_id)
            if new_ids:
                logger.info("Waiting 30 seconds for movie imports to complete...")
                await asyncio.sleep(30)
            await service.update_trending_movies_list()
        logger.info("Import of trending movies completed successfully!")
    except Exception as e:
        logger.error("Failed to import trending movies: %s", e)
        raise


@broker.task
async def import_movie_metadata(title: str, year: int) -> None:
    """Import a movie by searching for title and year."""
    try:
        logger.info("Starting import for movie '%s' (%s)", title, year)
        async with sessionmanager.session() as db:
            tmdb_api_key = await get_tmdb_api_key(db)
            tmdb = TMDB(api_key=tmdb_api_key)
            search_results = await tmdb.search_movies(query=title, year=year)

            if not search_results.get("results"):
                logger.warning("No results found for '%s' (%s)", title, year)
                return

            # Take the first result
            movie_result = search_results["results"][0]
            tmdb_id = movie_result.get("id")

            if tmdb_id:
                await import_movie.kiq(tmdb_id)
                logger.info("Queued import for movie '%s' with TMDB ID %s", title, tmdb_id)
            else:
                logger.warning("No TMDB ID found for '%s' (%s)", title, year)

    except Exception as e:
        logger.error("Failed to import movie '%s' (%s): %s", title, year, e)
        raise


async def _notify_import(media_item, media_type_str: str, **extra):
    """Send Redis notification after successful import."""
    try:
        from streamarr.services.redis_event import get_redis_event_service
        redis_service = get_redis_event_service()
        await redis_service.publish(
            channel="search:imports",
            event="media_imported",
            data={
                "guid": str(media_item.guid),
                "title": media_item.title,
                "media_type": media_type_str,
                "poster_path": media_item.poster_path,
                **extra,
            },
        )
    except Exception as e:
        # Notification is best-effort — never let a Redis blip fail the
        # import. Log so a broken pubsub doesn't go silent forever.
        logger.warning("Failed to publish import notification: %s", e)


async def _queue_overlay_render(media_item) -> None:
    """Best-effort queue of a poster overlay render after import or probe.

    Idempotent and silent on failure — the renderer cache-hash short
    circuits when nothing has changed, and a missed enqueue just delays
    the first browse-time render to the next ``tick_overlay_renders``.
    """
    if not media_item or not getattr(media_item, "poster_path", None):
        return
    media_type = getattr(media_item, "media_type", None)
    mt_value = getattr(media_type, "value", str(media_type))
    if mt_value not in ("MOVIES", "SHOWS"):
        return
    try:
        await render_overlay_for_item.kiq(str(media_item.guid), "POSTER")
    except Exception as exc:
        logger.debug(
            "queue overlay render skipped for %s: %s",
            getattr(media_item, "guid", "?"),
            exc,
        )


@broker.task
async def backfill_age_ratings() -> None:
    """Populate ``min_age`` / ``content_rating`` for movies and shows that lack them.

    One-shot admin task: walks every top-level MOVIES/SHOWS MediaItem with a
    TMDB external_id and a NULL ``min_age``, fetches TMDB details, and stores
    the parsed certification. Safe to re-run.
    """
    from streamarr.metadata.tmdb import TMDB
    from streamarr.models.media import MediaExternalId, MediaItem, MediaType
    from streamarr.utils.age_rating import parse_min_age

    logger.info("Starting age-rating backfill at %s", datetime.now(UTC))
    updated = 0
    async with sessionmanager.session() as db:
        api_key = await get_tmdb_api_key(db)
        if not api_key:
            logger.warning("TMDB API key not configured; skipping backfill")
            return

        rows = await db.execute(
            select(MediaItem, MediaExternalId.external_id)
            .join(MediaExternalId, MediaExternalId.media_item_guid == MediaItem.guid)
            .where(
                MediaItem.media_type.in_((MediaType.MOVIES, MediaType.SHOWS)),
                MediaItem.parent_guid.is_(None),
                MediaItem.min_age.is_(None),
                MediaExternalId.provider == "tmdb",
            )
        )
        items = rows.all()

        tmdb = TMDB(api_key=api_key)
        try:
            for media_item, tmdb_id in items:
                try:
                    if media_item.media_type == MediaType.MOVIES:
                        raw = await tmdb.get_movie_details(str(tmdb_id))
                        cert = TMDB.extract_certification(raw, "movie")
                    else:
                        raw = await tmdb.get_show_details(str(tmdb_id))
                        cert = TMDB.extract_certification(raw, "tv")
                    if not cert:
                        continue
                    media_item.content_rating = cert
                    media_item.min_age = parse_min_age(cert)
                    updated += 1
                except Exception as e:
                    logger.warning(
                        "Backfill failed for %s (tmdb %s): %s", media_item.guid, tmdb_id, e,
                    )
            await db.commit()
        finally:
            await tmdb.close()

    logger.info("Age-rating backfill complete: %s items updated", updated)


@broker.task(retry_on_error=True, delay=30)
async def import_movie(tmdb_id: int) -> None:
    """Import a movie by its TMDB ID."""
    try:
        async with sessionmanager.session() as db:
            tmdb_api_key = await get_tmdb_api_key(db)
            if not tmdb_api_key:
                logger.error("TMDB API key not configured")
                return

            tmdb = TMDB(api_key=tmdb_api_key)
            try:
                from streamarr.services.metadata_refresh import MetadataService
                service = MetadataService(db)
                media_item = await service.import_media(
                    plugin=tmdb,
                    external_id=str(tmdb_id),
                    provider_name="tmdb",
                    media_type=MediaType.MOVIES,
                )
                if media_item:
                    await _notify_import(media_item, "MOVIES", tmdb_id=tmdb_id)
                    await _queue_overlay_render(media_item)
            finally:
                await tmdb.close()

    except Exception as e:
        logger.error("Failed to import movie %s: %s", tmdb_id, e)
        raise


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def import_trending_shows() -> None:
    """Import trending TV shows from TMDB and update trending list."""
    logger.info("Starting import of trending shows at %s", datetime.now(UTC))
    try:
        async with sessionmanager.session() as db:
            service = TrendingService(db)
            new_ids = await service.get_new_trending_show_ids()
            for tmdb_id in new_ids:
                await import_show.kiq(tmdb_id)
            if new_ids:
                logger.info("Waiting 30 seconds for show imports to complete...")
                await asyncio.sleep(30)
            await service.update_trending_shows_list()
        logger.info("Import of trending shows completed successfully!")
    except Exception as e:
        logger.error("Failed to import trending shows: %s", e)
        raise


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def import_trending_games() -> None:
    """Import trending games from IGDB and update trending list."""
    logger.info("Starting import of trending games at %s", datetime.now(UTC))
    try:
        async with sessionmanager.session() as db:
            service = TrendingService(db)
            new_ids = await service.get_new_trending_game_ids()
            for igdb_id in new_ids:
                await import_game.kiq(igdb_id)
            if new_ids:
                logger.info("Waiting 30 seconds for game imports to complete...")
                await asyncio.sleep(30)
            await service.update_trending_games_list()
        logger.info("Import of trending games completed successfully!")
    except Exception as e:
        logger.error("Failed to import trending games: %s", e)
        raise


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def import_trending_music() -> None:
    """Import trending music from Spotify Charts and update trending list."""
    logger.info("Starting import of trending music at %s", datetime.now(UTC))
    try:
        async with sessionmanager.session() as db:
            service = TrendingService(db)
            new_ids = await service.get_new_trending_music_ids()
            for spotify_id in new_ids:
                await import_album.kiq(spotify_id)
            if new_ids:
                logger.info("Waiting 30 seconds for music imports to complete...")
                await asyncio.sleep(30)
            await service.update_trending_music_list()
        logger.info("Import of trending music completed successfully!")
    except Exception as e:
        logger.error("Failed to import trending music: %s", e)
        raise


@broker.task(retry_on_error=True, delay=30)
async def import_show(tmdb_id: int) -> None:
    """Import a TV show by its TMDB ID."""
    try:
        async with sessionmanager.session() as db:
            tmdb_api_key = await get_tmdb_api_key(db)
            if not tmdb_api_key:
                logger.error("TMDB API key not configured")
                return

            tmdb = TMDB(api_key=tmdb_api_key)
            try:
                from streamarr.services.metadata_refresh import MetadataService
                service = MetadataService(db)
                media_item = await service.import_media(
                    plugin=tmdb,
                    external_id=str(tmdb_id),
                    provider_name="tmdb",
                    media_type=MediaType.SHOWS,
                )
                if media_item:
                    await _notify_import(media_item, "SHOWS", tmdb_id=tmdb_id)
                    await _queue_overlay_render(media_item)
            finally:
                await tmdb.close()

    except Exception as e:
        logger.error("Failed to import show %s: %s", tmdb_id, e)
        raise


@broker.task(retry_on_error=True, delay=30)
async def import_game(igdb_id: int) -> None:
    """Import a game by its IGDB ID."""
    try:
        async with sessionmanager.session() as db:
            settings_service = SettingsService(db)
            client_id, client_secret = await settings_service.get_igdb_credentials()
            if not client_id or not client_secret:
                logger.error("IGDB credentials not configured")
                return

            from streamarr.metadata.igdb import IGDB
            igdb = IGDB(client_id=client_id, client_secret=client_secret)
            try:
                from streamarr.services.metadata_refresh import MetadataService
                service = MetadataService(db)
                media_item = await service.import_media(
                    plugin=igdb,
                    external_id=str(igdb_id),
                    provider_name="igdb",
                    media_type=MediaType.GAMES,
                )
                if media_item:
                    await _notify_import(media_item, "GAMES", igdb_id=igdb_id)
            finally:
                await igdb.close()

    except Exception as e:
        logger.error("Failed to import game %s: %s", igdb_id, e)
        raise


@broker.task(retry_on_error=True, delay=30)
async def import_book(openlibrary_id: str) -> None:
    """Import a book by its Open Library work ID with Author hierarchy."""
    try:
        async with sessionmanager.session() as db:
            from streamarr.services.book_import import BookImportService

            service = BookImportService(db)
            result = await service.import_book(openlibrary_id)

            if result:
                logger.info(
                    "Imported book: %s by %s",
                    result["title"], result.get("author", "Unknown"),
                )

    except Exception as e:
        logger.error("Failed to import book %s: %s", openlibrary_id, e)
        raise


@broker.task(retry_on_error=True, delay=30)
async def import_artist(spotify_id: str) -> None:
    """Import a music artist and their albums by Spotify ID.

    Creates the artist entity, then queues import_album for each of
    the artist's albums (which will create the full hierarchy).
    """
    try:
        async with sessionmanager.session() as db:
            from streamarr.services.spotify_import import SpotifyMusicImportService

            service = SpotifyMusicImportService(db)
            result = await service.import_artist(spotify_id)

            if result:
                queued = 0
                for album_id in result["album_ids"]:
                    await import_album.kiq(album_id)
                    queued += 1
                logger.info(
                    "Queued %s album imports for artist %s", queued, result["artist_title"],
                )

    except Exception as e:
        logger.error("Failed to import artist %s: %s", spotify_id, e)
        raise


@broker.task(retry_on_error=True, delay=30)
async def import_album(spotify_id: str) -> None:
    """Import a music album by its Spotify ID using unified media architecture.

    Creates the full hierarchy: Artist -> Album -> Songs, with Spotify external IDs
    for each entity. Artists and albums are deduplicated by external ID.
    """
    try:
        async with sessionmanager.session() as db:
            from streamarr.services.spotify_import import SpotifyMusicImportService

            service = SpotifyMusicImportService(db)
            await service.import_album(spotify_id)

    except Exception as e:
        logger.error("Failed to import album %s: %s", spotify_id, e)
        raise


@broker.task
async def send_notification_email(notification_id: str) -> None:
    """Send notification email asynchronously."""
    try:
        async with sessionmanager.session() as db:
            notification_service = NotificationService(db)
            notification = await notification_service.get_by_id(notification_id)

            if not notification:
                logger.error("Notification %s not found", notification_id)
                return

            if not notification.send_email:
                logger.info("Notification %s has send_email=False, skipping", notification_id)
                return

            # Get user
            user = await db.get(User, notification.user_id)
            if not user:
                logger.error("User %s not found", notification.user_id)
                await notification_service.mark_as_sent(
                    notification_id, success=False, error_message="User not found"
                )
                return

            # Resolve i18n for notification email
            from streamarr.services.auth import _get_email_i18n, _get_app_url
            from streamarr.services.settings import SettingsService

            i18n = _get_email_i18n("notification", user)
            lang = (user.ui_language or "en-US")[:2].lower()
            try:
                app_name = await SettingsService(db).get("system.site_name", "Streamarr")
            except Exception:
                app_name = "Streamarr"

            # Replace {app_name} placeholder in i18n strings
            i18n = {k: v.replace("{app_name}", app_name) for k, v in i18n.items()}

            # Send email
            success = await email_service.send_notification_email(
                to_email=user.email,
                subject=notification.subject,
                message=notification.message,
                notification_type=notification.notification_type.value,
                i18n=i18n,
                lang=lang,
                app_name=app_name,
            )

            # Update notification status
            if success:
                await notification_service.mark_as_sent(notification_id, success=True)
                logger.info(
                    "Notification email sent successfully to %s: %s",
                    user.email, notification.subject,
                )
            else:
                await notification_service.mark_as_sent(
                    notification_id,
                    success=False,
                    error_message="Failed to send email",
                )
                logger.error(
                    "Failed to send notification email to %s: %s",
                    user.email, notification.subject,
                )

    except Exception as e:
        logger.error("Error sending notification email %s: %s", notification_id, e)
        async with sessionmanager.session() as db:
            notification_service = NotificationService(db)
            await notification_service.mark_as_sent(
                notification_id, success=False, error_message=str(e)
            )


@broker.task
async def probe_media_file(media_file_guid: str) -> dict:
    """
    Worker task to probe a unified MediaFile and update its probe_data.

    This is the new unified probe task that works with the MediaFile model
    from the unified media system.
    """
    try:
        from streamarr.models.media import MediaFile
        from streamarr.services.media_file import MediaFileService
        from streamarr.services.play import probe_video_full

        async with sessionmanager.session() as db:
            file = await db.get(MediaFile, media_file_guid)

            if not file:
                logger.error("Media file %s not found", media_file_guid)
                return {"success": False, "error": "File not found"}

            logger.info("Probing media file: %s", file.file_path)
            probe_data = await probe_video_full(file.file_path, db)

            if not probe_data:
                logger.error("Failed to probe media file: %s", file.file_path)
                return {"success": False, "error": "Probe failed"}

            media_file_service = MediaFileService(db)
            file = await media_file_service.update_from_probe_data(
                media_file_guid, probe_data
            )

            # Resolution/codec just changed — re-render the overlay so
            # resolution-based templates (4K/1080p/HEVC badges) pick it up.
            if file and file.media_item_guid:
                try:
                    await render_overlay_for_item.kiq(
                        str(file.media_item_guid), "POSTER"
                    )
                except Exception as exc:
                    logger.debug(
                        "queue overlay render skipped post-probe for %s: %s",
                        file.media_item_guid,
                        exc,
                    )

            result = {
                "success": True,
                "file_guid": media_file_guid,
                "video_streams": len(probe_data.get("video_streams", [])),
                "audio_streams": len(probe_data.get("audio_streams", [])),
                "subtitle_streams": len(probe_data.get("subtitle_streams", [])),
                "width": file.width,
                "height": file.height,
                "codec": file.codec,
                "quality": file.quality,
                "duration": file.duration,
                "file_size": file.file_size,
            }
            logger.info("Successfully probed media file %s: %s", media_file_guid, result)
            return result

    except Exception as e:
        logger.error("Error probing media file %s: %s", media_file_guid, e)
        return {"success": False, "error": str(e)}


@broker.task()
async def search_media_item_releases(
    media_item_guid: str, user_guid: str | None = None, force: bool = False
) -> None:
    """Search for releases for a specific media item and store them (without downloading).

    This is used to automatically find releases when a user views a media item,
    particularly for episodes and movies that don't have files yet.

    Uses Sonarr/Radarr-style matching to filter releases that actually match
    the media item's title.

    Args:
        media_item_guid: GUID of the media item to search releases for
        user_guid: Optional GUID of the user who triggered the search
    """
    from streamarr.services.release_search import ReleaseSearchService

    try:
        async with sessionmanager.session() as db:
            service = ReleaseSearchService(db)
            await service.search_and_store_releases(
                media_item_guid, user_guid, force=force
            )
    except Exception as e:
        logger.error("Failed to search releases for media item %s: %s", media_item_guid, e)
        raise


@broker.task()
async def auto_download_media_item(
    media_item_guid: str,
    user_preferences: dict[str, Any] | None = None,
    user_guid: str | None = None,
    backfill: bool = False,
    upgrade: bool = False,
    replace_media_file_guid: str | None = None,
    platform: str | None = None,
) -> None:
    """
    Automatically download the best available release for a media item.

    This task:
    1. Gets all available releases for the media item
    2. Scores them using the library plugin's quality scoring
    3. Selects the best one
    4. Starts the download

    Args:
        media_item_guid: GUID of the media item
        user_preferences: Optional user quality preferences
        user_guid: Optional GUID of the requesting user (used for language scoring)
    """
    from streamarr.services.auto_download import AutoDownloadService

    try:
        async with sessionmanager.session() as db:
            service = AutoDownloadService(db)
            await service.auto_download(
                media_item_guid,
                user_preferences,
                user_guid,
                upgrade=upgrade,
                replace_media_file_guid=replace_media_file_guid,
                backfill=backfill,
                platform=platform,
            )
    except Exception as e:
        logger.error("Failed to auto-download media item %s: %s", media_item_guid, e)
        raise


@broker.task
async def refresh_media_item_metadata(media_item_guid_str: str) -> None:
    """
    Refresh metadata for a media item from external providers.

    Delegates all logic to MetadataRefreshService — the worker only
    resolves the correct provider plugin and external ID.
    """
    metadata_plugin = None
    try:
        media_item_guid = uuid.UUID(media_item_guid_str)
        logger.info("Refreshing metadata for media item %s", media_item_guid)

        async with sessionmanager.session() as db:
            from streamarr.services.metadata_refresh import MetadataService

            # Load media item to determine provider
            result = await db.execute(
                select(MediaItem)
                .options(selectinload(MediaItem.external_ids))
                .where(MediaItem.guid == media_item_guid)
            )
            media_item = result.scalars().first()
            if not media_item:
                logger.warning("Media item %s not found", media_item_guid)
                return

            # Resolve provider plugin and external ID
            external_id = None

            if media_item.media_type in [MediaType.MOVIES, MediaType.SHOWS]:
                tmdb_api_key = await get_tmdb_api_key(db)
                if tmdb_api_key:
                    metadata_plugin = TMDB(api_key=tmdb_api_key)
                    external_id = _get_external_id(media_item, "tmdb")

            elif media_item.media_type == MediaType.GAMES:
                games_plugin = get_plugin_instance("GAMES")
                if games_plugin and hasattr(games_plugin, "metadata_plugin"):
                    metadata_plugin = games_plugin.metadata_plugin
                    external_id = _get_external_id(media_item, "igdb")

            elif media_item.media_type == MediaType.BOOKS:
                from streamarr.metadata.openlibrary import OpenLibrary
                metadata_plugin = OpenLibrary()
                external_id = _get_external_id(media_item, "openlibrary")

            if not metadata_plugin:
                logger.warning(
                    "No metadata plugin for media item %s",
                    media_item_guid,
                )
                return

            # Delegate to service
            service = MetadataService(db)
            if media_item.media_type == MediaType.SHOWS and media_item.parent_guid:
                parent_result = await db.execute(
                    select(MediaItem)
                    .options(selectinload(MediaItem.external_ids))
                    .where(MediaItem.guid == media_item.parent_guid)
                )
                parent = parent_result.scalars().first()
                if not parent:
                    logger.warning(
                        "Parent media item %s for %s not found",
                        media_item.parent_guid,
                        media_item_guid,
                    )
                    return

                season_item = media_item
                show_item = parent
                if parent.parent_guid:
                    show_result = await db.execute(
                        select(MediaItem)
                        .options(selectinload(MediaItem.external_ids))
                        .where(MediaItem.guid == parent.parent_guid)
                    )
                    show_item = show_result.scalars().first()
                    season_item = parent
                    if not show_item:
                        logger.warning(
                            "Show parent %s for %s not found",
                            parent.parent_guid,
                            media_item_guid,
                        )
                        return

                show_external_id = _get_external_id(show_item, "tmdb")
                if not show_external_id or season_item.sequence_number is None:
                    logger.warning(
                        "No parent show TMDB ID or season number for media item %s",
                        media_item_guid,
                    )
                    return

                await service.refresh_season(
                    season_item.guid,
                    metadata_plugin,
                    show_external_id,
                    season_item.sequence_number,
                )
                return

            if not external_id:
                logger.warning(
                    "No external ID for media item %s",
                    media_item_guid,
                )
                return

            await service.refresh(media_item_guid, metadata_plugin, external_id)

    except Exception as e:
        logger.error(
            "Failed to refresh metadata for media item %s: %s",
            media_item_guid_str, e, exc_info=True,
        )
        raise
    finally:
        if metadata_plugin and hasattr(metadata_plugin, "close"):
            await metadata_plugin.close()


# ==================== Auto Metadata Refresh ====================


@broker.task(schedule=[{"cron": "0 3 * * *"}])  # Daily at 3 AM
async def auto_refresh_metadata() -> None:
    """Automatically refresh metadata for items not updated in the last 30 days.

    Processes up to 100 items per run to stay within API rate limits.
    """
    from datetime import UTC, timedelta

    logger.info("Starting automatic metadata refresh")
    cutoff = datetime.now(UTC) - timedelta(days=30)

    try:
        async with sessionmanager.session() as db:
            # Find items with stale metadata (oldest first)
            result = await db.execute(
                select(MediaItem)
                .where(MediaItem.media_type.in_([
                    MediaType.MOVIES, MediaType.SHOWS, MediaType.GAMES, MediaType.BOOKS,
                ]))
                .where(
                    (MediaItem.updated_at < cutoff) | (MediaItem.updated_at.is_(None))
                )
                .order_by(MediaItem.updated_at.asc().nullsfirst())
                .limit(100)
            )
            stale_items = result.scalars().all()

            if not stale_items:
                logger.info("No stale metadata items found")
                return

            logger.info("Found %d items with stale metadata, queuing refresh", len(stale_items))

            for item in stale_items:
                await refresh_media_item_metadata.kiq(str(item.guid))

            logger.info("Queued %d metadata refresh tasks", len(stale_items))

    except Exception as e:
        logger.error("Auto metadata refresh failed: %s", e)
        raise


# ==================== Cleanup Tasks ====================


@broker.task(schedule=[{"cron": "*/15 * * * *"}])  # Every 15 minutes
async def cleanup_orphaned_temp_files() -> dict:
    """
    Clean up orphaned temp files from old transcoding sessions.

    This task runs periodically to clean up temp files (.ts, .m3u8)
    that were not properly cleaned up when streams ended.

    Files older than 2 hours are considered orphaned.
    """
    from streamarr.services.media import MediaService

    logger.info("Starting cleanup of orphaned temp files")

    try:
        async with sessionmanager.session() as db:
            cleanup_service = MediaService(db)
            result = await cleanup_service.cleanup_orphaned_temp_files(max_age_hours=2)

            logger.info(
                "Orphaned temp cleanup complete: scanned %s, deleted %s",
                result['files_scanned'], result['files_deleted'],
            )

            return result

    except Exception as e:
        logger.error("Orphaned temp cleanup failed: %s", e, exc_info=True)
        raise


@broker.task(schedule=[{"cron": "30 4 * * *"}])  # Daily at 04:30
async def cleanup_trickplay_cache() -> dict:
    """
    Drop cached trickplay sprites that no longer belong to a media file.

    Deleting a file drops its sprites immediately, so this only collects what
    no hook can see: files moved or renamed outside the app, or removed while
    the backend was down.
    """
    from sqlalchemy import select

    from streamarr.models.media import MediaFile
    from streamarr.services import trickplay
    from streamarr.services.system_settings import SystemSettingsService

    logger.info("Starting trickplay cache cleanup")

    try:
        async with sessionmanager.session() as db:
            rows = await db.execute(select(MediaFile.file_path))
            known_paths = [path for (path,) in rows.all() if path]

            settings = await SystemSettingsService(db).get_transcoding_settings()
            budget = trickplay.bytes_for_gb(settings.get("trickplay_cache_max_gb"))

        result = await asyncio.to_thread(trickplay.purge_orphans, known_paths)

        # Orphans first: they are worthless, so evicting a usable entry before
        # dropping them would be wasted work.
        evicted = await asyncio.to_thread(trickplay.enforce_size_limit, budget)
        result["evicted"] = evicted["deleted"]
        result["bytes_freed"] += evicted["bytes_freed"]

        logger.info(
            "Trickplay cache cleanup complete: scanned %s, orphans %s, evicted %s, freed %.1f MB",
            result["scanned"],
            result["deleted"],
            result["evicted"],
            result["bytes_freed"] / 1_048_576,
        )
        return result

    except Exception as e:
        logger.error("Trickplay cache cleanup failed: %s", e, exc_info=True)
        raise


@broker.task(schedule=[{"cron": "*/5 * * * *"}])  # Every 5 minutes
async def cleanup_orphaned_transcode_containers() -> dict:
    """
    Stop and remove transcode containers that have no matching active Redis session.

    Containers can become orphaned when:
    - The Redis session expires (2h TTL) but the container keeps running
    - The frontend doesn't call stop_stream (e.g. tab closed, navigation)
    - A new transcode starts but the old one isn't stopped
    """
    from streamarr.services.transcoding_session import get_transcoding_session_service

    logger.info("Checking for orphaned transcode containers")

    try:
        session_service = get_transcoding_session_service()
        active_sessions = await session_service.get_all_sessions(active_only=True)
        active_session_ids = {s.session_id for s in active_sessions}

        stopped = 0
        errors = 0

        async with sessionmanager.session() as db:
            from streamarr.services.computing import ComputingService

            async with ComputingService(db) as computing_service:
                all_tasks = await computing_service.list_tasks()

                for task in all_tasks:
                    if task.get("status") not in ("running", "pending"):
                        continue

                    labels = task.get("labels", {})
                    session_id = (
                        labels.get("transcode.session_id")
                        or labels.get("trickplay.session_id")
                    )
                    if not session_id or session_id not in active_session_ids:
                        task_id = task["task_id"]
                        logger.warning(
                            "Stopping orphaned container %s (session_id=%s)",
                            task_id, session_id,
                        )
                        try:
                            await computing_service.stop_task(task_id, force=True)
                            await computing_service.delete_task(task_id)
                            if session_id:
                                from streamarr.services.storage_cleanup import cleanup_session_temp_files
                                temp_result = cleanup_session_temp_files(session_id)
                                if temp_result["deleted"]:
                                    logger.info(
                                        "Cleaned up %d temp files for orphaned session %s",
                                        temp_result["deleted"], session_id,
                                    )
                            stopped += 1
                        except Exception as e:
                            logger.error("Failed to stop orphaned container %s: %s", task_id, e)
                            errors += 1

        result = {"stopped": stopped, "errors": errors}
        if stopped or errors:
            logger.info("Orphaned container cleanup: %s", result)
        return result

    except Exception as e:
        logger.error("Orphaned container cleanup failed: %s", e, exc_info=True)
        raise


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def cleanup_stale_transcoding_sessions() -> dict:
    """
    Clean up stale transcoding sessions from Redis.

    This task runs periodically to remove sessions whose containers
    are no longer running and haven't been accessed recently.
    """
    from streamarr.services.transcoding_session import get_transcoding_session_service

    logger.info("Starting cleanup of stale transcoding sessions")

    try:
        session_service = get_transcoding_session_service()
        cleaned_count = await session_service.cleanup_stale_sessions()

        logger.info("Cleaned up %s stale transcoding sessions", cleaned_count)

        return {
            "cleaned_sessions": cleaned_count,
        }

    except Exception as e:
        logger.error("Session cleanup failed: %s", e, exc_info=True)
        raise


MAX_TRANSCODE_RETRIES = 2


@broker.task(schedule=[{"cron": "* * * * *"}])  # Every minute
async def monitor_active_transcodes() -> dict:
    """
    Monitor active transcoding sessions and recover from FFmpeg crashes.

    For each active session:
    - Check if the container is still running
    - If crashed: attempt restart (up to MAX_TRANSCODE_RETRIES)
    - If retries exhausted: mark session as failed and notify user via WebSocket
    """
    return await TranscodeMonitorWorker(MAX_TRANSCODE_RETRIES).monitor_active_transcodes()


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def cleanup_storage() -> dict:
    """
    Run full storage cleanup to free disk space.

    This task runs periodically and:
    - Deletes old transcoding temp files (.ts, .m3u8)
    - Removes old completed/failed download records from DB
    - Cleans up orphaned media file records (file missing on disk)
    - Removes duplicate media files per media item

    Settings are loaded from the database (storage.* keys).
    """
    return await StorageCleanupWorker().cleanup_storage()


# ---------------------------------------------------------------------------
# Intro/Outro/Credits Detection
# ---------------------------------------------------------------------------


@broker.task
async def detect_intro_outro_season(season_guid: str) -> dict:
    """Detect intros and outros for all episodes in a season using chromaprint."""
    logger.info("Starting intro/outro detection for season %s", season_guid)
    try:
        async with sessionmanager.session() as db:
            from streamarr.services.chromaprint import ChromaprintService

            service = ChromaprintService(db)
            result = await service.detect_intros_for_season(uuid.UUID(season_guid))
            logger.info("Intro/outro detection complete for season %s: %s", season_guid, result)
            return result
    except Exception as e:
        logger.error("Intro/outro detection failed for season %s: %s", season_guid, e, exc_info=True)
        raise


@broker.task
async def detect_credits_movie(media_item_guid: str) -> dict:
    """Detect credits in a movie using silence/black frame detection."""
    logger.info("Starting credits detection for %s", media_item_guid)
    try:
        async with sessionmanager.session() as db:
            from streamarr.services.chromaprint import ChromaprintService

            service = ChromaprintService(db)
            result = await service.detect_credits_for_movie(uuid.UUID(media_item_guid))
            logger.info("Credits detection complete for %s: %s", media_item_guid, result)
            return result or {"detected": False}
    except Exception as e:
        logger.error("Credits detection failed for %s: %s", media_item_guid, e, exc_info=True)
        raise


# ------------------------------------------------------------------
# Recommendation system tasks
# ------------------------------------------------------------------


REC_MEDIA_TYPES = ("MOVIES", "SHOWS")


async def _active_user_guids(db) -> list[str]:
    res = await db.execute(select(User.guid).where(User.is_active.is_(True)))
    return [str(u[0]) for u in res.all()]


@broker.task(schedule=[{"cron": "0 4 * * *"}])  # Daily 04:00
async def rebuild_user_profiles() -> None:
    """Refresh UserProfileVector for every active user × {MOVIES, SHOWS}."""
    from streamarr.services.recommendation import RecommendationService

    run_id = await record_worker_task_event(
        task_id="rebuild_user_profiles",
        category="recommendations",
        status="queued",
        message="Queued scheduled user profile rebuild",
    )
    logger.info("Rebuilding user profile vectors at %s", datetime.now(UTC))
    try:
        async with sessionmanager.session() as db:
            user_guids = await _active_user_guids(db)

        sem = asyncio.Semaphore(10)

        async def _build_one(guid: str, mt: str) -> None:
            async with sem:
                try:
                    async with sessionmanager.session() as db:
                        svc = RecommendationService(db)
                        await svc.build_user_profile(guid, mt)
                        await svc.close()
                except Exception as e:
                    logger.warning("profile build failed for %s/%s: %s", guid, mt, e)

        tasks = [_build_one(g, mt) for g in user_guids for mt in REC_MEDIA_TYPES]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Rebuilding user profile vectors done.")
        await record_worker_task_event(
            task_id="rebuild_user_profiles",
            category="recommendations",
            status="completed",
            run_id=run_id,
            message="Completed scheduled user profile rebuild",
        )
    except Exception as e:
        await record_worker_task_event(
            task_id="rebuild_user_profiles",
            category="recommendations",
            status="failed",
            run_id=run_id,
            message="Failed scheduled user profile rebuild",
            error=str(e),
        )
        raise


@broker.task(schedule=[{"cron": "30 4 * * *"}])  # Daily 04:30
async def refresh_recommendation_lists() -> None:
    """Rebuild every recommendation list (for_you, top_picks, because, friends)."""
    from streamarr.services.recommendation import RecommendationService

    run_id = await record_worker_task_event(
        task_id="refresh_recommendation_lists",
        category="recommendations",
        status="queued",
        message="Queued scheduled recommendation list refresh",
    )
    logger.info("Refreshing recommendation lists at %s", datetime.now(UTC))
    try:
        sem = asyncio.Semaphore(5)

        async with sessionmanager.session() as db:
            user_guids = await _active_user_guids(db)

        async def _rebuild_one(guid: str, mt: str):
            async with sem:
                try:
                    async with sessionmanager.session() as db:
                        svc = RecommendationService(db)
                        await svc.rebuild_for_you_list(uuid.UUID(guid), mt)
                        await svc.rebuild_top_picks_list(uuid.UUID(guid), mt)
                        await svc.rebuild_because_you_watched_lists(uuid.UUID(guid), mt)
                        await svc.rebuild_friends_watching_list(uuid.UUID(guid), mt)
                        await svc.close()
                except Exception as e:
                    logger.warning("rec rebuild failed for %s/%s: %s", guid, mt, e)

        tasks = [_rebuild_one(g, mt) for g in user_guids for mt in REC_MEDIA_TYPES]
        await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Recommendation lists refreshed.")
        await record_worker_task_event(
            task_id="refresh_recommendation_lists",
            category="recommendations",
            status="completed",
            run_id=run_id,
            message="Completed scheduled recommendation list refresh",
        )
    except Exception as e:
        await record_worker_task_event(
            task_id="refresh_recommendation_lists",
            category="recommendations",
            status="failed",
            run_id=run_id,
            message="Failed scheduled recommendation list refresh",
            error=str(e),
        )
        raise


@broker.task
async def rebuild_user_recommendations(user_guid: str) -> None:
    """On-demand rebuild triggered from viewing_history / favorite / friendship events.

    Redis-debounced so rapid-fire events collapse to one rebuild per user per 5 min.
    """
    import redis.asyncio as redis_async

    from streamarr.services.recommendation import RecommendationService

    run_id = await record_worker_task_event(
        task_id="rebuild_user_recommendations",
        category="recommendations",
        status="queued",
        message=f"Queued recommendation rebuild for user {user_guid}",
    )
    try:
        rds = redis_async.from_url(
            settings.redis_url, encoding="utf-8", decode_responses=True
        )
        try:
            debounce_key = f"recs:debounce:{user_guid}"
            if not await rds.set(debounce_key, "1", ex=300, nx=True):
                logger.debug("Skipping rebuild for %s (debounced)", user_guid)
                return
        finally:
            await rds.close()
    except Exception as e:
        logger.warning("Redis debounce lookup failed (%s) — proceeding", e)

    logger.info("On-demand rec rebuild for user %s", user_guid)
    failed = False
    for mt in REC_MEDIA_TYPES:
        try:
            async with sessionmanager.session() as db:
                svc = RecommendationService(db)
                await svc.build_user_profile(user_guid, mt)
                await svc.rebuild_for_you_list(uuid.UUID(user_guid), mt)
                await svc.rebuild_top_picks_list(uuid.UUID(user_guid), mt)
                await svc.rebuild_because_you_watched_lists(uuid.UUID(user_guid), mt)
                await svc.rebuild_friends_watching_list(uuid.UUID(user_guid), mt)
                await svc.close()
        except Exception as e:
            failed = True
            logger.warning(
                "On-demand rebuild failed for %s/%s: %s", user_guid, mt, e
            )
    await record_worker_task_event(
        task_id="rebuild_user_recommendations",
        category="recommendations",
        status="failed" if failed else "completed",
        run_id=run_id,
        message=(
            f"Failed recommendation rebuild for user {user_guid}"
            if failed
            else f"Completed recommendation rebuild for user {user_guid}"
        ),
    )


@broker.task(schedule=[{"cron": "0 */12 * * *"}])  # Every 12h
async def warm_external_similarity_cache() -> None:
    """Pre-warm the TMDB similar/recommendations Redis cache for the top
    ~500 most-viewed owned movies + shows."""
    async def _run() -> None:
        from streamarr.services.recommendation import RecommendationService

        from streamarr.models.viewing_history import ViewingHistory

        async with sessionmanager.session() as db:
            top = await db.execute(
                select(MediaItem, func.count().label("views"))
                .join(ViewingHistory, ViewingHistory.media_item_guid == MediaItem.guid)
                .where(MediaItem.media_type.in_(("MOVIES", "SHOWS")))
                .group_by(MediaItem.guid)
                .order_by(func.count().desc())
                .options(selectinload(MediaItem.external_ids))
                .limit(500)
            )
            items = [row[0] for row in top.all()]
            svc = RecommendationService(db)
            for item in items:
                tmdb_id = await svc._tmdb_id_of(item)
                if not tmdb_id:
                    continue
                mt = item.media_type.value
                segment = {"MOVIES": "movie", "SHOWS": "tv"}.get(mt)
                if not segment:
                    continue
                try:
                    await svc.tmdb_similar_cached(tmdb_id, segment)
                except Exception as e:
                    logger.debug("warm cache failed for %s: %s", tmdb_id, e)
            await svc.close()

    await _run()


# ------------------------------------------------------------------
# Smart-collection scheduler & runner
# ------------------------------------------------------------------


@broker.task(schedule=[{"cron": "* * * * *"}])  # Every minute
async def tick_smart_collections() -> dict:
    """Dispatch due smart-collection rules.

    Implementation lives in workers/smart_collection_worker.py so the
    test suite can drive it without booting taskiq's broker layer.
    """
    enqueued = await tick_smart_collections_impl()
    return {"enqueued": enqueued}


@broker.task(retry_on_error=True, delay=15)
async def run_smart_collection_rule(rule_guid: str) -> dict:
    """Execute a single smart-collection rule end-to-end."""
    return await run_smart_collection_rule_impl(rule_guid)


# ------------------------------------------------------------------
# Favorites monitoring + backwards-search orchestrator
# ------------------------------------------------------------------


@broker.task(retry_on_error=True, delay=30)
async def backfill_favorite_monitored(
    root_guid: str, user_guid: str | None = None
) -> dict:
    """Monitor a favorited root's whole subtree and backwards-search it."""
    return await backfill_favorite_monitored_impl(root_guid, user_guid)


@broker.task(retry_on_error=True, delay=15)
async def unmonitor_favorite(root_guid: str) -> dict:
    """Release the monitoring lock for an unfavorited subtree."""
    return await unmonitor_favorite_impl(root_guid)


@broker.task(schedule=[{"cron": "0 */6 * * *"}])  # Every 6 hours
async def tick_favorites_reconcile() -> dict:
    """Pick up new children of favorited roots + re-acquire lost files."""
    enqueued = await tick_favorites_reconcile_impl()
    return {"enqueued": enqueued}


@broker.task(schedule=[{"cron": "*/5 * * * *"}])  # Every 5 minutes
async def rss_sync() -> dict:
    """Poll RSS-enabled indexers and accelerate monitored acquisition."""
    return await rss_sync_impl()


@broker.task(schedule=[{"cron": "*/15 * * * *"}])  # Every 15 minutes
async def tick_upgrade_scan() -> dict:
    """Scan monitored leaves and enqueue profile-gated upgrades."""
    return await tick_upgrade_scan_impl()


@broker.task(retry_on_error=True, delay=30)
async def run_upgrade_search(media_item_guid: str) -> dict:
    """Force-search one monitored item and attempt an upgrade grab."""
    from streamarr.services.upgrade_scan import run_upgrade_search_impl

    return await run_upgrade_search_impl(media_item_guid)


# ------------------------------------------------------------------
# Overlay rendering
# ------------------------------------------------------------------


@broker.task(retry_on_error=True, delay=15)
async def render_overlay_for_item(
    media_guid: str, target: str = "POSTER"
) -> dict:
    """Render & cache overlays for a single MediaItem (poster or backdrop)."""
    return await render_overlay_for_item_impl(media_guid, target)


@broker.task
async def bulk_rerender_overlays_for_template(template_guid: str) -> dict:
    """Re-render every item potentially matching ``template_guid``.

    Invoked from the admin API after a template edit, so the change
    propagates without waiting for the next natural trigger.
    """
    enqueued = await bulk_rerender_for_template_impl(template_guid)
    return {"enqueued": enqueued}


@broker.task(schedule=[{"cron": "*/30 * * * *"}])  # Every 30 minutes
async def tick_render_missing_overlays() -> dict:
    """Backstop scheduler: render overlays for items that lack one.

    Catches items that pre-date a new template, items whose initial
    import hook failed, and recovery after Redis flushes.
    """
    enqueued = await tick_render_missing_overlays_impl()
    return {"enqueued": enqueued}


# ------------------------------------------------------------------
# Mass metadata operations
# ------------------------------------------------------------------


@broker.task(schedule=[{"cron": "*/5 * * * *"}])  # Every 5 minutes
async def tick_mass_operations() -> dict:
    """Dispatch due mass-operation rules."""
    enqueued = await tick_mass_operations_impl()
    return {"enqueued": enqueued}


@broker.task(retry_on_error=True, delay=30)
async def run_mass_operation_rule(
    rule_guid: str, dry_run: bool = False
) -> dict:
    """Execute a single mass-operation rule."""
    return await run_mass_operation_rule_impl(rule_guid, dry_run)


# ------------------------------------------------------------------
# Disaster-recovery database backup (pg_dump)
# ------------------------------------------------------------------


@broker.task(schedule=[{"cron": "0 2 * * *"}])  # Daily 02:00
async def scheduled_database_backup() -> dict:
    """Nightly pg_dump custom-format archive for disaster recovery.

    No-ops gracefully when pg_dump is not on PATH (the default backend/worker
    images ship without it) — deployment/backup/backup.sh is the primary path.
    """
    from streamarr.workers.backup_worker import run_pg_dump_backup

    return await run_pg_dump_backup("scheduled")


# Create scheduler with Redis source after task registration.
scheduler = create_scheduler()
