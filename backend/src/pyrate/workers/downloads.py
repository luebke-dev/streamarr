"""Download worker domain helpers."""

from __future__ import annotations

import asyncio
import logging

import httpx

from pyrate.database import sessionmanager
from pyrate.models.downloads import DownloadStatus
from pyrate.services import DownloaderService, DownloadService

logger = logging.getLogger(__name__)


class DownloadRefreshWorker:
    def __init__(
        self,
        downloader_service_cls=DownloaderService,
        download_service_cls=DownloadService,
    ) -> None:
        self.downloader_service_cls = downloader_service_cls
        self.download_service_cls = download_service_cls

    async def refresh_downloads(self, refresh_downloader_task) -> None:
        logger.info("Starting refresh of downloads from all downloaders")
        try:
            async with sessionmanager.session() as db:
                downloaders = await self.downloader_service_cls(db).get_all()
                webhook_types = {"spotdl", "torrent_downloader"}
                poll_downloaders = [
                    downloader
                    for downloader in downloaders
                    if downloader.type.lower() not in webhook_types
                ]

                for iteration in range(6):
                    logger.info(
                        "Refreshing downloads (iteration %d/6)...",
                        iteration + 1,
                    )
                    for downloader in poll_downloaders:
                        await refresh_downloader_task.kiq(str(downloader.guid))

                    if iteration < 5:
                        await asyncio.sleep(10)
        except Exception as exc:
            logger.error("Download refresh failed: %s", exc)
            raise

    async def refresh_downloader(
        self,
        downloader_id: str,
        *,
        handle_completed_download_task,
        auto_download_media_item_task,
    ) -> None:
        async with sessionmanager.session() as db:
            downloader = await self.downloader_service_cls(db).get_by_id(downloader_id)
            download_service = self.download_service_cls(db)

            try:
                stats = await download_service.update_downloads_from_client(downloader)
            except (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout) as exc:
                logger.warning(
                    "Downloader %s (%s) unreachable: %s - skipping this poll",
                    downloader.label,
                    downloader.host,
                    exc,
                )
                return

            logger.info(
                "Refreshed downloader %s: %s updated, %s completed, %s failed",
                downloader_id,
                stats["updated"],
                stats["completed"],
                stats["failed"],
            )

            if stats["completed"] > 0:
                await self._queue_completed_downloads(
                    download_service,
                    downloader,
                    handle_completed_download_task,
                )

            if stats["failed"] > 0:
                await self._handle_failed_downloads(
                    download_service,
                    downloader,
                    auto_download_media_item_task,
                )

    async def _queue_completed_downloads(
        self,
        download_service: DownloadService,
        downloader,
        handle_completed_download_task,
    ) -> None:
        client = download_service.get_downloader_client(downloader)
        status = await client.get_downloads()
        for item in status:
            download = await download_service.get_by_external_id(item["external_id"])
            if not download or download.status != DownloadStatus.COMPLETED:
                continue

            path = await self._completed_download_path(client, download, item)
            if not path:
                logger.warning(
                    "Completed download %s has no path, skipping import",
                    download.external_id,
                )
                continue
            await handle_completed_download_task.kiq(download.external_id, path)

    async def _completed_download_path(self, client, download, item: dict) -> str | None:
        path = item["path"]
        if path:
            return path

        try:
            job_detail = await client.get_job(download.external_id)
            path = job_detail.get("path") or job_detail.get("output_path")
            if path and hasattr(client, "_map_path"):
                path = client._map_path(path)
            return path
        except Exception:
            return None

    async def _handle_failed_downloads(
        self,
        download_service: DownloadService,
        downloader,
        auto_download_media_item_task,
    ) -> None:
        client = download_service.get_downloader_client(downloader)
        status = await client.get_downloads()
        for item in status:
            if item["status"] != DownloadStatus.FAILED:
                continue

            download = await download_service.get_by_external_id(item["external_id"])
            if not download or download.status != DownloadStatus.FAILED:
                continue

            logger.warning("Download failed: %s (%s)", download.title, download.external_id)
            await download_service.blacklist_download(
                download,
                "Download failed in downloader client",
            )
            media_item_guid = await download_service.get_media_item_guid_for_download(
                download
            )
            retry_info = await download_service.handle_failed_download(
                {
                    "blacklisted": True,
                    "media_item_guid": str(media_item_guid) if media_item_guid else None,
                },
                item["external_id"],
            )
            if retry_info:
                await auto_download_media_item_task.kiq(
                    retry_info["media_item_guid"],
                    None,
                    retry_info["user_guid"],
                )

            try:
                await client.remove_old(download.external_id)
            except Exception as exc:
                logger.warning(
                    "Failed to remove failed download from client history: %s",
                    exc,
                )
