import asyncio
import logging
from typing import Any

from streamarr.indexers.base import IndexerBase, IndexerError

logger = logging.getLogger(__name__)


class Newznab(IndexerBase):
    def __init__(self, *args, **kwargs):
        self._init_common(**kwargs)
        self.id = kwargs.get("id", "newznab")

    def get_name(self) -> str:
        return "Newznab"

    async def _search(
        self, function: str, params: dict[str, str | None]
    ) -> list[dict[str, Any]]:
        """
        Executes a search request to the Newznab API with controlled concurrency and retry logic.

        Args:
            function (str): The specific search function to call (e.g., "movie", "tvsearch").
            params (dict): The parameters to send with the request.

        Returns:
            list[dict]: A list of items returned from the search, each enriched with an "indexer_id".
        """
        params = {k: v for k, v in params.items() if v is not None}
        logger.debug("Newznab search: function=%s params=%s", function, params)

        data = await self._request(function=function, params=params)

        # Newznab returns "item" as a list when there are multiple hits and a
        # single dict when there's only one. Normalise so downstream code can
        # safely iterate.
        def _items_of(payload: dict[str, Any]) -> list[dict[str, Any]]:
            raw = payload.get("channel", {}).get("item", [])
            if isinstance(raw, dict):
                return [raw]
            return raw if isinstance(raw, list) else []

        items = _items_of(data)

        offset_attr = data["channel"]["response"]["@attributes"]
        offset = int(offset_attr["offset"]) + 100
        total = int(offset_attr["total"])
        # Limit pagination to max 10 pages (1000 results) to avoid hammering the indexer
        max_offset = min(total, 1000)
        semaphore = asyncio.Semaphore(self.concurrent_requests)

        async def limited_request(offset: int) -> list[dict[str, Any]]:
            async with semaphore:
                task_params = {**params, "offset": offset}
                response = await self._request(function=function, params=task_params)
                return _items_of(response)

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
                "size": self._extract_size(item),
                "publish_date": item.get("pubDate"),
            }
            for item in items
        ]
        logger.debug("Newznab search function=%s returned %d results", function, len(items))
        return items

    @staticmethod
    def _extract_size(item: dict[str, Any]) -> int | None:
        """
        Extract file size from a Newznab API item.

        Newznab returns size in enclosure.@attributes.length and/or
        in newznab:attr / attr entries with name="size".

        Args:
            item: A single item dict from the Newznab JSON response.

        Returns:
            File size in bytes as int, or None if not found.
        """
        # Try enclosure.@attributes.length first (most common)
        try:
            length = item.get("enclosure", {}).get("@attributes", {}).get("length")
            if length:
                size = int(length)
                if size > 0:
                    return size
        except (ValueError, TypeError):
            pass

        # Try newznab:attr entries (alternative format)
        for attr_key in ("newznab:attr", "attr"):
            attrs = item.get(attr_key)
            if attrs is None:
                continue
            # attrs can be a single dict or a list of dicts
            if isinstance(attrs, dict):
                attrs = [attrs]
            if isinstance(attrs, list):
                for attr in attrs:
                    try:
                        attr_data = attr if isinstance(attr, dict) else {}
                        # Handle @attributes wrapper
                        inner = attr_data.get("@attributes", attr_data)
                        if inner.get("name") == "size":
                            size = int(inner.get("value", 0))
                            if size > 0:
                                return size
                    except (ValueError, TypeError):
                        continue

        return None

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
        sync. Does NOT paginate — one request per indexer per tick.
        Returns [] on any indexer error so a bad feed is just skipped.
        """
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
                "size": self._extract_size(item),
                "publish_date": item.get("pubDate"),
            }
            for item in raw[:limit]
        ]
        logger.debug("Newznab fetch_recent %s returned %d items", self.id, len(items))
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
        """
        Search for music releases using Newznab audio search.

        Supports the Newznab t=music function with artist/album parameters.
        Falls back to t=search with combined query if t=music is not supported.
        """
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
        """Search for book / audiobook releases via Newznab.

        We've seen indexers (e.g. Scenenzbs) silently ignore the ``q`` param
        on ``t=book`` and return their entire eBook latest-feed (~250 rows
        of unrelated authors), which then floods the matcher. Prefer the
        plain ``t=search`` endpoint with the query and category filter —
        Newznab guarantees query matching there. ``t=book`` only runs as a
        fallback when ``t=search`` returns nothing.

        Categories: 7010=ebooks, 3030=audiobooks, 7020=comics.
        """
        if not categories:
            categories = "7010,3030,7020"

        combined_q = q
        if not combined_q:
            parts = [p for p in (author, title) if p]
            combined_q = " ".join(parts) if parts else None

        params = {"q": combined_q, "cat": categories}

        results = await self._search("search", params)
        if results:
            return results

        # Last-resort fallback: ask the indexer for its book function. Some
        # respect q here, the broken ones return latest-eBooks-feed which we
        # accept as worst-case (the matcher will drop irrelevant titles).
        try:
            return await self._search("book", params)
        except Exception:
            return []

    async def search_game(
        self,
        q: str | None = None,
        categories: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        """Search for game releases using Newznab general search.

        Newznab has no native t=game function, so we use t=search with
        PC game categories. Default: 4050 (PC Games), 1010-1110 (Console).
        """
        if not categories:
            categories = "4050,1010,1035,1080,1100,1110,1040,1050,1090"

        params = {
            "q": q,
            "cat": categories,
        }
        return await self._search("search", params)


    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        """
        Validate Newznab configuration by testing API connection.

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
            logger.info("Newznab config validation successful for %s", self.base_url)
            return {"valid": True, "errors": []}

        except IndexerError as e:
            logger.warning("Newznab config validation failed for %s: %s", self.base_url, e)
            errors.append(f"Connection failed: {str(e)}")
            return {"valid": False, "errors": errors}
        except Exception as e:
            logger.error("Newznab config validation error for %s: %s", self.base_url, e)
            errors.append(f"Unexpected error: {str(e)}")
            return {"valid": False, "errors": errors}


# Export plugin class for loader
PLUGIN_CLASS = Newznab
