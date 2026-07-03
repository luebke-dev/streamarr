"""MDBList list source: aggregated curated lists keyed by ``listspec``.

MDBList exposes user-curated and trending lists via a JSON API. The most
useful endpoint for smart collections is ``/lists/{user}/{listname}/items``
which returns a flat array of items with IMDb/TMDb/TVDB IDs.
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


class MdblistListSource(ListSource):
    """Builders against the public MDBList API.

    Config shapes:
      * ``{"mode": "user_list", "user": "<slug>", "list": "<list-slug>"}``
      * ``{"mode": "top_lists", "category": "movie"}``  (returns refs from
        the curated "top lists" rotation; convenient for defaults)
    """

    slug = "mdblist"
    supported_media_types = frozenset(
        {ListSourceMediaType.MOVIE, ListSourceMediaType.SHOW}
    )
    requires_api_key = True
    config_schema = {
        "mode": {
            "type": "select",
            "options": ["user_list", "top_lists"],
            "required": True,
        },
        "user": {"type": "string", "depends_on": {"mode": "user_list"}},
        "list": {"type": "string", "depends_on": {"mode": "user_list"}},
        "category": {
            "type": "select",
            "options": ["movie", "show"],
            "depends_on": {"mode": "top_lists"},
        },
    }

    BASE_URL = "https://api.mdblist.com"
    DEFAULT_LIMIT = 100

    def __init__(
        self,
        api_key: str,
        *,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise ListSourceError("MDBList list source requires an API key.")
        self.api_key = api_key
        self.client = client or make_async_client(base_url=self.BASE_URL)
        self._owns_client = client is None

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def _get(self, path: str, params: dict | None = None) -> Any:
        merged = {"apikey": self.api_key, **(params or {})}

        async def do_request() -> httpx.Response:
            return await self.client.get(
                f"{self.BASE_URL}{path}", params=merged
            )

        response = await http_with_retries(
            do_request, max_retries=4, base_delay=1.0, log_label="mdblist"
        )
        if response is None:
            raise ListSourceError(
                f"MDBList request exhausted retries: {path}"
            )
        if response.status_code >= 400:
            raise ListSourceError(
                f"MDBList {path} returned {response.status_code}"
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
        if mode == "user_list":
            user = config.get("user")
            slug = config.get("list")
            if not user or not slug:
                raise ListSourceError(
                    "MDBList user_list mode requires user and list"
                )
            data = await self._get(f"/lists/{user}/{slug}/items")
        elif mode == "top_lists":
            data = await self._get("/lists/top")
        else:
            raise ListSourceError(f"Unknown MDBList mode {mode!r}")

        rows = self._extract_rows(data, media_type)
        refs: list[ExternalRef] = []
        for row in rows:
            ref = self._row_to_ref(row, media_type)
            if ref is None:
                continue
            refs.append(ref)
            if len(refs) >= limit:
                break
        return refs

    @staticmethod
    def _extract_rows(payload: Any, media_type: ListSourceMediaType) -> list[dict]:
        # MDBList sometimes returns {"movies": [...], "shows": [...]} and
        # sometimes a flat array — handle both.
        if isinstance(payload, dict):
            wanted = "movies" if media_type is ListSourceMediaType.MOVIE else "shows"
            rows = payload.get(wanted)
            if isinstance(rows, list):
                return rows
            # Fallback: any list-typed value.
            for value in payload.values():
                if isinstance(value, list):
                    return value
            return []
        if isinstance(payload, list):
            return payload
        return []

    @staticmethod
    def _row_to_ref(
        row: dict, media_type: ListSourceMediaType
    ) -> ExternalRef | None:
        if row.get("imdb_id"):
            provider, ext_id = "imdb", str(row["imdb_id"])
        elif row.get("tmdb_id"):
            provider, ext_id = "tmdb", str(row["tmdb_id"])
        elif row.get("tvdb_id"):
            provider, ext_id = "tvdb", str(row["tvdb_id"])
        else:
            return None
        year = row.get("release_year") or row.get("year")
        return ExternalRef(
            provider=provider,
            external_id=ext_id,
            media_type=media_type,
            title=row.get("title"),
            year=int(year) if isinstance(year, (int, str)) and str(year).isdigit() else None,
            extra={
                "mdblist_score": row.get("score"),
                "imdb_rating": row.get("imdb_rating"),
                "tmdb_rating": row.get("tmdb_rating"),
            },
        )
