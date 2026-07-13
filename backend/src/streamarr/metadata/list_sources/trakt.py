"""Trakt list source: charts, user lists, popular/trending/anticipated."""

from __future__ import annotations

import logging
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

# Trakt charts available without OAuth (only client_id header needed).
_CHART_ENDPOINTS = {
    "trending": "{type}s/trending",
    "popular": "{type}s/popular",
    "watched": "{type}s/watched/weekly",
    "collected": "{type}s/collected/weekly",
    "anticipated": "{type}s/anticipated",
    "boxoffice": "movies/boxoffice",  # movies only
}


class TraktListSource(ListSource):
    """Builders against the Trakt API.

    Config shapes:
      * ``{"mode": "chart", "chart": "trending"}``
      * ``{"mode": "list", "user": "<slug>", "list": "<list-slug-or-id>"}``
    """

    slug = "trakt"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = True
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["chart", "list"],
            "required": True,
        },
        "chart": {
            "type": "select",
            "options": sorted(_CHART_ENDPOINTS),
            "depends_on": {"mode": "chart"},
        },
        "user": {"type": "string", "depends_on": {"mode": "list"}},
        "list": {"type": "string", "depends_on": {"mode": "list"}},
    }

    BASE_URL = "https://api.trakt.tv"
    DEFAULT_LIMIT = 80

    def __init__(
        self,
        client_id: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not client_id:
            raise ListSourceError("Trakt list source requires a client_id.")
        self.client_id = client_id
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.BASE_URL}{path}",
                params=params or {},
                headers={
                    "Content-Type": "application/json",
                    "trakt-api-version": "2",
                    "trakt-api-key": self.client_id,
                },
            )

        response = await http_with_retries(
            do_request, max_retries=5, base_delay=1.0, log_label="trakt"
        )
        if response is None:
            raise ListSourceError(f"Trakt request exhausted retries: {path}")
        if response.status_code >= 400:
            raise ListSourceError(f"Trakt {path} returned {response.status_code}")
        return response.json()

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
            return await self._fetch_chart(config, media_type, limit)
        if mode == "list":
            return await self._fetch_user_list(config, media_type, limit)
        raise ListSourceError(f"Unknown Trakt mode {mode!r}")

    async def _fetch_chart(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        chart = config.get("chart")
        template = _CHART_ENDPOINTS.get(chart)
        if template is None:
            raise ListSourceError(f"Unknown Trakt chart {chart!r}")
        if chart == "boxoffice" and media_type is not ListSourceMediaType.MOVIE:
            raise ListSourceError("Trakt boxoffice chart is movies-only")
        type_token = "movie" if media_type is ListSourceMediaType.MOVIE else "show"
        path = "/" + template.format(type=type_token)

        rows = await self._get(path, {"limit": str(limit)})
        if not isinstance(rows, list):
            return []
        refs: list[ExternalRef] = []
        for row in rows[:limit]:
            ref = self._row_to_ref(row, media_type)
            if ref is not None:
                refs.append(ref)
        return refs

    async def _fetch_user_list(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        user = config.get("user")
        list_slug = config.get("list")
        if not user or not list_slug:
            raise ListSourceError(
                "Trakt list mode requires both 'user' and 'list'"
            )
        type_token = "movies" if media_type is ListSourceMediaType.MOVIE else "shows"
        path = f"/users/{user}/lists/{list_slug}/items/{type_token}"
        rows = await self._get(path, {"limit": str(limit)})
        if not isinstance(rows, list):
            return []
        refs: list[ExternalRef] = []
        for row in rows[:limit]:
            ref = self._row_to_ref(row, media_type)
            if ref is not None:
                refs.append(ref)
        return refs

    @staticmethod
    def _row_to_ref(
        row: dict, media_type: ListSourceMediaType
    ) -> ExternalRef | None:
        # Trakt rows wrap the actual item under "movie" / "show". Charts that
        # add extra metrics (watcher_count, etc.) keep those at the top level.
        key = "movie" if media_type is ListSourceMediaType.MOVIE else "show"
        item = row.get(key) or row
        ids = item.get("ids") or {}
        # Prefer TMDb id (matches streamarr's primary external provider), fall
        # back to IMDb / TVDB / Trakt slug so the resolver has *something*.
        if ids.get("tmdb"):
            provider, ext_id = "tmdb", str(ids["tmdb"])
        elif ids.get("imdb"):
            provider, ext_id = "imdb", str(ids["imdb"])
        elif ids.get("tvdb"):
            provider, ext_id = "tvdb", str(ids["tvdb"])
        elif ids.get("trakt"):
            provider, ext_id = "trakt", str(ids["trakt"])
        else:
            return None
        return ExternalRef(
            provider=provider,
            external_id=ext_id,
            media_type=media_type,
            title=item.get("title"),
            year=item.get("year"),
            extra={
                "trakt_ids": ids,
                "watcher_count": row.get("watcher_count"),
                "play_count": row.get("play_count"),
                "list_count": row.get("list_count"),
            },
        )
