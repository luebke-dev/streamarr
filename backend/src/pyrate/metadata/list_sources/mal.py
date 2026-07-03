"""MyAnimeList list source via the public Jikan REST API.

Jikan proxies MAL's data and requires no key. The official MAL API needs
an OAuth flow we don't want to push onto admins, so we stick with Jikan
for read-only chart access.
"""

from __future__ import annotations

import logging
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


# Jikan top filters map to MAL's "top" rankings. ``type`` is added at
# fetch-time from media_type.
_TOP_FILTERS = {
    "airing": "airing",
    "upcoming": "upcoming",
    "bypopularity": "bypopularity",
    "favorite": "favorite",
    "rated": None,  # No filter → ranked by score
}


class MalListSource(ListSource):
    """Builders against the Jikan REST API (MyAnimeList proxy).

    Config shapes:
      * ``{"mode": "top", "filter": "bypopularity"}``
      * ``{"mode": "season", "year": 2024, "season": "winter"}``
      * ``{"mode": "genre", "genre_id": 1}``
    """

    slug = "mal"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = False
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["top", "season", "genre"],
            "required": True,
        },
        "filter": {
            "type": "select",
            "options": sorted(_TOP_FILTERS),
            "depends_on": {"mode": "top"},
        },
        "year": {"type": "integer", "depends_on": {"mode": "season"}},
        "season": {
            "type": "select",
            "options": ["winter", "spring", "summer", "fall"],
            "depends_on": {"mode": "season"},
        },
        "genre_id": {"type": "integer", "depends_on": {"mode": "genre"}},
    }

    BASE_URL = "https://api.jikan.moe/v4"
    PER_PAGE = 25
    DEFAULT_LIMIT = 50

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> dict:
        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.BASE_URL}{path}", params=params or {}
            )

        response = await http_with_retries(
            do_request, max_retries=4, base_delay=1.5, log_label="jikan"
        )
        if response is None:
            raise ListSourceError(f"Jikan request exhausted retries: {path}")
        if response.status_code >= 400:
            raise ListSourceError(
                f"Jikan {path} returned {response.status_code}"
            )
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
        type_token = (
            "movie" if media_type is ListSourceMediaType.MOVIE else "tv"
        )

        params: dict[str, Any] = {"type": type_token, "limit": self.PER_PAGE}
        if mode == "top":
            filter_value = _TOP_FILTERS.get(config.get("filter") or "rated")
            if filter_value:
                params["filter"] = filter_value
            path = "/top/anime"
        elif mode == "season":
            year = config.get("year")
            season = (config.get("season") or "").lower()
            if not year or season not in {"winter", "spring", "summer", "fall"}:
                raise ListSourceError(
                    "MAL season mode requires year and a valid season"
                )
            path = f"/seasons/{year}/{season}"
        elif mode == "genre":
            genre_id = config.get("genre_id")
            if not genre_id:
                raise ListSourceError("MAL genre mode requires genre_id")
            params["genres"] = str(genre_id)
            params["order_by"] = "score"
            params["sort"] = "desc"
            path = "/anime"
        else:
            raise ListSourceError(f"Unknown MAL mode {mode!r}")

        refs: list[ExternalRef] = []
        page = 1
        while len(refs) < limit:
            data = await self._get(path, {**params, "page": page})
            rows = data.get("data") or []
            if not rows:
                break
            for row in rows:
                ref = self._row_to_ref(row, media_type)
                if ref is not None:
                    refs.append(ref)
                if len(refs) >= limit:
                    break
            pagination = data.get("pagination") or {}
            if not pagination.get("has_next_page"):
                break
            page += 1
        return refs

    @staticmethod
    def _row_to_ref(
        row: dict, media_type: ListSourceMediaType
    ) -> ExternalRef | None:
        mal_id = row.get("mal_id")
        if not mal_id:
            return None
        aired = row.get("aired") or {}
        from_str = aired.get("from") or ""
        year: int | None = None
        if from_str and len(from_str) >= 4 and from_str[:4].isdigit():
            year = int(from_str[:4])
        return ExternalRef(
            provider="mal",
            external_id=str(mal_id),
            media_type=media_type,
            title=row.get("title_english") or row.get("title"),
            year=year,
            extra={
                "score": row.get("score"),
                "rank": row.get("rank"),
                "popularity": row.get("popularity"),
                "genres": [g.get("name") for g in row.get("genres") or []],
            },
        )
