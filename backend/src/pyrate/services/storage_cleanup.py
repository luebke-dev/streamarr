"""Storage cleanup service for managing disk space.

Monitors disk usage for download and transcoding directories,
automatically deletes old files when thresholds are exceeded.
"""

import glob
import logging
import re
import shutil
import time
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.downloads import Download
from pyrate.models.list import List, ListItem
from pyrate.models.media import MediaFile, MediaItem

logger = logging.getLogger(__name__)

# Matches the session_id format accepted by the stream API, used here to reject
# anything that could escape the temp directory via path-traversal characters.
# Capped length so a pathological session_id can't fuel an expensive glob.
_SESSION_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,128}$")


def cleanup_session_temp_files(
    session_id: str, temp_path: str = "/temp"
) -> dict:
    """Delete temp transcoding files for a given session ID.

    Removes /temp/{session_id}.m3u8 and /temp/{session_id}_*.ts files.

    Args:
        session_id: The transcoding session ID.
        temp_path: Root temp directory.

    Returns:
        dict with ``deleted`` and ``errors`` counts.
    """
    result = {"deleted": 0, "errors": 0}

    if not _SESSION_ID_RE.match(session_id):
        logger.warning("Rejecting cleanup for invalid session_id: %r", session_id)
        return result

    patterns = [
        f"{temp_path}/{session_id}.m3u8",
        f"{temp_path}/{session_id}_*.ts",
    ]

    for pattern in patterns:
        for filepath in glob.glob(pattern):
            try:
                Path(filepath).unlink(missing_ok=True)
                result["deleted"] += 1
                logger.debug("Deleted temp file: %s", filepath)
            except Exception as e:
                result["errors"] += 1
                logger.warning("Failed to delete temp file %s: %s", filepath, e)

    return result


