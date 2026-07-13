"""IMDb list source: charts and user/curated lists.

IMDb has no public read API. Chart and list pages embed structured data
in a ``__NEXT_DATA__`` ``<script>`` tag (Next.js hydration payload) which
is much more reliable than CSS-selector scraping. We pluck IMDb IDs from
there.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx

from streamarr.metadata.list_sources.base import (
    ExternalRef,
    ListSource,
    ListSourceError,
    ListSourceMediaType,
)
from streamarr.utils.http import make_async_client
from streamarr.utils.retry import http_with_retries

logger = logging.getLogger(__name__)


_CHART_PATHS = {
    "top_movies": "/chart/top/",
    "popular_movies": "/chart/moviemeter/",
    "top_shows": "/chart/toptv/",
    "popular_shows": "/chart/tvmeter/",
    "lowest_rated": "/chart/bottom/",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__"[^>]*>(?P<payload>.*?)</script>',
    re.DOTALL,
)

_TT_RE = re.compile(r'"id"\s*:\s*"(tt\d{6,12})"')


class ImdbListSource(ListSource):
    """Builders against IMDb's public chart and list pages.

    Config shapes:
      * ``{"mode": "chart", "chart": "top_movies"}``
      * ``{"mode": "list", "list_id": "ls000071729"}``
        (any IMDb list id, including curated awards lists)
    """

    slug = "imdb"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = False
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["chart", "list"],
            "required": True,
        },
        "chart": {
            "type": "select",
            "options": sorted(_CHART_PATHS),
            "depends_on": {"mode": "chart"},
        },
        "list_id": {"type": "string", "depends_on": {"mode": "list"}},
    }

    BASE_URL = "https://www.imdb.com"
    DEFAULT_LIMIT = 250
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
                    "Accept-Language": "en-US,en;q=0.5",
                    "Accept": "text/html",
                },
            )

        response = await http_with_retries(
            do_request, max_retries=4, base_delay=2.0, log_label="imdb"
        )
        if response is None:
            raise ListSourceError(f"IMDb request exhausted retries: {path}")
        if response.status_code >= 400:
            raise ListSourceError(
                f"IMDb {path} returned {response.status_code}"
            )
        return response.text

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None = None,
    ) -> list[ExternalRef]:
        mode = config.get("mode")
        limit = limit or self.DEFAULT_LIMIT

        if mode == "chart":
            path = _CHART_PATHS.get(config.get("chart"))
            if path is None:
                raise ListSourceError(
                    f"Unknown IMDb chart {config.get('chart')!r}"
                )
        elif mode == "list":
            list_id = config.get("list_id")
            if not list_id:
                raise ListSourceError("IMDb list mode requires list_id")
            path = f"/list/{list_id}/"
        else:
            raise ListSourceError(f"Unknown IMDb mode {mode!r}")

        html = await self._get_html(path)
        ids = self._extract_tt_ids(html, limit)
        return [
            ExternalRef(
                provider="imdb",
                external_id=tt,
                media_type=media_type,
            )
            for tt in ids
        ]

    @staticmethod
    def _extract_tt_ids(html: str, limit: int) -> list[str]:
        # Prefer the Next.js hydration payload — it's stable JSON.
        match = _NEXT_DATA_RE.search(html)
        if match:
            try:
                payload = json.loads(match.group("payload"))
            except json.JSONDecodeError:
                payload = None
            ids = _walk_for_tt_ids(payload, limit) if payload else []
            if ids:
                return ids

        # Fallback: regex over the whole page (deduped, preserves order).
        seen: dict[str, None] = {}
        for match_obj in _TT_RE.finditer(html):
            seen.setdefault(match_obj.group(1), None)
            if len(seen) >= limit:
                break
        return list(seen)


def _walk_for_tt_ids(node: Any, limit: int) -> list[str]:
    """Walk a parsed JSON tree collecting IMDb ``tt`` ids in source order."""

    result: list[str] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if len(result) >= limit:
            return
        if isinstance(value, dict):
            # IMDb's hydration payload uses ``{"id": "tt0111161", ...}`` and
            # in newer responses ``{"const": "tt..."}`` for chart entries.
            candidate = value.get("id") or value.get("const")
            if (
                isinstance(candidate, str)
                and candidate.startswith("tt")
                and candidate[2:].isdigit()
                and candidate not in seen
            ):
                seen.add(candidate)
                result.append(candidate)
            for v in value.values():
                if len(result) >= limit:
                    return
                visit(v)
        elif isinstance(value, list):
            for v in value:
                if len(result) >= limit:
                    return
                visit(v)

    visit(node)
    return result
