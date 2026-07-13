import logging
from typing import Any

from streamarr.downloaders.base import DownloaderBase
from streamarr.utils.http import make_async_client

logger = logging.getLogger(__name__)


class Deluge(DownloaderBase):
    """
    Deluge torrent client plugin.

    Communicates with Deluge Web UI via JSON-RPC API.
    """

    def __init__(self, base_url: str, api_key: str, verify_ssl: bool = True):
        self.base_url = base_url
        self.password = api_key  # Deluge uses password authentication
        self.client = make_async_client(verify=verify_ssl)
        self.cookie = None
        self._request_id = 0

    def get_name(self) -> str:
        """Get the plugin name."""
        return "Deluge"

    def _get_next_id(self) -> int:
        """Get next request ID for JSON-RPC."""
        self._request_id += 1
        return self._request_id

    async def _ensure_authenticated(self):
        """Ensure we have a valid authentication cookie."""
        if self.cookie is None:
            await self._authenticate()

    async def _authenticate(self):
        """Authenticate with Deluge Web UI."""
        response = await self.client.post(
            f"{self.base_url}/json",
            json={
                "method": "auth.login",
                "params": [self.password],
                "id": self._get_next_id(),
            },
        )
        data = response.json()

        if data.get("error"):
            raise Exception(f"Deluge authentication failed: {data['error']}")

        if not data.get("result"):
            raise Exception("Deluge authentication failed: Invalid password")

        # Store the cookie for future requests
        self.cookie = response.cookies

    async def _request(self, method: str, params: list | None = None) -> Any:
        """Make a JSON-RPC request to Deluge."""
        await self._ensure_authenticated()

        if params is None:
            params = []

        response = await self.client.post(
            f"{self.base_url}/json",
            json={
                "method": method,
                "params": params,
                "id": self._get_next_id(),
            },
            cookies=self.cookie,
        )

        data = response.json()

        if data.get("error"):
            # Token might have expired, try re-authenticating once
            if "Not authenticated" in str(data.get("error")):
                self.cookie = None
                await self._authenticate()
                # Retry the request
                response = await self.client.post(
                    f"{self.base_url}/json",
                    json={
                        "method": method,
                        "params": params,
                        "id": self._get_next_id(),
                    },
                    cookies=self.cookie,
                )
                data = response.json()

                if data.get("error"):
                    raise Exception(f"Deluge API error: {data['error']}")
            else:
                raise Exception(f"Deluge API error: {data['error']}")

        return data.get("result")

    async def add_by_url(self, url: str, priority: int | None = 0):
        """
        Add a torrent by URL or magnet link.

        Args:
            url: Torrent URL or magnet link
            priority: Priority (kept for API compatibility, not used by Deluge)

        Returns:
            dict with torrent hash

        Raises:
            Exception: If torrent addition fails
        """
        logger.info(f"Adding torrent with URL: {url}")

        # Deluge's web.add_torrents method
        # Returns the torrent hash if successful
        result = await self._request(
            "web.add_torrents",
            [
                [
                    {
                        "path": url,
                        "options": {},
                    }
                ]
            ],
        )

        if result and len(result) > 0:
            # Result format: [[success, torrent_hash, ...]]
            if isinstance(result[0], list) and len(result[0]) > 1:
                torrent_hash = result[0][1]
            else:
                torrent_hash = result[0] if isinstance(result[0], str) else None

            if not torrent_hash:
                logger.error(f"Unexpected Deluge response format: {result}")
                raise Exception("Failed to extract torrent hash from Deluge response")

            return {"torrent_hash": torrent_hash}
        else:
            raise Exception("Failed to add torrent to Deluge: Empty response")

    async def get_downloads(self) -> list[dict[str, Any]]:
        """
        Get all torrents and their status.

        Returns:
            list of download dictionaries with standardized format
        """
        logger.info("Fetching all downloads from Deluge")

        # Get torrent status for all torrents
        # Fields we want: name, state, progress, eta, save_path, hash
        torrents = await self._request(
            "web.update_ui",
            [
                [
                    "name",
                    "state",
                    "progress",
                    "eta",
                    "save_path",
                    "hash",
                ],
                {},
            ],
        )

        downloads = []

        if torrents and "torrents" in torrents:
            for torrent_hash, torrent_data in torrents["torrents"].items():
                # Map Deluge states to our standard states
                state = torrent_data.get("state", "Unknown")
                status_map = {
                    "Downloading": "Downloading",
                    "Seeding": "Completed",
                    "Paused": "Paused",
                    "Checking": "Checking",
                    "Queued": "Queued",
                    "Error": "Failed",
                }
                status = status_map.get(state, state)

                # Progress is in percentage (0-100)
                progress = torrent_data.get("progress", 0.0)

                # ETA is in seconds (-1 if unknown)
                eta = torrent_data.get("eta", 0)
                timeleft = eta if eta > 0 else 0

                download = {
                    "external_id": torrent_hash,
                    "timeleft": timeleft,
                    "progress": progress,
                    "status": status,
                    "path": torrent_data.get("save_path", ""),
                }
                downloads.append(download)

        return downloads

    async def remove(self, torrent_hash: str | list[str]) -> Any:
        """
        Remove torrent(s) from Deluge.

        Args:
            torrent_hash: Single hash or list of hashes

        Returns:
            bool indicating success
        """
        if isinstance(torrent_hash, str):
            torrent_hash = [torrent_hash]

        # Remove torrent but keep data (False for remove_data)
        result = await self._request(
            "core.remove_torrents",
            [torrent_hash, False],
        )

        return result if result is not None else True

    async def pause_download(self, torrent_hash: str) -> Any:
        """Pause a torrent download."""
        result = await self._request("core.pause_torrent", [[torrent_hash]])
        return result

    async def resume_job(self, torrent_hash: str) -> Any:
        """Resume a paused torrent."""
        result = await self._request("core.resume_torrent", [[torrent_hash]])
        return result

    async def pause_queue(self) -> Any:
        """Pause all torrents."""
        # Get all torrent hashes first
        torrents = await self._request("web.update_ui", [["hash"], {}])
        if torrents and "torrents" in torrents:
            torrent_hashes = list(torrents["torrents"].keys())
            if torrent_hashes:
                await self._request("core.pause_torrent", [torrent_hashes])
        return True

    async def resume_queue(self) -> Any:
        """Resume all paused torrents."""
        # Get all torrent hashes first
        torrents = await self._request("web.update_ui", [["hash"], {}])
        if torrents and "torrents" in torrents:
            torrent_hashes = list(torrents["torrents"].keys())
            if torrent_hashes:
                await self._request("core.resume_torrent", [torrent_hashes])
        return True

    async def close(self) -> None:
        """Clean up plugin resources."""
        if self.client:
            await self.client.aclose()

    async def get_torrent_status(self, torrent_hash: str):
        """
        Get detailed status for a specific torrent.

        Args:
            torrent_hash: The torrent hash

        Returns:
            dict with torrent details
        """
        result = await self._request(
            "web.get_torrent_status",
            [
                torrent_hash,
                [
                    "name",
                    "state",
                    "progress",
                    "eta",
                    "save_path",
                    "total_done",
                    "total_size",
                ],
            ],
        )
        return result


# Export plugin class for loader
PLUGIN_CLASS = Deluge
