import asyncio
import logging
from typing import Any

from streamarr.indexers.base import IndexerBase, IndexerError

logger = logging.getLogger(__name__)


class Torznab(IndexerBase):
    def __init__(self, *args, **kwargs):
        self._init_common(**kwargs)
        self.id = kwargs.get("id", "torznab")

    def get_name(self) -> str:
        return "Torznab"

    async def _search(
        self, function: str, params: dict[str, str | None]
    ) -> list[dict[str, Any]]:
        """
        Executes a search request to the Torznab API with controlled concurrency and retry logic.

        Args:
            function (str): The specific search function to call (e.g., "movie", "tvsearch").
            params (dict): The parameters to send with the request.

        Returns:
            list[dict]: A list of items returned from the search, each enriched with an "indexer_id".
        """
        params = {k: v for k, v in params.items() if v is not None}
        logger.debug("Torznab search: function=%s params=%s", function, params)

        data = await self._request(function=function, params=params)
        items = data.get("channel", {}).get("item", [])

        offset_attr = data["channel"]["response"]["@attributes"]
        offset = int(offset_attr["offset"]) + 100
        total = int(offset_attr["total"])
        max_offset = min(total, 1000)
        semaphore = asyncio.Semaphore(self.concurrent_requests)

        async def limited_request(offset: int) -> list[dict[str, Any]]:
            async with semaphore:
                task_params = {**params, "offset": offset}
                response = await self._request(function=function, params=task_params)
                return response.get("channel", {}).get("item", [])

        tasks = [limited_request(offset) for offset in range(offset, max_offset, 100)]
        for task in asyncio.as_completed(tasks):
            try:
                r = await task
                items.extend(r)
            except IndexerError:
                return []
        items = [
            {
                **item,
                "indexer_id": self.id,
                "publish_date": item.get("pubDate"),
            }
            for item in items
        ]
        logger.debug("Torznab search function=%s returned %d results", function, len(items))
        return items

    async def search_movie(
        self,
        q: str | None = None,
        imdb_id: str | None = None,
        categories: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """
        Searches for a movie based on query, IMDb ID, and/or categories.

        Args:
            q (str, optional): The search query string.
            imdb_id (str, optional): The IMDb ID of the movie.
            categories (str, optional): The categories to filter the search.

        Returns:
            list[dict]: A list of movies matching the search criteria, each enriched with an "indexer_id".
        """
        params = {
            "imdbid": imdb_id,
            "q": q,
            "cat": categories,
        }
        return await self._search("movie", params)

    async def fetch_recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Single-page latest feed (``t=search`` with no query) for RSS
        sync. One request per indexer per tick; [] on any error."""
        try:
            data = await self._request(function="search", params={})
        except IndexerError:
            return []
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("fetch_recent failed for %s: %s", self.id, e)
            return []

        raw = data.get("channel", {}).get("item", []) if isinstance(data, dict) else []
        if isinstance(raw, dict):
            raw = [raw]
        if not isinstance(raw, list):
            return []
        items = [
            {
                **item,
                "indexer_id": self.id,
                "publish_date": item.get("pubDate"),
            }
            for item in raw[:limit]
        ]
        logger.debug("Torznab fetch_recent %s returned %d items", self.id, len(items))
        return items

    async def get_feed(self):
        """Back-compat alias for the old (broken) stub name."""
        return await self.fetch_recent()

    async def search_show(
        self,
        q: str | None = None,
        tvdb_id: str | None = None,
        imdb_id: str | None = None,
        categories: str | None = None,
        season: str | None = None,
        ep: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """
        Searches for a TV show based on query, TVDB/IMDB ID, and/or categories.

        Uses tiered ID priority (like Sonarr): tvdbid > imdbid > query text.
        """
        params = {
            "tvdbid": tvdb_id,
            "imdbid": imdb_id,
            "q": q,
            "cat": categories,
            "season": season,
            "ep": ep,
        }
        return await self._search("tvsearch", params)

    async def search_music(
        self,
        q: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        categories: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Search for music releases using Torznab audio search."""
        params = {
            "artist": artist,
            "album": album,
            "q": q,
            "cat": categories,
        }
        return await self._search("music", params)

    async def search_book(
        self,
        q: str | None = None,
        author: str | None = None,
        title: str | None = None,
        categories: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Search for book/audiobook releases using Torznab."""
        if not categories:
            categories = "7010,3030,7020"

        combined_q = q
        if not combined_q:
            parts = []
            if author:
                parts.append(author)
            if title:
                parts.append(title)
            combined_q = " ".join(parts) if parts else None

        params = {"q": combined_q, "cat": categories}

        try:
            results = await self._search("book", params)
            if results:
                return results
        except Exception:
            pass

        return await self._search("search", params)

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate Torznab configuration by testing API connection.

        Args:
            config: Configuration dictionary with base_url and api_key

        Returns:
            dict: Validation result with 'valid' (bool) and 'errors' (list)
        """
        errors = []

        # Check required fields
        if not config.get("base_url"):
            errors.append("Base URL is required")
        if not config.get("api_key"):
            errors.append("API key is required")

        if errors:
            return {"valid": False, "errors": errors}

        # Test connection by fetching capabilities
        try:
            response = await self._request(function="caps", params={})

            # Check if we got valid capabilities response
            if "channel" not in response:
                errors.append("Invalid response from indexer - missing capabilities")
                return {"valid": False, "errors": errors}

            # Successfully connected
            logger.info("Torznab config validation successful for %s", self.base_url)
            return {"valid": True, "errors": []}

        except IndexerError as e:
            logger.warning("Torznab config validation failed for %s: %s", self.base_url, e)
            errors.append(f"Connection failed: {str(e)}")
            return {"valid": False, "errors": errors}
        except Exception as e:
            logger.error("Torznab config validation error for %s: %s", self.base_url, e)
            errors.append(f"Unexpected error: {str(e)}")
            return {"valid": False, "errors": errors}


# Export plugin class for loader
PLUGIN_CLASS = Torznab
