"""Open Library metadata provider for books and audiobooks.

Uses the Open Library API (openlibrary.org) — free, no auth required.
Rate limit: ~3 req/s with User-Agent header. We self-throttle below that
and back off honourably on 429 responses so a bulk import doesn't fill
the worker logs with errors.
"""

import asyncio
import logging
import time
from typing import Any

import httpx

from streamarr.metadata.base import MetadataBase, NormalizedMetadata

logger = logging.getLogger(__name__)

BASE_URL = "https://openlibrary.org"
COVERS_URL = "https://covers.openlibrary.org"
USER_AGENT = "streamarr.media/1.0 (https://streamarr.media)"

# Self-throttling. Open Library publishes a soft limit of ~3 req/s; stay
# comfortably under it so concurrent bulk-imports across worker replicas
# don't add up to a 429 storm. Token-bucket-style: at most one request
# every ``_MIN_INTERVAL_SECONDS`` per process, serialised by a lock.
_MIN_INTERVAL_SECONDS = 0.4
_RETRY_MAX_ATTEMPTS = 3
_RETRY_DEFAULT_BACKOFF_SECONDS = 5.0
_throttle_lock = asyncio.Lock()
_last_request_at = 0.0


async def _throttle() -> None:
    """Block until at least ``_MIN_INTERVAL_SECONDS`` has elapsed since last call."""
    global _last_request_at
    async with _throttle_lock:
        now = time.monotonic()
        wait = _MIN_INTERVAL_SECONDS - (now - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


def _parse_retry_after(value: str | None) -> float:
    """Parse ``Retry-After`` (seconds form). Returns the default backoff on
    parse error or non-numeric/HTTP-date values — we don't bother with
    HTTP-date parsing since Open Library only sends seconds.
    """
    if not value:
        return _RETRY_DEFAULT_BACKOFF_SECONDS
    try:
        return max(0.0, float(value))
    except (ValueError, TypeError):
        return _RETRY_DEFAULT_BACKOFF_SECONDS


class OpenLibrary(MetadataBase):
    """Open Library metadata provider."""

    def __init__(self, **kwargs):
        self.client = httpx.AsyncClient(
            base_url=BASE_URL,
            headers={"User-Agent": USER_AGENT},
            timeout=httpx.Timeout(connect=3.0, read=5.0, write=5.0, pool=5.0),
        )

    async def _get_json(
        self, url: str, *, params: dict[str, Any] | None = None
    ) -> dict[str, Any] | None:
        """Throttled, 429-aware GET → JSON helper.

        Returns the parsed body on 2xx, ``None`` on persistent failure
        (so callers can return their own empty default). 429s are retried
        with the server's Retry-After hint — only the final failure is
        logged at WARNING; per-attempt 429s stay at DEBUG to keep worker
        logs readable during bulk imports.
        """
        last_exc: Exception | None = None
        for attempt in range(_RETRY_MAX_ATTEMPTS):
            await _throttle()
            try:
                resp = await self.client.get(url, params=params)
                if resp.status_code == 429:
                    backoff = _parse_retry_after(resp.headers.get("Retry-After"))
                    logger.debug(
                        "Open Library 429 on %s (attempt %d/%d) — sleeping %.1fs",
                        url, attempt + 1, _RETRY_MAX_ATTEMPTS, backoff,
                    )
                    await asyncio.sleep(backoff)
                    continue
                resp.raise_for_status()
                return resp.json()
            except httpx.HTTPStatusError as e:
                # Non-429 4xx: don't retry — this is a deterministic miss
                # (404 work id, etc.). Caller logs at the appropriate level.
                last_exc = e
                if e.response is not None and e.response.status_code < 500:
                    return None
            except Exception as e:
                last_exc = e
                # Transient — fall through to retry loop with a small wait.
                await asyncio.sleep(0.5 * (attempt + 1))

        if last_exc is not None:
            logger.warning(
                "Open Library request to %s failed after %d attempts: %s",
                url, _RETRY_MAX_ATTEMPTS, last_exc,
            )
        return None

    async def search(self, query: str, **kwargs) -> list[dict[str, Any]]:
        """Search for books by title, author, or ISBN."""
        params: dict[str, Any] = {"limit": kwargs.get("limit", 20)}

        if kwargs.get("isbn"):
            params["isbn"] = kwargs["isbn"]
        elif kwargs.get("author") and kwargs.get("title"):
            params["author"] = kwargs["author"]
            params["title"] = kwargs["title"]
        else:
            params["q"] = query

        params["fields"] = ",".join([
            "key", "title", "author_name", "author_key",
            "first_publish_year", "isbn", "cover_i",
            "number_of_pages_median", "language", "subject",
            "edition_count", "ebook_access",
        ])

        data = await self._get_json("/search.json", params=params)
        if data is None:
            return []

        results = []
        for doc in data.get("docs", []):
            work_id = doc.get("key", "").replace("/works/", "")
            cover_id = doc.get("cover_i")
            isbn_list = doc.get("isbn", [])

            results.append({
                "id": work_id,
                "title": doc.get("title"),
                "authors": doc.get("author_name", []),
                "author_keys": doc.get("author_key", []),
                "year": doc.get("first_publish_year"),
                "isbn": isbn_list[0] if isbn_list else None,
                "isbns": isbn_list[:5],
                "cover_url": f"{COVERS_URL}/b/id/{cover_id}-L.jpg" if cover_id else None,
                "pages": doc.get("number_of_pages_median"),
                "subjects": (doc.get("subject") or [])[:10],
                "edition_count": doc.get("edition_count", 0),
                "provider": "openlibrary",
            })

        return results

    async def get_details(self, media_id: str | int, **kwargs) -> dict[str, Any]:
        """Get book details by Open Library work ID (e.g. 'OL45883W')."""
        work_id = str(media_id)
        if not work_id.startswith("OL"):
            work_id = f"OL{work_id}W"

        work = await self._get_json(f"/works/{work_id}.json")
        if work is None:
            return {}

        # Get author details
        authors = []
        for author_ref in work.get("authors", []):
            author_key = author_ref.get("author", {}).get("key", "")
            if not author_key:
                continue
            author_data = await self._get_json(f"{author_key}.json")
            if author_data:
                authors.append({
                    "name": author_data.get("name"),
                    "key": author_key.replace("/authors/", ""),
                    "photo_url": f"{COVERS_URL}/a/olid/{author_key.replace('/authors/', '')}-L.jpg",
                })

        # Extract cover
        covers = work.get("covers", [])
        cover_url = f"{COVERS_URL}/b/id/{covers[0]}-L.jpg" if covers else None

        # Description
        description = work.get("description")
        if isinstance(description, dict):
            description = description.get("value", "")

        # Subjects
        subjects = work.get("subjects", [])[:20]

        return {
            "id": work_id,
            "title": work.get("title"),
            "description": description,
            "authors": authors,
            "cover_url": cover_url,
            "subjects": subjects,
            "first_publish_date": work.get("first_publish_date"),
            "provider": "openlibrary",
        }

    async def get_normalized_details(
        self, media_id: str | int, media_type: str = "book", **kwargs
    ) -> NormalizedMetadata:
        raw = await self.get_details(media_id, **kwargs)
        if not raw:
            return NormalizedMetadata()

        author_names = [a["name"] for a in raw.get("authors", []) if a.get("name")]

        return NormalizedMetadata(
            title=raw.get("title"),
            description=raw.get("description"),
            poster_path=raw.get("cover_url"),
            release_date=raw.get("first_publish_date"),
            credits={"authors": raw.get("authors", [])},
            extra={
                "subjects": raw.get("subjects", []),
                "author_names": author_names,
            },
        )

    async def search_author(self, query: str, limit: int = 10) -> list[dict[str, Any]]:
        """Search for authors."""
        data = await self._get_json(
            "/search/authors.json", params={"q": query, "limit": limit}
        )
        if data is None:
            return []

        return [
            {
                "id": doc.get("key", "").replace("/authors/", ""),
                "name": doc.get("name"),
                "work_count": doc.get("work_count", 0),
                "top_subjects": doc.get("top_subjects", [])[:5],
                "photo_url": f"{COVERS_URL}/a/olid/{doc.get('key', '').replace('/authors/', '')}-L.jpg",
                "provider": "openlibrary",
            }
            for doc in data.get("docs", [])
        ]

    async def get_author_works(self, author_id: str, limit: int = 50) -> list[dict[str, Any]]:
        """Get works by an author."""
        data = await self._get_json(
            f"/authors/{author_id}/works.json", params={"limit": limit}
        )
        if data is None:
            return []

        works = []
        for entry in data.get("entries", []):
            work_key = entry.get("key", "").replace("/works/", "")
            covers = entry.get("covers", [])
            works.append({
                "id": work_key,
                "title": entry.get("title"),
                "cover_url": f"{COVERS_URL}/b/id/{covers[0]}-L.jpg" if covers else None,
                "provider": "openlibrary",
            })

        return works

    async def get_editions(self, work_id: str, limit: int = 10) -> list[dict[str, Any]]:
        """Get editions of a work (for ISBN lookup)."""
        data = await self._get_json(
            f"/works/{work_id}/editions.json", params={"limit": limit}
        )
        if data is None:
            return []

        editions = []
        for entry in data.get("entries", []):
            isbn_13 = entry.get("isbn_13", [])
            isbn_10 = entry.get("isbn_10", [])
            covers = entry.get("covers", [])
            editions.append({
                "key": entry.get("key", "").replace("/books/", ""),
                "title": entry.get("title"),
                "isbn_13": isbn_13[0] if isbn_13 else None,
                "isbn_10": isbn_10[0] if isbn_10 else None,
                "publishers": entry.get("publishers", []),
                "publish_date": entry.get("publish_date"),
                "number_of_pages": entry.get("number_of_pages"),
                "physical_format": entry.get("physical_format"),
                "cover_url": f"{COVERS_URL}/b/id/{covers[0]}-L.jpg" if covers else None,
            })

        return editions

    async def close(self) -> None:
        if self.client:
            await self.client.aclose()
