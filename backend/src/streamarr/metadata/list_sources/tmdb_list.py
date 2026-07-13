"""TMDb list source: charts, discover, network/keyword/collection lookups."""

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


# Charts available without authentication beyond an API key.
_MOVIE_CHARTS = {
    "popular": "movie/popular",
    "top_rated": "movie/top_rated",
    "now_playing": "movie/now_playing",
    "upcoming": "movie/upcoming",
    "trending_day": "trending/movie/day",
    "trending_week": "trending/movie/week",
}

_SHOW_CHARTS = {
    "popular": "tv/popular",
    "top_rated": "tv/top_rated",
    "airing_today": "tv/airing_today",
    "on_the_air": "tv/on_the_air",
    "trending_day": "trending/tv/day",
    "trending_week": "trending/tv/week",
}


class TmdbListSource(ListSource):
    """Builders against TMDb's REST API.

    Supported ``config`` shapes:

      * ``{"mode": "chart", "chart": "popular"}``
      * ``{"mode": "discover", "params": {"with_genres": "28", ...}}``
        (any param TMDb's /discover endpoints accept is passed through)
      * ``{"mode": "collection", "collection_id": 10}``
      * ``{"mode": "keyword", "keyword_id": 9715}``
      * ``{"mode": "company", "company_id": 420}``
      * ``{"mode": "network", "network_id": 213}``  (shows only)

    Pagination: TMDb returns 20 per page; we walk pages until ``limit`` or
    the end-of-data is reached. ``limit=None`` defaults to 80.
    """

    slug = "tmdb"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = True
    config_schema = {
        "mode": {
            "type": "select",
            "label": "Mode",
            "options": [
                "chart",
                "discover",
                "collection",
                "keyword",
                "company",
                "network",
            ],
            "required": True,
        },
        "chart": {
            "type": "select",
            "label": "Chart",
            "options": sorted(set(_MOVIE_CHARTS) | set(_SHOW_CHARTS)),
            "depends_on": {"mode": "chart"},
        },
        "params": {
            "type": "json",
            "label": "Discover Params",
            "depends_on": {"mode": "discover"},
        },
        "collection_id": {
            "type": "integer",
            "depends_on": {"mode": "collection"},
        },
        "keyword_id": {
            "type": "integer",
            "depends_on": {"mode": "keyword"},
        },
        "company_id": {
            "type": "integer",
            "depends_on": {"mode": "company"},
        },
        "network_id": {
            "type": "integer",
            "depends_on": {"mode": "network"},
        },
    }

    DEFAULT_LIMIT = 80
    BASE_URL = "https://api.themoviedb.org/3"

    def __init__(
        self,
        api_key: str,
        *,
        language: str = "de-DE",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ListSourceError("TMDb list source requires an API key.")
        self.api_key = api_key
        self.language = language
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, endpoint: str, params: dict | None = None) -> dict:
        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.BASE_URL}/{endpoint}",
                params={"language": self.language, **(params or {})},
                headers={"Authorization": f"Bearer {self.api_key}"},
            )

        response = await http_with_retries(
            do_request, max_retries=5, base_delay=1.0, log_label="tmdb-list"
        )
        if response is None:
            raise ListSourceError(
                f"TMDb request exhausted retries: {endpoint}"
            )
        if response.status_code >= 400:
            raise ListSourceError(
                f"TMDb {endpoint} returned {response.status_code}"
            )
        return response.json()

    async def fetch(
        self,
        config: dict[str, Any],
        *,
        media_type: ListSourceMediaType,
        limit: int | None = None,
    ) -> list[ExternalRef]:
        if media_type not in self.supported_media_types:
            raise ListSourceError(
                f"TMDb list source does not support media_type {media_type}"
            )

        mode = config.get("mode")
        limit = limit or self.DEFAULT_LIMIT

        if mode == "chart":
            return await self._fetch_chart(config, media_type, limit)
        if mode == "discover":
            return await self._fetch_discover(config, media_type, limit)
        if mode == "collection":
            return await self._fetch_collection(config, media_type, limit)
        if mode in {"keyword", "company"}:
            return await self._fetch_discover_with_id(
                config, media_type, mode, limit
            )
        if mode == "network":
            if media_type is not ListSourceMediaType.SHOW:
                raise ListSourceError(
                    "TMDb network mode is shows-only"
                )
            return await self._fetch_discover_with_id(
                config, media_type, mode, limit
            )

        raise ListSourceError(f"Unknown TMDb list mode: {mode!r}")

    async def _fetch_chart(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        chart = config.get("chart")
        table = (
            _MOVIE_CHARTS
            if media_type is ListSourceMediaType.MOVIE
            else _SHOW_CHARTS
        )
        endpoint = table.get(chart)
        if endpoint is None:
            raise ListSourceError(
                f"Unknown TMDb chart {chart!r} for {media_type}"
            )
        return await self._paginate(endpoint, {}, media_type, limit)

    async def _fetch_discover(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        endpoint = (
            "discover/movie"
            if media_type is ListSourceMediaType.MOVIE
            else "discover/tv"
        )
        params = dict(config.get("params") or {})
        return await self._paginate(endpoint, params, media_type, limit)

    async def _fetch_discover_with_id(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        mode: str,
        limit: int,
    ) -> list[ExternalRef]:
        # Map mode → discover param.
        param_key = {
            "keyword": "with_keywords",
            "company": "with_companies",
            "network": "with_networks",
        }[mode]
        id_key = f"{mode}_id"
        target_id = config.get(id_key)
        if target_id is None:
            raise ListSourceError(
                f"TMDb {mode} mode requires {id_key} in config"
            )
        endpoint = (
            "discover/movie"
            if media_type is ListSourceMediaType.MOVIE
            else "discover/tv"
        )
        return await self._paginate(
            endpoint, {param_key: str(target_id)}, media_type, limit
        )

    async def _fetch_collection(
        self,
        config: dict[str, Any],
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        if media_type is not ListSourceMediaType.MOVIE:
            raise ListSourceError("TMDb collections are movies-only")
        collection_id = config.get("collection_id")
        if collection_id is None:
            raise ListSourceError(
                "TMDb collection mode requires collection_id"
            )
        data = await self._get(f"collection/{collection_id}")
        parts = data.get("parts", []) or []
        refs = [self._row_to_ref(row, media_type) for row in parts]
        return [r for r in refs if r is not None][:limit]

    async def _paginate(
        self,
        endpoint: str,
        params: dict,
        media_type: ListSourceMediaType,
        limit: int,
    ) -> list[ExternalRef]:
        refs: list[ExternalRef] = []
        page = 1
        while len(refs) < limit:
            data = await self._get(endpoint, {**params, "page": page})
            results = data.get("results") or []
            if not results:
                break
            for row in results:
                ref = self._row_to_ref(row, media_type)
                if ref is None:
                    continue
                refs.append(ref)
                if len(refs) >= limit:
                    break
            total_pages = data.get("total_pages") or 1
            if page >= total_pages:
                break
            page += 1
        return refs

    @staticmethod
    def _row_to_ref(
        row: dict, media_type: ListSourceMediaType
    ) -> ExternalRef | None:
        tmdb_id = row.get("id")
        if tmdb_id is None:
            return None
        title = row.get("title") or row.get("name") or row.get("original_name")
        date = row.get("release_date") or row.get("first_air_date") or ""
        year: int | None = None
        if date and len(date) >= 4 and date[:4].isdigit():
            year = int(date[:4])
        return ExternalRef(
            provider="tmdb",
            external_id=str(tmdb_id),
            media_type=media_type,
            title=title,
            year=year,
            extra={
                "vote_average": row.get("vote_average"),
                "vote_count": row.get("vote_count"),
                "popularity": row.get("popularity"),
                "original_language": row.get("original_language"),
                "genre_ids": row.get("genre_ids"),
            },
        )
