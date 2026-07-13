import logging
from typing import Any

from streamarr.downloaders.base import DownloaderBase
from streamarr.utils.http import make_async_client

logger = logging.getLogger(__name__)


class Spotdl(DownloaderBase):
    """Spotify track downloader plugin using the spotdl HTTP API.

    Downloads Spotify tracks as OGG files (320 kbps) via librespot.
    The ``url`` parameter passed to :meth:`add_by_url` is expected to be a
    Spotify track ID (e.g. ``3n3Ppam7vgaVa1iaRUc9Lp``).
    """

    def __init__(self, base_url: str, api_key: str | None = None, verify_ssl: bool = True):
        self.base_url = base_url.rstrip("/")
        self.client = make_async_client(verify=verify_ssl)

    def get_name(self) -> str:
        return "spotdl"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json: dict | None = None,
        params: dict | None = None,
    ) -> dict[str, Any]:
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
        """Queue a Spotify track for download.

        Args:
            url: Spotify track ID, URI, or URL.
        """
        track_id = url.split(":")[-1].split("/")[-1]
        logger.info("Queuing Spotify track %s for download", track_id)
        data = await self._request("POST", "/api/jobs", json={"track_id": track_id})
        return {
            "job_id": data.get("id"),
            "track_id": data.get("track_id"),
            "status": data.get("status"),
        }

    async def get_downloads(self) -> list[dict[str, Any]]:
        """Get all download jobs from spotdl."""
        jobs = await self._request("GET", "/api/jobs")
        downloads = []
        for job in jobs if isinstance(jobs, list) else []:
            logger.debug(f"spotdl job response: {job}")
            status = job.get("status", "unknown")
            progress = 100 if status in ("completed", "done") else 0
            mapped_status = self._map_status(status)
            output_path = job.get("path") or job.get("output_path")
            if output_path:
                output_path = self._map_path(output_path)
            downloads.append(
                {
                    "external_id": job.get("id"),
                    "status": mapped_status,
                    "progress": progress,
                    "timeleft": 0,
                    "path": output_path,
                }
            )
        return downloads

    async def get_job(self, job_id: str) -> dict[str, Any]:
        """Get status of a single download job."""
        return await self._request("GET", f"/api/jobs/{job_id}")

    async def remove(self, download_id: str | list[str]) -> Any:
        """Remove is not supported by spotdl — no-op."""
        logger.debug("spotdl does not support removing jobs")
        return None

    async def pause_download(self, download_id: str) -> Any:
        """Pause is not supported by spotdl — no-op."""
        logger.debug("spotdl does not support pausing downloads")
        return None

    async def resume_job(self, download_id: str) -> Any:
        """Resume is not supported by spotdl — no-op."""
        logger.debug("spotdl does not support resuming downloads")
        return None

    async def pause_queue(self) -> Any:
        """Pause queue is not supported by spotdl — no-op."""
        logger.debug("spotdl does not support pausing the queue")
        return None

    async def resume_queue(self) -> Any:
        """Resume queue is not supported by spotdl — no-op."""
        logger.debug("spotdl does not support resuming the queue")
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
        """Rewrite a spotdl container path to the backend mount path.

        Delegates to the single configurable mount translation so the
        remote/local prefixes live in exactly one place.
        """
        from streamarr.api.v1.webhooks import map_download_path

        return map_download_path("spotdl", path)

    @staticmethod
    def _map_status(status: str) -> str:
        """Map spotdl job status to the standard download status."""
        mapping = {
            "queued": "Queued",
            "downloading": "Downloading",
            "completed": "Completed",
            "done": "Completed",
            "failed": "Failed",
        }
        return mapping.get(status, status)


# Export plugin class for loader
PLUGIN_CLASS = Spotdl