class StorageCleanupService:
    """Service for monitoring and managing disk space across storage paths."""

    def __init__(self, db: AsyncSession | None = None):
        self.db = db

    @staticmethod
    def get_disk_usage(path: str) -> dict:
        """Get disk usage statistics for a path.

        Args:
            path: Filesystem path to check

        Returns:
            Dict with total, used, free bytes and usage percentage.
            Returns zeros if path does not exist.
        """
        path_obj = Path(path)
        if not path_obj.exists():
            return {
                "path": path,
                "total": 0,
                "used": 0,
                "free": 0,
                "usage_percent": 0.0,
            }

        usage = shutil.disk_usage(path)
        usage_percent = (usage.used / usage.total * 100) if usage.total > 0 else 0.0

        return {
            "path": path,
            "total": usage.total,
            "used": usage.used,
            "free": usage.free,
            "usage_percent": round(usage_percent, 2),
        }

    @staticmethod
    def get_directory_size(path: str) -> int:
        """Calculate the total size of all files in a directory (recursively).

        Args:
            path: Directory path

        Returns:
            Total size in bytes
        """
        total = 0
        path_obj = Path(path)
        if not path_obj.exists():
            return 0

        for f in path_obj.rglob("*"):
            if f.is_symlink():
                continue  # Never follow symlinks
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError as e:
                    logger.debug("Could not stat file %s: %s", f, e)
        return total

    async def get_storage_overview(
        self,
        temp_path: str = "/temp",
        downloads_path: str = "/downloads",
        library_paths: list[str] | None = None,
    ) -> dict:
        """Get a complete storage overview for all managed paths.

        Args:
            temp_path: Path for transcoding temp files
            downloads_path: Path for download files
            library_paths: List of library paths to check

        Returns:
            Dict with disk usage for each path
        """
        if library_paths is None:
            library_paths = [
                "/library/movies",
                "/library/shows",
                "/library/music",
                "/library/books",
                "/library/games",
            ]

        overview = {
            "temp": {
                **self.get_disk_usage(temp_path),
                "directory_size": self.get_directory_size(temp_path),
            },
            "downloads": {
                **self.get_disk_usage(downloads_path),
                "directory_size": self.get_directory_size(downloads_path),
            },
            "libraries": {},
        }

        for lib_path in library_paths:
            name = Path(lib_path).name
            overview["libraries"][name] = {
                **self.get_disk_usage(lib_path),
                "directory_size": self.get_directory_size(lib_path),
            }

        return overview

    async def cleanup_transcode_temp(
        self,
        temp_path: str = "/temp",
        max_age_hours: float = 2.0,
        max_size_gb: float | None = None,
    ) -> dict:
        """Clean up old transcoding temp files.

        Deletes .ts segments and .m3u8 playlists that are older than max_age_hours.
        If max_size_gb is set, also deletes oldest files when total size exceeds limit.

        Args:
            temp_path: Path to temp directory
            max_age_hours: Delete files older than this (hours)
            max_size_gb: Optional max total size in GB for temp dir

        Returns:
            Cleanup result dict
        """
        result = {
            "files_scanned": 0,
            "files_deleted": 0,
            "bytes_freed": 0,
            "errors": [],
        }

        temp_dir = Path(temp_path)
        if not temp_dir.exists():
            return result

        max_age_seconds = max_age_hours * 3600
        current_time = time.time()

        # Collect all temp files with their info
        temp_files = []
        for pattern in ["*.ts", "*.m3u8"]:
            for f in temp_dir.glob(pattern):
                if f.is_symlink():
                    continue  # Never follow symlinks
                try:
                    stat = f.stat()
                    temp_files.append(
                        {
                            "path": f,
                            "size": stat.st_size,
                            "mtime": stat.st_mtime,
                            "age": current_time - stat.st_mtime,
                        }
                    )
                except OSError as e:
                    result["errors"].append(f"Cannot stat {f}: {e}")

        result["files_scanned"] = len(temp_files)

        # Phase 1: Delete files older than max_age_hours
        for info in temp_files:
            if info["age"] > max_age_seconds:
                try:
                    info["path"].unlink(missing_ok=True)
                    result["files_deleted"] += 1
                    result["bytes_freed"] += info["size"]
                    info["deleted"] = True
                    logger.debug(
                        "Deleted old temp file: %s (age: %.1fh)",
                        info['path'], info['age'] / 3600,
                    )
                except Exception as e:
                    result["errors"].append(f"Failed to delete {info['path']}: {e}")
                    info["deleted"] = False
            else:
                info["deleted"] = False

        # Phase 2: If max_size_gb set, delete oldest remaining files until under limit
        if max_size_gb is not None:
            max_size_bytes = max_size_gb * 1024**3
            remaining = [f for f in temp_files if not f.get("deleted")]
            remaining.sort(key=lambda f: f["mtime"])  # oldest first

            current_size = sum(f["size"] for f in remaining)

            for info in remaining:
                if current_size <= max_size_bytes:
                    break
                try:
                    info["path"].unlink(missing_ok=True)
                    result["files_deleted"] += 1
                    result["bytes_freed"] += info["size"]
                    current_size -= info["size"]
                    logger.debug(
                        "Deleted temp file for size limit: %s (%.1f MB)",
                        info['path'], info['size'] / 1024 / 1024,
                    )
                except Exception as e:
                    result["errors"].append(f"Failed to delete {info['path']}: {e}")

        logger.info(
            "Transcode temp cleanup: scanned %s, deleted %s, freed %.1f MB",
            result['files_scanned'], result['files_deleted'], result['bytes_freed'] / 1024 / 1024,
        )

        return result

    async def cleanup_old_downloads(
        self,
        max_age_days: int = 30,
        statuses: list[str] | None = None,
    ) -> dict:
        """Clean up old download records from the database.

        Removes download records that have been imported or failed and are
        older than max_age_days.

        Retention-safe by construction: this only deletes ``Download``
        history rows, never ``MediaFile`` rows or files on disk, so it
        cannot threaten favorited/monitored retention. (Documented so a
        future change doesn't make it cascade to files.)

        Args:
            max_age_days: Delete download records older than this (days)
            statuses: Statuses to clean up (default: Imported, Failed)

        Returns:
            Cleanup result dict
        """
        if self.db is None:
            return {"error": "No database session available", "records_deleted": 0}

        if statuses is None:
            statuses = ["Imported", "Failed"]

        result = {
            "records_deleted": 0,
            "errors": [],
        }

        try:
            from datetime import UTC, datetime, timedelta

            cutoff = datetime.now(UTC) - timedelta(days=max_age_days)

            # Count before deleting
            count_result = await self.db.execute(
                select(Download)
                .where(Download.status.in_(statuses))
                .where(Download.created_at < cutoff)
            )
            old_downloads = count_result.scalars().all()
            result["records_deleted"] = len(old_downloads)

            if old_downloads:
                await self.db.execute(
                    delete(Download)
                    .where(Download.status.in_(statuses))
                    .where(Download.created_at < cutoff)
                )
                await self.db.commit()

            logger.info(
                "Download records cleanup: deleted %s records older than %s days (statuses: %s)",
                result['records_deleted'], max_age_days, ', '.join(statuses),
            )

        except Exception as e:
            result["errors"].append(f"Database error: {e}")
            logger.error("Failed to clean up download records: %s", e, exc_info=True)
            await self.db.rollback()

        return result

    async def cleanup_orphaned_media_files(self) -> dict:
        """Find and clean up MediaFile records whose files no longer exist on disk.

        Returns:
            Cleanup result dict
        """
        if self.db is None:
            return {"error": "No database session available", "records_cleaned": 0}

        result = {
            "files_checked": 0,
            "orphaned_records": 0,
            "errors": [],
        }

        try:
            files_result = await self.db.execute(select(MediaFile))
            media_files = files_result.scalars().all()
            result["files_checked"] = len(media_files)

            orphaned_item_guids: set = set()
            for media_file in media_files:
                if media_file.file_path and not Path(media_file.file_path).exists():
                    logger.info(
                        "Orphaned media file record: %s -> %s",
                        media_file.guid, media_file.file_path,
                    )
                    orphaned_item_guids.add(media_file.media_item_guid)
                    await self.db.delete(media_file)
                    result["orphaned_records"] += 1

            if result["orphaned_records"] > 0:
                await self.db.commit()

            # A monitored/favorited item that just lost its file must be
            # re-acquired (don't wait up to 6h for the reconcile sweep).
            if orphaned_item_guids:
                to_reacquire = await self._collect_protected_lineage(
                    orphaned_item_guids
                )
                if to_reacquire:
                    try:
                        from pyrate.worker import (
                            auto_download_media_item,
                            search_media_item_releases,
                        )

                        for g in to_reacquire:
                            await search_media_item_releases.kiq(
                                str(g), None, force=True
                            )
                            await auto_download_media_item.kiq(
                                str(g), None, None, backfill=True
                            )
                        result["reacquire_enqueued"] = len(to_reacquire)
                    except Exception as e:
                        logger.warning(
                            "Failed to enqueue re-acquisition: %s", e
                        )

            logger.info(
                "Orphaned media files check: %s checked, %s orphaned records removed",
                result['files_checked'], result['orphaned_records'],
            )

        except Exception as e:
            result["errors"].append(f"Database error: {e}")
            logger.error("Failed to check orphaned media files: %s", e, exc_info=True)
            await self.db.rollback()

        return result

    async def cleanup_library_duplicates(
        self,
        library_path: str,
        keep_newest: bool = True,
    ) -> dict:
        """Find and remove duplicate media files per media item in a library.

        When multiple files exist for the same media item, keeps only the
        newest (or oldest if keep_newest=False) file.

        Args:
            library_path: Library path to check for duplicates
            keep_newest: If True, keeps the newest file; if False, keeps the oldest

        Returns:
            Cleanup result dict
        """
        if self.db is None:
            return {"error": "No database session available", "duplicates_removed": 0}

        result = {
            "items_checked": 0,
            "duplicates_removed": 0,
            "bytes_freed": 0,
            "errors": [],
        }

        try:
            # Find media files in this library path
            files_result = await self.db.execute(
                select(MediaFile).where(MediaFile.file_path.like(f"{library_path}%"))
            )
            media_files = files_result.scalars().all()

            # Group by media_item_guid
            by_item: dict[str, list] = {}
            for mf in media_files:
                key = str(mf.media_item_guid)
                if key not in by_item:
                    by_item[key] = []
                by_item[key].append(mf)

            result["items_checked"] = len(by_item)

            # Never prune extra qualities of monitored/favorited items —
            # Subsystem 3's upgrade logic is the sole owner of removing
            # superseded qualities for those.
            protected_strs: set[str] = set()
            if media_files:
                protected = await self._collect_protected_lineage(
                    {mf.media_item_guid for mf in media_files}
                )
                protected_strs = {str(g) for g in protected}

            for _item_guid, files in by_item.items():
                if len(files) <= 1:
                    continue
                if _item_guid in protected_strs:
                    continue

                # Sort by file_size descending (keep largest = best quality)
                files.sort(
                    key=lambda f: f.file_size or 0,
                    reverse=keep_newest,
                )

                # Keep the first one, remove the rest
                keep = files[0]
                for dup in files[1:]:
                    try:
                        dup_path = Path(dup.file_path)
                        freed = dup.file_size or 0

                        if dup_path.exists():
                            dup_path.unlink()
                            result["bytes_freed"] += freed
                            logger.info(
                                "Deleted duplicate: %s (kept: %s)",
                                dup.file_path, keep.file_path,
                            )

                        await self.db.delete(dup)
                        result["duplicates_removed"] += 1
                    except Exception as e:
                        result["errors"].append(
                            f"Failed to remove duplicate {dup.file_path}: {e}"
                        )

            if result["duplicates_removed"] > 0:
                await self.db.commit()

            logger.info(
                "Library duplicates check (%s): %s items, %s duplicates removed, %.1f MB freed",
                library_path, result['items_checked'], result['duplicates_removed'], result['bytes_freed'] / 1024 / 1024,
            )

        except Exception as e:
            result["errors"].append(f"Database error: {e}")
            logger.error("Failed to check library duplicates: %s", e, exc_info=True)
            await self.db.rollback()

        return result

    async def cleanup_rclone_retention(
        self,
        retention_days: int = 7,
        mount_prefix: str = "/downloads/",
        orphan_min_age_hours: float = 24.0,
    ) -> dict:
        """Delete rclone-backed media files older than retention_days.

        Files whose media_item (or any ancestor up to the root show) is in
        someone's favorites are skipped when ``favorites.permanent`` is on.
        The deletion goes through the rclone mount, so it removes the file
        from the remote too. The media_file row is also dropped; if that was
        the only file for an item, its availability_status becomes a natural
        candidate for the next search.

        Also sweeps **orphan directories** under *mount_prefix* — top-level
        dirs that are not referenced by any media_file row. These accumulate
        when a download completes but the import never created a media_file
        (failed parser, transient bug, etc.). To avoid racing with a job
        currently being imported, we only delete dirs whose mtime is older
        than *orphan_min_age_hours*.
        """
        from datetime import UTC, datetime, timedelta

        from pyrate.services.settings import SettingsService

        if self.db is None:
            return {"error": "No database session", "files_deleted": 0}

        settings_service = SettingsService(self.db)
        protect_favorites = await settings_service.get("favorites.permanent", False)

        cutoff = datetime.now(UTC) - timedelta(days=retention_days)

        result = await self.db.execute(
            select(MediaFile)
            .where(MediaFile.file_path.like(f"{mount_prefix}%"))
            .where(MediaFile.created_at < cutoff)
        )
        candidates = list(result.scalars().all())

        # Build the set of media_item guids that must survive: monitored
        # lineage (always) + favorited lineage (when favorites.permanent).
        protected: set = set()
        if candidates:
            protected = await self._collect_protected_lineage(
                {mf.media_item_guid for mf in candidates},
                include_favorites=bool(protect_favorites),
            )

        files_deleted = 0
        rows_deleted = 0
        skipped = 0
        errors: list[str] = []
        bytes_freed = 0

        for mf in candidates:
            if mf.media_item_guid in protected:
                skipped += 1
                continue

            path = Path(mf.file_path)
            try:
                if path.exists():
                    size = mf.file_size or path.stat().st_size
                    path.unlink()  # rclone SFTP → deletes on remote
                    files_deleted += 1
                    bytes_freed += size
                await self.db.delete(mf)
                rows_deleted += 1
            except Exception as e:
                errors.append(f"{mf.file_path}: {e}")

        if rows_deleted:
            await self.db.commit()

        # Sweep orphan directories: things in /downloads/ that no media_file
        # references. These come from completed jobs whose import never
        # produced a media_file row (parser miss, code path bug, etc.).
        orphan_stats = await self._sweep_orphan_download_dirs(
            mount_prefix=mount_prefix,
            min_age_hours=orphan_min_age_hours,
        )
        files_deleted += orphan_stats["dirs_deleted"]
        bytes_freed += orphan_stats["bytes_freed"]
        errors.extend(orphan_stats["errors"])

        logger.info(
            "Rclone retention: deleted %d files (%s MB), removed %d rows, skipped %d favorited, "
            "orphan dirs purged %d (%s MB), errors=%d",
            files_deleted - orphan_stats["dirs_deleted"],
            (bytes_freed - orphan_stats["bytes_freed"]) // (1024 * 1024),
            rows_deleted, skipped,
            orphan_stats["dirs_deleted"],
            orphan_stats["bytes_freed"] // (1024 * 1024),
            len(errors),
        )
        return {
            "files_deleted": files_deleted,
            "rows_deleted": rows_deleted,
            "bytes_freed": bytes_freed,
            "skipped_favorited": skipped,
            "orphan_dirs_deleted": orphan_stats["dirs_deleted"],
            "orphan_bytes_freed": orphan_stats["bytes_freed"],
            "errors": errors,
        }

    async def _sweep_orphan_download_dirs(
        self, mount_prefix: str, min_age_hours: float
    ) -> dict:
        """Delete top-level dirs under *mount_prefix* not referenced by media_file.

        Skips dirs whose mtime is younger than *min_age_hours* so we don't
        race with an import that just finished. Also leaves any path that
        appears as a prefix of an existing media_file.file_path — the import
        registered something inside it, even if the dir name itself differs.
        """
        result: dict = {"dirs_deleted": 0, "bytes_freed": 0, "errors": []}
        root = Path(mount_prefix)
        if not root.exists() or not root.is_dir():
            return result

        try:
            top_level = [p for p in root.iterdir() if p.is_dir() and p.name != ".tmp"]
        except OSError as exc:
            result["errors"].append(f"iter {root}: {exc}")
            return result

        if not top_level:
            return result

        # Pull all media_file paths under this mount in one query, build a
        # set of "referenced top-level dir names" so we can decide locally
        # without N+1 lookups.
        rows = await self.db.execute(
            select(MediaFile.file_path).where(
                MediaFile.file_path.like(f"{mount_prefix}%")
            )
        )
        referenced_top_level: set[str] = set()
        prefix_len = len(mount_prefix)
        for (path,) in rows.all():
            tail = path[prefix_len:]
            top = tail.split("/", 1)[0] if tail else ""
            if top:
                referenced_top_level.add(top)

        cutoff_seconds = time.time() - (min_age_hours * 3600.0)

        for dir_path in top_level:
            if dir_path.name in referenced_top_level:
                continue
            try:
                if dir_path.stat().st_mtime > cutoff_seconds:
                    continue  # too fresh, may be mid-import
                size_bytes = sum(
                    f.stat().st_size for f in dir_path.rglob("*") if f.is_file()
                )
                shutil.rmtree(str(dir_path))
                result["dirs_deleted"] += 1
                result["bytes_freed"] += size_bytes
                logger.info(
                    "Purged orphan download dir %s (%.1f MB)",
                    dir_path, size_bytes / (1024 * 1024),
                )
            except OSError as exc:
                result["errors"].append(f"{dir_path}: {exc}")

        return result

    async def _collect_favorited_lineage(self, media_item_guids: set) -> set:
        """Return the subset of guids whose root ancestor is in any favorites list.

        Favorites are stored on the root media_item (show/movie/album). For a
        per-episode media_file we need to walk up the parent chain up to 3
        levels (episode -> season -> show) to tell whether anyone favorited it.
        """
        if not media_item_guids:
            return set()

        from sqlalchemy import literal_column

        # Recursive CTE: each input guid + up to 3 ancestors
        anchor = (
            select(
                MediaItem.guid.label("origin"),
                MediaItem.guid.label("node"),
                MediaItem.parent_guid,
                literal_column("0").label("depth"),
            )
            .where(MediaItem.guid.in_(media_item_guids))
            .cte(name="lineage", recursive=True)
        )
        recursive = (
            select(
                anchor.c.origin,
                MediaItem.guid,
                MediaItem.parent_guid,
                (anchor.c.depth + 1),
            )
            .join(anchor, MediaItem.guid == anchor.c.parent_guid)
            .where(anchor.c.depth < 3)
        )
        cte = anchor.union_all(recursive)

        fav_match = (
            select(cte.c.origin)
            .join(ListItem, ListItem.item_guid == cte.c.node)
            .join(List, List.guid == ListItem.list_guid)
            .where(List.list_type == "FAVORITES")
            .distinct()
        )
        result = await self.db.execute(fav_match)
        return {row[0] for row in result.all()}

    async def _collect_protected_lineage(
        self, media_item_guids: set, *, include_favorites: bool = True
    ) -> set:
        """Guids that must survive cleanup because their lineage (self + up
        to 3 ancestors) is either favorited (when ``include_favorites``) OR
        monitored. ``monitored`` is the durable retention flag and is always
        protected; the favorites part mirrors the legacy
        ``favorites.permanent`` behaviour and is gated by the caller.
        """
        if not media_item_guids:
            return set()

        from sqlalchemy import literal_column

        anchor = (
            select(
                MediaItem.guid.label("origin"),
                MediaItem.guid.label("node"),
                MediaItem.parent_guid,
                literal_column("0").label("depth"),
            )
            .where(MediaItem.guid.in_(media_item_guids))
            .cte(name="prot_lineage", recursive=True)
        )
        recursive = (
            select(
                anchor.c.origin,
                MediaItem.guid,
                MediaItem.parent_guid,
                (anchor.c.depth + 1),
            )
            .join(anchor, MediaItem.guid == anchor.c.parent_guid)
            .where(anchor.c.depth < 3)
        )
        cte = anchor.union_all(recursive)

        protected: set = set()

        # Monitored lineage — always protected.
        mon_match = (
            select(cte.c.origin)
            .join(MediaItem, MediaItem.guid == cte.c.node)
            .where(MediaItem.monitored.is_(True))
            .distinct()
        )
        protected.update(
            row[0] for row in (await self.db.execute(mon_match)).all()
        )

        # Favorited lineage — gated like the legacy behaviour.
        if include_favorites:
            fav_match = (
                select(cte.c.origin)
                .join(ListItem, ListItem.item_guid == cte.c.node)
                .join(List, List.guid == ListItem.list_guid)
                .where(List.list_type == "FAVORITES")
                .distinct()
            )
            protected.update(
                row[0] for row in (await self.db.execute(fav_match)).all()
            )

        return protected

    async def run_full_cleanup(
        self,
        temp_path: str = "/temp",
        temp_max_age_hours: float = 2.0,
        temp_max_size_gb: float | None = None,
        download_max_age_days: int = 30,
        library_paths: list[str] | None = None,
    ) -> dict:
        """Run a complete storage cleanup across all areas.

        Args:
            temp_path: Transcoding temp directory
            temp_max_age_hours: Max age for temp files
            temp_max_size_gb: Max total size for temp directory
            download_max_age_days: Max age for completed download records
            library_paths: Library paths to check for orphaned/duplicate files

        Returns:
            Combined cleanup results
        """
        if library_paths is None:
            library_paths = [
                "/library/movies",
                "/library/shows",
            ]

        results = {
            "temp_cleanup": await self.cleanup_transcode_temp(
                temp_path=temp_path,
                max_age_hours=temp_max_age_hours,
                max_size_gb=temp_max_size_gb,
            ),
            "download_records": await self.cleanup_old_downloads(
                max_age_days=download_max_age_days,
            ),
            "orphaned_files": await self.cleanup_orphaned_media_files(),
            "duplicates": {},
        }

        for lib_path in library_paths:
            name = Path(lib_path).name
            results["duplicates"][name] = await self.cleanup_library_duplicates(
                library_path=lib_path,
            )

        # Add storage overview after cleanup
        results["storage_after"] = await self.get_storage_overview(
            temp_path=temp_path,
            library_paths=library_paths,
        )

        return results
