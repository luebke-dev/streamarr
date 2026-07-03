import logging
from datetime import timedelta
from typing import Any

from pyrate.downloaders.base import DownloaderBase
from pyrate.utils.http import make_async_client

logger = logging.getLogger(__name__)


class Sabnzbd(DownloaderBase):
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url
        self.api_key = api_key
        self.client = make_async_client()

    def get_name(self) -> str:
        """Get the plugin name."""
        return "SABnzbd"

    async def _request(
        self, sabnzbd_method: str, method: str = "GET", params: dict | None = None
    ):
        if params is None:
            params = {}
        params = {k: v for k, v in params.items() if v is not None}
        response = await self.client.request(
            method=method,
            url=f"{self.base_url}/api",
            params={
                "apikey": self.api_key,
                "mode": sabnzbd_method,
                "output": "json",
                **params,
            },
        )
        data = response.json()
        return data

    async def add_by_url(
        self, url: str, priority: int | None = 0, **kwargs
    ) -> dict[str, Any]:
        """Add a download by URL."""
        logging.info(f"Adding Download with URL: {url}")
        data = await self._request(
            sabnzbd_method="addurl", params={"name": url, "priority": priority}
        )

        return data

    async def change_complete_action(self, action: str):
        data = await self._request(
            sabnzbd_method="change_complete_action", params={"value": action}
        )
        return data

    async def sort_queue(self, key: str, direction: str):
        data = await self._request(
            sabnzbd_method="queue",
            params={"name": "sort", "sort": key, "direction": direction},
        )
        return data

    async def _queue(
        self,
        start: int | None = None,
        limit: int | None = None,
        category: str | None = None,
        priority: int | None = None,
        search: str | None = None,
        nzo_ids: str | None = None,
    ):
        data = await self._request(
            sabnzbd_method="queue",
            params={
                "start": start,
                "limit": limit,
                "category": category,
                "priority": priority,
                "search": search,
                "nzo_ids": nzo_ids,
            },
        )
        return data["queue"]["slots"]

    async def get_downloads(self) -> list[dict[str, Any]]:
        """Get all downloads and their status."""
        logger.info("Fetching all downloads")
        queue = await self._queue()
        history = await self._history()
        downloads = []
        for item in queue:
            timeleft = item["timeleft"].split(":")
            timeleft = timedelta(
                hours=int(timeleft[0]),
                minutes=int(timeleft[1]),
                seconds=int(timeleft[2]),
            )
            download = {
                "external_id": item["nzo_id"],
                "timeleft": timeleft.seconds,
                "progress": item["percentage"],
                "status": item["status"],
            }
            downloads.append(download)

        for item in history:
            download = {
                "external_id": item["nzo_id"],
                "status": item["status"],
                "progress": 100,
                "timeleft": 0,
                "path": item["storage"],
            }
            downloads.append(download)
        return downloads

    async def get_files(self, nzo_id: str):
        data = await self._request(sabnzbd_method="get_files", params={"value": nzo_id})
        return data["files"]

    async def server_stats(self):
        data = await self._request(sabnzbd_method="server_stats")
        return data

    async def remove(self, download_id: str | list[str]) -> Any:
        """Remove download(s)."""
        data = await self._request(
            sabnzbd_method="queue",
            params={
                "name": "delete",
                "value": download_id
                if isinstance(download_id, str)
                else ",".join(download_id),
            },
        )
        return data["status"]

    async def remove_old(self, download_id: str):
        data = await self._request(
            sabnzbd_method="history", params={"name": "delete", "value": download_id}
        )
        return data["status"]

    async def pause_download(self, download_id: str) -> Any:
        """Pause a specific download."""
        data = await self._request(
            sabnzbd_method="queue", params={"name": "pause", "value": download_id}
        )
        return data

    async def purge_queue(
        self, search: str | None = None, delete_files: bool | None = None
    ):
        data = await self._request(
            sabnzbd_method="queue", params={"search": search, "del_files": delete_files}
        )
        return data

    async def resume_job(self, nzo_id: str) -> Any:
        """Resume a paused download."""
        data = await self._request(
            sabnzbd_method="queue", params={"name": "resume", "value": nzo_id}
        )
        return data

    async def resume_queue(self) -> Any:
        """Resume all paused downloads."""
        data = await self._request(sabnzbd_method="resume")
        return data["status"]

    async def pause_queue(self) -> Any:
        """Pause all downloads."""
        data = await self._request(sabnzbd_method="pause")
        return data["status"]

    async def close(self) -> None:
        """Clean up plugin resources."""
        if self.client:
            await self.client.aclose()

    async def change_job_name(
        self, nzo_id: str, new_name: str | None = None, new_password: str | None = None
    ):
        data = await self._request(
            sabnzbd_method="queue",
            params={
                "name": "rename",
                "value": nzo_id,
                "value2": new_name,
                "value3": new_password,
            },
        )

        return data

    async def change_job_priority(self, nzo_id: str, priority: int):
        data = await self._request(
            sabnzbd_method="queue",
            params={
                "name": "priority",
                "value": nzo_id,
                "value2": priority,
            },
        )

        return data

    async def change_job_post_processing_options(self, nzo_id: str, options: int):
        data = await self._request(
            sabnzbd_method="change_opts",
            params={"value": nzo_id, "value2": options},
        )

        return data

    async def change_job_category(self, nzo_id: str, category: str):
        data = await self._request(
            sabnzbd_method="change_cat",
            params={"value": nzo_id, "value2": category},
        )

        return data

    async def set_speedlimit(self, limit: str | int | None):
        data = await self._request(
            sabnzbd_method="config", params={"name": "speedlimit", "value": limit}
        )
        return data["status"]

    async def _history(
        self,
        start: int | None = None,
        limit: int | None = None,
        category: str | None = None,
        nzo_ids: list[str] | None = None,
    ):
        data = await self._request(
            sabnzbd_method="history",
            params={
                "start": start,
                "limit": limit,
                "category": category,
                "nzo_ids": nzo_ids,
            },
        )

        return data["history"]["slots"]

    async def version(self):
        data = await self._request(sabnzbd_method="version")
        return data

    async def restart(self):
        data = await self._request(sabnzbd_method="restart")
        return data

    async def shutdown(self):
        data = await self._request(sabnzbd_method="shutdown")
        return data

    async def get_categories(self):
        data = await self._request(sabnzbd_method="get_cats")
        return data

    async def get_scripts(self):
        data = await self._request(sabnzbd_method="get_scripts")
        return data


# Export plugin class for loader
PLUGIN_CLASS = Sabnzbd


async def async_setup(config: dict[str, Any]) -> bool:
    """
    Set up the SABnzbd plugin.

    This function is called by the plugin loader during initialization.

    Args:
        config: Plugin configuration from manifest

    Returns:
        bool: True if setup was successful
    """
    # Validate required configuration
    required = ["base_url", "api_key"]
    for field in required:
        if field not in config:
            logger.error(f"SABnzbd plugin requires '{field}' in configuration")
            return False

    logger.info("SABnzbd plugin setup completed successfully")
    return True
