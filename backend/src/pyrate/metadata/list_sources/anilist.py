"""AniList list source: anime charts via the public GraphQL endpoint.

AniList's GraphQL API is keyless for read queries. We expose two modes:
``chart`` (popular/trending/top_rated by year+season) and ``staff_search``
(items linked to a studio/staff id).

Anime returned by AniList carries MAL ids in the ``idMal`` field; we map
those onto ``provider="mal"`` so the resolver can use whichever id pyrate
already stores for the item. Falls back to ``provider="anilist"``.
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


_CHART_SORTS = {
    "trending": "TRENDING_DESC",
    "popular": "POPULARITY_DESC",
    "top_rated": "SCORE_DESC",
    "favourites": "FAVOURITES_DESC",
}

_BASE_QUERY = """
query ($page: Int, $perPage: Int, $sort: [MediaSort], $type: MediaType,
       $season: MediaSeason, $seasonYear: Int, $studio: Int) {
  Page(page: $page, perPage: $perPage) {
    pageInfo { hasNextPage }
    media(sort: $sort, type: $type, season: $season,
          seasonYear: $seasonYear, studio_id: $studio,
          isAdult: false) {
      id
      idMal
      title { romaji english native }
      startDate { year }
      averageScore
      popularity
      genres
    }
  }
}
"""


class AnilistListSource(ListSource):
    """AniList charts via GraphQL.

    Config shapes:
      * ``{"mode": "chart", "chart": "trending"}``
      * ``{"mode": "chart", "chart": "popular", "year": 2024, "season": "WINTER"}``
      * ``{"mode": "chart", "chart": "top_rated", "studio_id": 6}``

    For shows (TV anime) only — AniList movies map onto ListSourceMediaType.MOVIE.
    """

    slug = "anilist"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = False
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["chart"],
            "required": True,
            "default": "chart",
        },
        "chart": {
            "type": "select",
            "options": sorted(_CHART_SORTS),
            "required": True,
        },
        "year": {"type": "integer"},
        "season": {
            "type": "select",
            "options": ["WINTER", "SPRING", "SUMMER", "FALL"],
        },
        "studio_id": {"type": "integer"},
    }

    BASE_URL = "https://graphql.anilist.co"
    PER_PAGE = 50
    DEFAULT_LIMIT = 80

    def __init__(self, *, client: httpx.AsyncClient | None = None) -> None:
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _post(self, payload: dict) -> Any:
        async def do_request() -> httpx.Response:
            return await self.client.post(
                self.BASE_URL,
                json=payload,
                headers={"Accept": "application/json"},
            )

        response = await http_with_retries(
            do_request, max_retries=4, base_delay=1.5, log_label="anilist"
        )
        if response is None:
            raise ListSourceError("AniList request exhausted retries")
        if response.status_code >= 400:
            raise ListSourceError(
                f"AniList returned {response.status_code}"
            )
        body = response.json()
        if body.get("errors"):
            raise ListSourceError(
                f"AniList GraphQL errors: {body['errors']}"
            )
        return body.get("data") or {}

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None = None,
    ) -> list[ExternalRef]:
        mode = config.get("mode", "chart")
        if mode != "chart":
            raise ListSourceError(f"AniList: unknown mode {mode!r}")

        sort = _CHART_SORTS.get(config.get("chart"))
        if sort is None:
            raise ListSourceError(
                f"AniList: unknown chart {config.get('chart')!r}"
            )

        limit = limit or self.DEFAULT_LIMIT
        type_token = (
            "MOVIE" if media_type is ListSourceMediaType.MOVIE else "TV"
        )

        refs: list[ExternalRef] = []
        page = 1
        while len(refs) < limit:
            variables = {
                "page": page,
                "perPage": min(self.PER_PAGE, limit - len(refs)),
                "sort": [sort],
                "type": type_token,
                "season": config.get("season"),
                "seasonYear": config.get("year"),
                "studio": config.get("studio_id"),
            }
            data = await self._post(
                {"query": _BASE_QUERY, "variables": variables}
            )
            page_obj = data.get("Page") or {}
            for row in page_obj.get("media") or []:
                ref = self._row_to_ref(row, media_type)
                if ref is not None:
                    refs.append(ref)
                if len(refs) >= limit:
                    break
            if not (page_obj.get("pageInfo") or {}).get("hasNextPage"):
                break
            page += 1
        return refs

    @staticmethod
    def _row_to_ref(
        row: dict, media_type: ListSourceMediaType
    ) -> ExternalRef | None:
        if row.get("idMal"):
            provider, ext_id = "mal", str(row["idMal"])
        elif row.get("id"):
            provider, ext_id = "anilist", str(row["id"])
        else:
            return None
        title = row.get("title") or {}
        return ExternalRef(
            provider=provider,
            external_id=ext_id,
            media_type=media_type,
            title=title.get("english") or title.get("romaji"),
            year=(row.get("startDate") or {}).get("year"),
            extra={
                "anilist_id": row.get("id"),
                "score": row.get("averageScore"),
                "popularity": row.get("popularity"),
                "genres": row.get("genres"),
            },
        )
