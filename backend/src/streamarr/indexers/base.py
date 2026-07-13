"""Base class for release indexers (Newznab, Torznab) and shared error type."""

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

import httpx

from streamarr.utils.http import make_async_client
from streamarr.utils.net import UnsafeUrlError, assert_safe_url

logger = logging.getLogger(__name__)


class IndexerError(Exception):
    """Raised when an indexer call fails non-retryably (HTTP error, rate-limit,
    or exhausted retries). Subclassing the bare Exception keeps the public
    surface small; callers branch on the message string today."""


class IndexerBase(ABC):
    """Abstract base class for release indexers.

    Concrete subclasses (Newznab, Torznab) share the same Newznab/Torznab
    XML+JSON wire protocol, so the HTTP request loop, retry/backoff, and
    rate-limit handling all live here in ``_request``. Subclasses only need
    to set the per-instance config in ``__init__`` and implement the
    search_* methods.
    """

    base_url: str
    api_key: str
    client: httpx.AsyncClient
    max_retries: int
    retry_delay: int
    concurrent_requests: int
    id: str

    def _init_common(self, **kwargs: Any) -> None:
        """Populate the shared connection/retry attributes from kwargs.

        Called by concrete subclasses' ``__init__`` so each can keep its own
        ``id`` default while still sharing this configuration shape.
        """
        self.base_url = kwargs.get("base_url", "")
        self.api_key = kwargs.get("api_key", "")
        # Honour the indexer's verify_ssl config (self-signed / self-hosted
        # indexers) when we build the client ourselves. An explicitly supplied
        # client is used as-is.
        self.client = kwargs.get(
            "client",
            make_async_client(verify=kwargs.get("verify_ssl", True)),
        )
        self.max_retries = kwargs.get("max_retries", 3)
        self.retry_delay = kwargs.get("retry_delay", 2)
        self.concurrent_requests = kwargs.get("concurrent_requests", 5)

    async def _request(
        self,
        function: str,
        params: dict[str, Any] | None = None,
        base: str | None = "api",
    ) -> dict[str, Any]:
        """Call the indexer API with retries on transient failure.

        Retries on timeouts / connection errors (with linear ``retry_delay``).
        Bails out immediately on HTTP status errors — 429 raises a dedicated
        rate-limit message, other 4xx/5xx surface the upstream error so the
        caller can decide whether to blacklist the indexer.
        """
        filtered = {k: v for k, v in (params or {}).items() if v is not None}

        url = f"{self.base_url}/{base}"
        try:
            assert_safe_url(url)
        except UnsafeUrlError as exc:
            raise IndexerError(f"Refusing to contact unsafe indexer URL {self.base_url}: {exc}") from exc

        for attempt in range(1, self.max_retries + 1):
            try:
                response = await self.client.get(
                    url,
                    params={
                        "t": function,
                        "o": "json",
                        "apikey": self.api_key,
                        **filtered,
                    },
                )
                response.raise_for_status()
                return response.json()

            except httpx.TimeoutException:
                logger.warning(
                    "Request to %s timed out (attempt %d/%d)",
                    self.base_url, attempt, self.max_retries,
                )
            except httpx.HTTPStatusError as e:
                logger.error("HTTP error from %s: %s", self.base_url, e)
                if e.response.status_code == 429:
                    logger.warning("Rate limited by %s", self.base_url)
                    raise IndexerError(
                        f"Rate limited by {self.base_url}. Please wait before making more requests."
                    ) from e
                raise IndexerError(
                    f"HTTP error {e.response.status_code} from {self.base_url}: {e}"
                ) from e
            except httpx.RequestError as e:
                logger.error(
                    "Request error for %s: %s (attempt %d/%d)",
                    self.base_url, e, attempt, self.max_retries,
                )

            if attempt < self.max_retries:
                await asyncio.sleep(self.retry_delay)

        logger.error(
            "All %d attempts failed for %s function=%s",
            self.max_retries, self.base_url, function,
        )
        raise IndexerError(
            f"Failed to retrieve data from {self.base_url} after {self.max_retries} attempts."
        )

    @abstractmethod
    async def search_movie(
        self, q: str | None = None, imdb_id: str | None = None, **kwargs
    ) -> list[dict[str, Any]]: ...

    @abstractmethod
    async def search_show(
        self,
        q: str | None = None,
        tvdb_id: str | None = None,
        season: str | None = None,
        ep: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]: ...

    async def search_music(self, q: str | None = None, **kwargs) -> list[dict[str, Any]]:
        return []

    async def search_book(
        self,
        q: str | None = None,
        author: str | None = None,
        title: str | None = None,
        **kwargs,
    ) -> list[dict[str, Any]]:
        return []

    async def search_game(self, q: str | None = None, **kwargs) -> list[dict[str, Any]]:
        return []

    async def fetch_recent(self, *, limit: int = 100) -> list[dict[str, Any]]:
        """Latest/unfiltered feed for RSS sync. Indexers without a usable
        feed return an empty list (so they're simply skipped)."""
        return []

    async def close(self) -> None:
        if getattr(self, "client", None):
            await self.client.aclose()

    async def validate_config(self, config: dict[str, Any]) -> dict[str, Any]:
        return {"valid": True, "errors": []}
