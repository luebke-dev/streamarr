import logging
from typing import Any

from pyrate.downloaders.base import DownloaderBase
from pyrate.utils.http import make_async_client

logger = logging.getLogger(__name__)


class TorrentDownloader(DownloaderBase):
    """BitTorrent downloader plugin using the torrent-downloader HTTP API.

    The ``url`` parameter passed to :meth:`add_by_url` is expected to be a
    magnet URI (e.g. ``magnet:?xt=urn:btih:...``) or a torrent file URL.
    """

    REMOTE_PREFIX = "/downloads"
    LOCAL_PREFIX = "/torrent-downloads"

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.client = make_async_client()

    def get_name(self) -> str:
        return "torrent_downloader"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        response = await self.client.request(
            method=method,
            url=f"{self.base_url}{path}",
            json=json,
            params=params,
        )
        response.raise_for_status()
        return response.json()

    # ------------------------------------------------------------------
    # DownloaderBase interface
    # ------------------------------------------------------------------

    async def add_by_url(self, url: str, **kwargs) -> dict[str, Any]:
        """Queue a torrent for download.

        Args:
            url: Magnet URI or HTTP URL to a .torrent file.
        """
        if url.startswith("magnet:"):
            payload = {"magnet_uri": url}
        else:
            payload = {"torrent_url": url}

        if "name" in kwargs:
            payload["name"] = kwargs["name"]
        if "category" in kwargs:
            payload["category"] = kwargs["category"]
        if "priority" in kwargs:
            payload["priority"] = kwargs["priority"]

        logger.info(f"Queuing torrent for download: {url[:80]}...")
        data = await self._request("POST", "/api/jobs", json=payload)
        return {
            "job_id": data.get("id"),
            "info_hash": data.get("info_hash"),
            "status": data.get("status"),
        }

    async def get_downloads(self) -> list[dict[str, Any]]:
        """Get all download jobs from torrent-downloader."""
        jobs = await self._request("GET", "/api/jobs")
        downloads = []
        for job in jobs if isinstance(jobs, list) else []:
            status = job.get("status", "unknown")
            progress = job.get("progress", 0)
            mapped_status = self._map_status(status)
            destination = job.get("destination")
            if destination:
                destination = self._map_path(destination)
            downloads.append(
                {
                    "external_id": job.get("id"),
                    "status": mapped_status,
                    "progress": progress,
                    "timeleft": 0,
                    "path": destination,
                    "download_speed": job.get("download_speed", 0),
                    "upload_speed": job.get("upload_speed", 0),
                    "peers_connected": job.get("peers_connected", 0),
                    "seeds_connected": job.get("seeds_connected", 0),
                }
            )
        return downloads

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Get status of a single download job."""
        return await self._request("GET", f"/api/jobs/{job_id}")

    async def remove(self, download_id: str | list[str]) -> Any:
        """Cancel/remove a torrent job."""
        if isinstance(download_id, list):
            for did in download_id:
                await self._request("DELETE", f"/api/jobs/{did}")
        else:
            await self._request("DELETE", f"/api/jobs/{download_id}")
        return None

    async def pause_download(self, download_id: str) -> Any:
        """Pause is not supported — no-op."""
        logger.debug("torrent-downloader does not support pausing downloads")
        return None

    async def resume_job(self, download_id: str) -> Any:
        """Resume is not supported — no-op."""
        logger.debug("torrent-downloader does not support resuming downloads")
        return None

    async def pause_queue(self) -> Any:
        """Pause queue is not supported — no-op."""
        logger.debug("torrent-downloader does not support pausing the queue")
        return None

    async def resume_queue(self) -> Any:
        """Resume queue is not supported — no-op."""
        logger.debug("torrent-downloader does not support resuming the queue")
        return None

    async def close(self) -> None:
        """Clean up HTTP client resources."""
        if self.client:
            await self.client.aclose()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _map_path(cls, path: str) -> str:
        """Rewrite a container path to the backend mount path."""
        if path.startswith(cls.REMOTE_PREFIX):
            return cls.LOCAL_PREFIX + path[len(cls.REMOTE_PREFIX) :]
        return path

    @staticmethod
    def _map_status(status: str) -> str:
        """Map torrent-downloader job status to the standard download status."""
        mapping = {
            "queued": "Queued",
            "downloading": "Downloading",
            "seeding": "Seeding",
            "completed": "Completed",
            "failed": "Failed",
            "cancelled": "Cancelled",
        }
        return mapping.get(status, status)


# Export plugin class for loader
PLUGIN_CLASS = TorrentDownloader


async def async_setup(config: dict[str, Any]) -> bool:
    """Validate plugin configuration."""
    if "base_url" not in config:
        logger.error("torrent_downloader plugin requires 'base_url' in configuration")
        return False
    logger.info("torrent_downloader plugin setup completed successfully")
    return True
