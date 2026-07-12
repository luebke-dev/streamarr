import logging
import time
from typing import Any

import httpx

from pyrate.metadata.base import MetadataBase

logger = logging.getLogger(__name__)


class TVDB(MetadataBase):
    """
    TheTVDB metadata plugin for TV shows.

    Provides metadata for TV series, episodes, actors, and more via TheTVDB API v4.
    Supports authentication with API key and optional subscriber PIN for premium features.
    """

    def __init__(
        self,
        api_key: str,
        pin: str | None = None,
        language: str = "de",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.api_key = api_key
        self.pin = pin
        self.language = language
        self.base_url = "https://api4.thetvdb.com/v4"
        self.token: str | None = None
        self.token_expires_at: float | None = None

        if client is None:
            self.client = httpx.AsyncClient()
        else:
            self.client = client

    def get_name(self) -> str:
        """Get the plugin name."""
        return "TheTVDB"

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for TheTVDB."""
        return {
            "api_key": {
                "type": "password",
                "label": "API Key",
                "hint": "Your TheTVDB API Key",
                "required": True,
                "placeholder": "Enter your TheTVDB API key",
                "info_text": "Get API Key at: https://thetvdb.com/dashboard/account/apikey",
                "info_link": "https://thetvdb.com/dashboard/account/apikey",
            },
            "pin": {
                "type": "password",
                "label": "Subscriber PIN",
                "hint": "Optional subscriber PIN for premium features",
                "required": False,
                "placeholder": "Enter your subscriber PIN (optional)",
            },
        }

    async def _authenticate(self) -> bool:
        """
        Authenticate with TheTVDB API to get access token.

        Returns:
            bool: True if authentication was successful
        """
        try:
            payload = {"apikey": self.api_key}
            if self.pin:
                payload["pin"] = self.pin

            response = await self.client.post(f"{self.base_url}/login", json=payload)
            response.raise_for_status()

            data = response.json()
            if data.get("status") == "success":
                self.token = data["data"]["token"]
                # Tokens typically expire after 1 month, set expiry to 29 days
                self.token_expires_at = time.time() + (29 * 24 * 60 * 60)
                logger.info("Successfully authenticated with TheTVDB API")
                return True
            else:
                logger.error(f"TheTVDB authentication failed: {data.get('message')}")
                return False

        except Exception as e:
            logger.error(f"Failed to authenticate with TheTVDB API: {e}")
            return False

    async def _ensure_authenticated(self) -> bool:
        """
        Ensure we have a valid access token.

        Returns:
            bool: True if we have a valid token
        """
        if (
            self.token is None
            or self.token_expires_at is None
            or time.time() >= self.token_expires_at
        ):
            return await self._authenticate()
        return True

    async def _request(
        self, endpoint: str, params: dict | None = None
    ) -> dict[str, Any]:
        """
        Make a request to the TheTVDB API.

        Args:
            endpoint: API endpoint path
            params: Query parameters

        Returns:
            dict: JSON response data
        """
        if not await self._ensure_authenticated():
            return {}

        if params is None:
            params = {}

        try:
            headers = {
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json",
            }

            response = await self.client.get(
                f"{self.base_url}/{endpoint}",
                headers=headers,
                params=params,
            )
            response.raise_for_status()

            data = response.json()
            if data.get("status") == "success":
                return data.get("data", {})
            else:
                logger.error(f"TheTVDB API error: {data.get('message')}")
                return {}

        except httpx.HTTPStatusError as e:
            logger.error(f"HTTP error when requesting {endpoint}: {e}")
            return {}
        except Exception as e:
            logger.error(f"Error when requesting {endpoint}: {e}")
            return {}

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """
        Search for TV series.

        Args:
            query: Search query string
            **kwargs: Additional parameters like 'year', 'type'

        Returns:
            list[dict]: Search results
        """
        params = {
            "query": query,
            "type": kwargs.get("type", "series"),
        }

        if "year" in kwargs:
            params["year"] = kwargs["year"]

        result = await self._request("search", params=params)

        if isinstance(result, list):
            return result
        elif isinstance(result, dict) and "series" in result:
            return result.get("series", [])
        else:
            return []

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """
        Get detailed information about a TV series.

        Args:
            media_id: The TheTVDB series ID
            **kwargs: Additional parameters like 'extended' for more details

        Returns:
            dict: Detailed series information
        """
        endpoint = f"series/{media_id}"

        if kwargs.get("extended"):
            endpoint += "/extended"

        result = await self._request(endpoint)
        return result if isinstance(result, dict) else {}

    async def get_series_details(self, series_id: str | int) -> dict[str, Any]:
        """
        Get detailed information about a series.

        Args:
            series_id: The TheTVDB series ID

        Returns:
            dict: Detailed series information
        """
        return await self._request(f"series/{series_id}/extended")

    async def get_series_episodes(
        self, series_id: str | int, season: int | None = None, page: int = 0
    ) -> dict[str, Any]:
        """
        Get episodes for a series.

        Args:
            series_id: The TheTVDB series ID
            season: Optional season number to filter
            page: Page number for pagination

        Returns:
            dict: Episodes data with pagination info
        """
        params = {"page": page}
        if season is not None:
            params["season"] = season

        result = await self._request(
            f"series/{series_id}/episodes/default", params=params
        )
        return result if isinstance(result, dict) else {}

    async def get_episode_details(self, episode_id: str | int) -> dict[str, Any]:
        """
        Get detailed information about an episode.

        Args:
            episode_id: The TheTVDB episode ID

        Returns:
            dict: Detailed episode information
        """
        result = await self._request(f"episodes/{episode_id}/extended")
        return result if isinstance(result, dict) else {}

    async def search_series(
        self, query: str, year: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Search for TV series by name.

        Args:
            query: Series name to search for
            year: Optional year to filter results

        Returns:
            list[dict]: List of matching series
        """
        return await self.search(query, type="series", year=year)

    async def get_series_by_imdb_id(self, imdb_id: str) -> dict[str, Any]:
        """
        Get series information by IMDb ID.

        Args:
            imdb_id: IMDb ID (e.g., 'tt0944947')

        Returns:
            dict: Series information
        """
        # Search by remote ID
        params = {"imdbId": imdb_id}
        result = await self._request("search/remoteid", params=params)

        if isinstance(result, list) and len(result) > 0:
            # Get the first series from results
            series_id = result[0].get("id")
            if series_id:
                return await self.get_series_details(series_id)

        return {}

    async def get_series_artwork(self, series_id: str | int) -> list[dict[str, Any]]:
        """
        Get artwork (posters, banners, etc.) for a series.

        Args:
            series_id: The TheTVDB series ID

        Returns:
            list[dict]: List of artwork items
        """
        result = await self._request(f"series/{series_id}/artworks")
        return result if isinstance(result, list) else []

    async def close(self) -> None:
        """Clean up plugin resources."""
        if self.client:
            await self.client.aclose()


# Export plugin class for loader
PLUGIN_CLASS = TVDB
