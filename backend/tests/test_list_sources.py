"""Tests for the list-source adapters under streamarr.metadata.list_sources."""

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from streamarr.metadata.list_sources import (
    ExternalRef,
    ListSourceError,
    ListSourceMediaType,
    build_source,
    list_source_slugs,
)
from streamarr.metadata.list_sources.imdb import (
    ImdbListSource,
    _walk_for_tt_ids,
)
from streamarr.metadata.list_sources.letterboxd import (
    LetterboxdListSource,
    _SLUG_RE,
    _TMDB_RE,
)
from streamarr.metadata.list_sources.tmdb_list import TmdbListSource


def _resp(json_data, status_code=200, headers=None):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.headers = headers or {}
    resp.text = ""
    return resp


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------


class TestRegistry:
    def test_known_slugs_present(self):
        slugs = list_source_slugs()
        assert {"tmdb", "trakt", "mdblist", "imdb", "letterboxd", "mal", "anilist"} <= set(slugs)

    def test_build_unknown_raises(self):
        with pytest.raises(ListSourceError):
            build_source("does-not-exist")

    def test_build_requires_api_key(self):
        with pytest.raises(ListSourceError):
            build_source("tmdb", {})

    def test_build_keyless_source_works(self):
        # IMDb/Letterboxd/MAL/AniList have no required key.
        source = build_source("imdb", {})
        assert source.slug == "imdb"


# ---------------------------------------------------------------------------
# TmdbListSource
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_client():
    return AsyncMock(spec=httpx.AsyncClient)


@pytest.fixture
def tmdb_source(mock_client):
    return TmdbListSource(api_key="k", client=mock_client)


class TestTmdbListSource:
    @pytest.mark.asyncio
    async def test_chart_pagination_respects_limit(
        self, tmdb_source, mock_client
    ):
        mock_client.get.side_effect = [
            _resp(
                {
                    "results": [
                        {
                            "id": 1,
                            "title": "A",
                            "release_date": "2020-01-01",
                            "vote_average": 7.1,
                        },
                        {
                            "id": 2,
                            "title": "B",
                            "release_date": "2019-05-04",
                        },
                    ],
                    "total_pages": 3,
                }
            ),
            _resp(
                {
                    "results": [
                        {"id": 3, "title": "C", "release_date": "2018-09-10"},
                    ],
                    "total_pages": 3,
                }
            ),
        ]
        refs = await tmdb_source.fetch(
            {"mode": "chart", "chart": "popular"},
            media_type=ListSourceMediaType.MOVIE,
            limit=3,
        )
        assert [r.external_id for r in refs] == ["1", "2", "3"]
        assert refs[0].provider == "tmdb"
        assert refs[0].year == 2020
        assert refs[0].extra["vote_average"] == 7.1

    @pytest.mark.asyncio
    async def test_chart_unknown_name_raises(self, tmdb_source, mock_client):
        with pytest.raises(ListSourceError):
            await tmdb_source.fetch(
                {"mode": "chart", "chart": "no-such-chart"},
                media_type=ListSourceMediaType.MOVIE,
            )

    @pytest.mark.asyncio
    async def test_collection_movies_only(self, tmdb_source):
        with pytest.raises(ListSourceError):
            await tmdb_source.fetch(
                {"mode": "collection", "collection_id": 10},
                media_type=ListSourceMediaType.SHOW,
            )

    @pytest.mark.asyncio
    async def test_collection_returns_parts(self, tmdb_source, mock_client):
        mock_client.get.return_value = _resp(
            {
                "parts": [
                    {"id": 100, "title": "X"},
                    {"id": 101, "title": "Y"},
                ]
            }
        )
        refs = await tmdb_source.fetch(
            {"mode": "collection", "collection_id": 10},
            media_type=ListSourceMediaType.MOVIE,
            limit=10,
        )
        assert [r.external_id for r in refs] == ["100", "101"]


# ---------------------------------------------------------------------------
# IMDb extraction
# ---------------------------------------------------------------------------


class TestImdbExtraction:
    def test_walk_for_tt_ids_dedupes_in_order(self):
        payload = {
            "props": {
                "pageProps": {
                    "contentData": {
                        "entries": [
                            {"chartItem": {"id": "tt0111161"}},
                            {"chartItem": {"id": "tt0068646"}},
                            {"chartItem": {"id": "tt0111161"}},  # dupe
                        ]
                    }
                }
            }
        }
        ids = _walk_for_tt_ids(payload, limit=10)
        assert ids == ["tt0111161", "tt0068646"]

    def test_walk_for_tt_ids_respects_limit(self):
        payload = {
            "x": [{"id": f"tt{1000000 + i}"} for i in range(20)]
        }
        ids = _walk_for_tt_ids(payload, limit=5)
        assert len(ids) == 5
        assert ids[0] == "tt1000000"

    def test_regex_fallback_picks_up_ids(self):
        html = '... "id":"tt0111161" ... no_next_data_here ... "id":"tt0068646" ...'
        ids = ImdbListSource._extract_tt_ids(html, limit=10)
        assert ids == ["tt0111161", "tt0068646"]


# ---------------------------------------------------------------------------
# Letterboxd parsing (regex-only, no network)
# ---------------------------------------------------------------------------


class TestLetterboxdParsing:
    def test_slug_regex_extracts_name_and_year(self):
        html = (
            '<li class="poster-container" data-film-id="55">\n'
            '  <div class="film-poster" data-film-slug="the-godfather" '
            'data-film-name="The Godfather" data-film-release-year="1972"></div>\n'
            "</li>"
        )
        matches = list(_SLUG_RE.finditer(html))
        assert len(matches) == 1
        assert matches[0].group("slug") == "the-godfather"
        assert matches[0].group("name") == "The Godfather"
        assert matches[0].group("year") == "1972"

    def test_tmdb_regex_extracts_id(self):
        html = (
            '<a href="https://www.themoviedb.org/movie/238/" '
            'data-track-action="TMDb">TMDb</a>'
        )
        match = _TMDB_RE.search(html)
        assert match is not None
        assert match.group("id") == "238"

    @pytest.mark.asyncio
    async def test_movies_only_constraint(self):
        source = LetterboxdListSource(client=AsyncMock(spec=httpx.AsyncClient))
        with pytest.raises(ListSourceError):
            await source.fetch(
                {"mode": "popular_this_week"},
                media_type=ListSourceMediaType.SHOW,
            )


# ---------------------------------------------------------------------------
# ExternalRef dataclass
# ---------------------------------------------------------------------------


class TestExternalRef:
    def test_default_extra_is_isolated(self):
        a = ExternalRef(
            provider="tmdb", external_id="1", media_type=ListSourceMediaType.MOVIE
        )
        b = ExternalRef(
            provider="tmdb", external_id="2", media_type=ListSourceMediaType.MOVIE
        )
        a.extra["x"] = 1
        assert "x" not in b.extra
