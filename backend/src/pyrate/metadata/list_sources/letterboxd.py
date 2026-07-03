"""Letterboxd list source.

Letterboxd has no public API. List pages render each film as a
``<li class="poster-container" data-film-id="..">`` with a ``data-film-slug``
attribute. To map a slug onto an external id pyrate can resolve, we fetch
the film's page in a second pass and extract the TMDb id from its
``<a href="https://www.themoviedb.org/movie/..">`` link.

To keep the fan-out polite we cap concurrency and the maximum films per
fetch. For very large lists, use the ``page_limit`` config knob.
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import Any

import httpx

from pyrate.metadata.list_sources.base import (
    ExternalRef,
    ListSource,
    ListSourceError,
    ListSourceMediaType,
)
from pyrate.utils.http import make_async_client
from pyrate.utils.retry import http_with_retries

logger = logging.getLogger(__name__)


_SLUG_RE = re.compile(
    r'data-film-slug="(?P<slug>[^"]+)"'
    r'(?=(?:[^>]*data-film-name="(?P<name>[^"]*)")|[^>]*>)'
    r'(?=(?:[^>]*data-film-release-year="(?P<year>\d{4})")|[^>]*>)'
    r'[^>]*',
    re.DOTALL,
)

_TMDB_RE = re.compile(
    r'https?://www\.themoviedb\.org/(?:movie|tv)/(?P<id>\d+)'
)
_IMDB_RE = re.compile(r'https?://www\.imdb\.com/title/(?P<id>tt\d+)')


class LetterboxdListSource(ListSource):
    """Builders against Letterboxd user/curated lists.

    Config shapes:
      * ``{"mode": "user_list", "user": "<slug>", "list": "<list-slug>"}``
      * ``{"mode": "user_films", "user": "<slug>"}`` (a user's watched films)
      * ``{"mode": "popular_this_week"}`` (curated)

    Optional knobs (any mode):
      * ``page_limit``: hard cap on list pages walked (default 4 ≈ 100 films)
      * ``concurrency``: parallel film-page lookups (default 5, max 10)
    """

    slug = "letterboxd"
    supported_media_types = frozenset({ListSourceMediaType.MOVIE})
    requires_api_key = False
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["user_list", "user_films", "popular_this_week"],
            "required": True,
        },
        "user": {"type": "string", "depends_on": {"mode": "user_list"}},
        "list": {"type": "string", "depends_on": {"mode": "user_list"}},
        "page_limit": {"type": "integer", "default": 4},
        "concurrency": {"type": "integer", "default": 5},
    }

    BASE_URL = "https://letterboxd.com"
    DEFAULT_LIMIT = 100
    _USER_AGENT = (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get_html(self, path: str) -> str:
        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.BASE_URL}{path}",
                headers={
                    "User-Agent": self._USER_AGENT,
                    "Accept": "text/html",
                    "Accept-Language": "en-US,en;q=0.5",
                },
            )

        response = await http_with_retries(
            do_request, max_retries=4, base_delay=2.0, log_label="letterboxd"
        )
        if response is None:
            raise ListSourceError(
                f"Letterboxd request exhausted retries: {path}"
            )
        if response.status_code == 404:
            raise ListSourceError(f"Letterboxd {path} not found")
        if response.status_code >= 400:
            raise ListSourceError(
                f"Letterboxd {path} returned {response.status_code}"
            )
        return response.text

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None = None,
    ) -> list[ExternalRef]:
        if media_type is not ListSourceMediaType.MOVIE:
            raise ListSourceError(
                "Letterboxd only supports movies"
            )

        mode = config.get("mode")
        if mode == "user_list":
            user = config.get("user")
            list_slug = config.get("list")
            if not user or not list_slug:
                raise ListSourceError(
                    "Letterboxd user_list mode requires user and list"
                )
            base_path = f"/{user}/list/{list_slug}/"
        elif mode == "user_films":
            user = config.get("user")
            if not user:
                raise ListSourceError(
                    "Letterboxd user_films mode requires user"
                )
            base_path = f"/{user}/films/"
        elif mode == "popular_this_week":
            base_path = "/films/popular/this/week/"
        else:
            raise ListSourceError(f"Unknown Letterboxd mode {mode!r}")

        limit = limit or self.DEFAULT_LIMIT
        page_limit = max(1, int(config.get("page_limit") or 4))
        concurrency = max(1, min(10, int(config.get("concurrency") or 5)))

        slugs = await self._collect_slugs(base_path, page_limit, limit)
        refs = await self._resolve_to_refs(slugs, concurrency)
        return refs[:limit]

    async def _collect_slugs(
        self, base_path: str, page_limit: int, limit: int
    ) -> list[tuple[str, str | None, int | None]]:
        """Walk paginated list pages collecting (slug, name, year) triples."""
        seen: dict[str, tuple[str | None, int | None]] = {}
        for page in range(1, page_limit + 1):
            path = base_path if page == 1 else f"{base_path}page/{page}/"
            try:
                html = await self._get_html(path)
            except ListSourceError as exc:
                logger.info("letterboxd page %d stopped: %s", page, exc)
                break
            new = 0
            for match in _SLUG_RE.finditer(html):
                slug = match.group("slug")
                if slug in seen:
                    continue
                name = match.group("name")
                year_raw = match.group("year")
                year = int(year_raw) if year_raw else None
                seen[slug] = (name, year)
                new += 1
                if len(seen) >= limit:
                    break
            if new == 0 or len(seen) >= limit:
                break
        return [(slug, n, y) for slug, (n, y) in seen.items()]

    async def _resolve_to_refs(
        self,
        slugs: list[tuple[str, str | None, int | None]],
        concurrency: int,
    ) -> list[ExternalRef]:
        sem = asyncio.Semaphore(concurrency)

        async def worker(
            slug: str, name: str | None, year: int | None
        ) -> ExternalRef | None:
            async with sem:
                try:
                    html = await self._get_html(f"/film/{slug}/")
                except ListSourceError as exc:
                    logger.info("letterboxd film %s failed: %s", slug, exc)
                    return None
            tmdb_match = _TMDB_RE.search(html)
            if tmdb_match:
                return ExternalRef(
                    provider="tmdb",
                    external_id=tmdb_match.group("id"),
                    media_type=ListSourceMediaType.MOVIE,
                    title=name,
                    year=year,
                    extra={"letterboxd_slug": slug},
                )
            imdb_match = _IMDB_RE.search(html)
            if imdb_match:
                return ExternalRef(
                    provider="imdb",
                    external_id=imdb_match.group("id"),
                    media_type=ListSourceMediaType.MOVIE,
                    title=name,
                    year=year,
                    extra={"letterboxd_slug": slug},
                )
            return None

        results = await asyncio.gather(
            *(worker(slug, name, year) for slug, name, year in slugs)
        )
        return [ref for ref in results if ref is not None]
