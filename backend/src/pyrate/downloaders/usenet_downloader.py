import logging
from typing import Any

from pyrate.downloaders.base import DownloaderBase
from pyrate.utils.http import make_async_client

logger = logging.getLogger(__name__)


class UsenetDownloader(DownloaderBase):
    """Usenet downloader plugin using the usenet-downloader HTTP API.

    The ``url`` parameter passed to :meth:`add_by_url` is expected to be a
    URL to an NZB file (e.g. ``https://indexer.example/get/abc123``).
    """

    def __init__(self, base_url: str, api_key: str | None = None, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.client = make_async_client(verify=verify_ssl)

    def get_name(self) -> str:
        return "usenet_downloader"

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
        """Queue an NZB for download.

        Args:
            url: URL to an NZB file.
        """
        payload: dict[str, Any] = {"nzb_url": url}

        # name is required by the usenet-downloader API
        if "name" in kwargs:
            payload["name"] = kwargs["name"]
        else:
            payload["name"] = url.split("/")[-1].split("?")[0] or "download"
        if "category" in kwargs:
            payload["category"] = kwargs["category"]
        if "priority" in kwargs:
            payload["priority"] = kwargs["priority"]

        logger.info("Queuing NZB for download: %s", url[:80])
        data = await self._request("POST", "/api/jobs", json=payload)
        return {
            "job_id": data.get("id"),
            "name": data.get("name"),
            "status": data.get("status"),
        }

    async def get_downloads(self) -> list[dict[str, Any]]:
        """Get all download jobs from usenet-downloader."""
        jobs = await self._request("GET", "/api/jobs")
        downloads = []
        for job in jobs if isinstance(jobs, list) else []:
            status = job.get("status", "unknown")
            progress = job.get("progress", 0)
            mapped_status = self._map_status(status)
            # Empty destination resolves to the downloader's local base dir.
            destination = self._map_path(job.get("destination") or "")
            downloads.append(
                {
                    "external_id": job.get("id"),
                    "status": mapped_status,
                    "progress": progress,
                    "speed_bps": job.get("speed_bps", 0),
                    "timeleft": 0,
                    "path": destination,
                }
            )
        return downloads

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Get status of a single download job."""
        return await self._request("GET", f"/api/jobs/{job_id}")

    async def remove(self, download_id: str | list[str]) -> Any:
        """Cancel/remove a usenet job."""
        if isinstance(download_id, list):
            for did in download_id:
                await self._request("DELETE", f"/api/jobs/{did}")
        else:
            await self._request("DELETE", f"/api/jobs/{download_id}")
        return None

    async def pause_download(self, download_id: str) -> Any:
        return await self._request("POST", f"/api/jobs/{download_id}/pause")

    async def resume_job(self, download_id: str) -> Any:
        return await self._request("POST", f"/api/jobs/{download_id}/resume")

    async def pause_queue(self) -> Any:
        return await self._request("POST", "/api/control/pause")

    async def resume_queue(self) -> Any:
        return await self._request("POST", "/api/control/resume")

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @classmethod
    def _map_path(cls, path: str) -> str:
        """Rewrite a container path to the backend mount path.

        Delegates to the single configurable mount translation so the
        remote/local prefixes live in exactly one place.
        """
        from pyrate.api.v1.webhooks import map_download_path

        return map_download_path("usenet", path)

    @staticmethod
    def _map_status(status: str) -> str:
        """Map usenet-downloader job status to the standard download status."""
        mapping = {
            "queued": "Queued",
            "downloading": "Downloading",
            "paused": "Paused",
            "completed": "Completed",
            "failed": "Failed",
            "cancelled": "Cancelled",
        }
        return mapping.get(status, status)


PLUGIN_CLASS = UsenetDownloader
