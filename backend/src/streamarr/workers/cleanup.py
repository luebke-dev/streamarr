"""Cleanup worker domain helpers."""

from __future__ import annotations

import logging

from streamarr.database import sessionmanager
from streamarr.services.settings import SettingsService
from streamarr.services.storage_cleanup import StorageCleanupService

logger = logging.getLogger(__name__)


class StorageCleanupWorker:
    async def cleanup_storage(self) -> dict:
        logger.info("Starting scheduled storage cleanup")
        try:
            async with sessionmanager.session() as db:
                settings_service = SettingsService(db)
                cleanup_service = StorageCleanupService(db)
                settings = await self._load_settings(settings_service)

                results = await self._run_cleanup(cleanup_service, settings)
                overview = await cleanup_service.get_storage_overview(
                    temp_path=settings["temp_path"]
                )
                logger.info(
                    "Storage cleanup complete. Temp disk usage: %s%%, Temp files deleted: %s, Download records removed: %s",
                    overview["temp"]["usage_percent"],
                    results["temp_cleanup"]["files_deleted"],
                    results["download_records"]["records_deleted"],
                )
                return results
        except Exception as exc:
            logger.error("Storage cleanup failed: %s", exc, exc_info=True)
            raise

    @staticmethod
    async def _load_settings(settings_service: SettingsService) -> dict:
        return {
            "temp_max_age_hours": await settings_service.get(
                "storage.temp_max_age_hours",
                2.0,
            ),
            "temp_max_size_gb": await settings_service.get(
                "storage.temp_max_size_gb",
                None,
            ),
            "download_max_age_days": await settings_service.get(
                "storage.download_record_max_age_days",
                30,
            ),
            "cleanup_orphaned": await settings_service.get(
                "storage.cleanup_orphaned_files",
                True,
            ),
            "cleanup_dupes": await settings_service.get(
                "storage.cleanup_duplicates",
                True,
            ),
            "temp_path": await settings_service.get("transcoding.temp_path", "/temp"),
            "rclone_retention_days": await settings_service.get(
                "storage.rclone_retention_days",
                7,
            ),
        }

    async def _run_cleanup(
        self,
        cleanup_service: StorageCleanupService,
        settings: dict,
    ) -> dict:
        results = {
            "temp_cleanup": await cleanup_service.cleanup_transcode_temp(
                temp_path=settings["temp_path"],
                max_age_hours=settings["temp_max_age_hours"],
                max_size_gb=settings["temp_max_size_gb"],
            ),
            "download_records": await cleanup_service.cleanup_old_downloads(
                max_age_days=settings["download_max_age_days"],
            ),
        }

        if settings["cleanup_orphaned"]:
            results["orphaned_files"] = (
                await cleanup_service.cleanup_orphaned_media_files()
            )
        if settings["cleanup_dupes"]:
            results["duplicates"] = await self._cleanup_duplicates(cleanup_service)
        if settings["rclone_retention_days"] and settings["rclone_retention_days"] > 0:
            results["rclone_retention"] = (
                await cleanup_service.cleanup_rclone_retention(
                    retention_days=settings["rclone_retention_days"],
                )
            )
        return results

    @staticmethod
    async def _cleanup_duplicates(cleanup_service: StorageCleanupService) -> dict:
        results = {}
        for lib_path in ["/library/movies", "/library/shows"]:
            name = lib_path.rsplit("/", 1)[-1]
            results[name] = await cleanup_service.cleanup_library_duplicates(
                library_path=lib_path,
            )
        return results
