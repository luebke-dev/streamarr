"""Tests for the TMDB matcher that identifies items the scanner left bare."""

import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from streamarr.models.media import MediaType
from streamarr.workers.metadata_match_worker import (
    _candidate_titles,
    _match_via_path_id,
    _match_via_search,
    _normalise,
    _title_and_year,
)


def _item(title, *, year=None, media_type=MediaType.MOVIES):
    return SimpleNamespace(
        guid=uuid.uuid4(),
        title=title,
        media_type=media_type,
        release_date=datetime(year, 1, 1, tzinfo=UTC) if year else None,
    )


class TestNormalise:
    @pytest.mark.parametrize(
        "left,right",
        [
            ("Top Gun Maverick", "Top Gun: Maverick"),
            ("Terminator 3 Rise of the Machines", "Terminator 3: Rise of the Machines"),
            ("Anchorman The Legend of Ron Burgundy", "Anchorman - The Legend of Ron Burgundy"),
            ("Wall-E", "WALL·E"),
            ("Amelie", "Amélie"),
        ],
    )
    def test_punctuation_spacing_and_diacritics_do_not_separate_titles(self, left, right):
        assert _normalise(left) == _normalise(right)

    def test_different_films_stay_different(self):
        assert _normalise("The Matrix") != _normalise("The Matrix Reloaded")


class TestTitleAndYear:
    def test_year_comes_from_the_release_date(self):
        assert _title_and_year(_item("Parasite", year=2019)) == ("Parasite", 2019)

    def test_trailing_year_is_split_off_the_title(self):
        # The scanner derives show titles from folder names, so the year ends
        # up inside the title and there is no release_date at all.
        assert _title_and_year(_item("Better Call Saul (2015)")) == (
            "Better Call Saul",
            2015,
        )

    def test_release_date_wins_over_a_title_suffix(self):
        assert _title_and_year(_item("Devs (2020)", year=2020)) == ("Devs", 2020)

    def test_a_year_inside_the_title_is_left_alone(self):
        assert _title_and_year(_item("Blade Runner 2049", year=2017)) == (
            "Blade Runner 2049",
            2017,
        )


class TestCandidateTitles:
    def test_localised_and_original_spelling_both_count(self):
        # The client asks TMDB for de-DE, so a German library matches on the
        # translated title while the folder carries the original.
        titles = _candidate_titles(
            {"title": "Der König der Löwen", "original_title": "The Lion King"}
        )
        assert _normalise("The Lion King") in titles
        assert _normalise("Der König der Löwen") in titles


class TestSearchMatching:
    @pytest.mark.asyncio
    async def test_exact_title_and_year_is_accepted(self):
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [{"id": 496243, "title": "Parasite", "release_date": "2019-05-30"}]
        }
        outcome = await _match_via_search(tmdb, _item("Parasite", year=2019), MediaType.MOVIES)
        assert outcome.status == "matched"
        assert outcome.tmdb_id == "496243"

    @pytest.mark.asyncio
    async def test_match_on_the_original_title_of_a_localised_entry(self):
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [
                {
                    "id": 8587,
                    "title": "Der König der Löwen",
                    "original_title": "The Lion King",
                    "release_date": "1994-06-24",
                }
            ]
        }
        outcome = await _match_via_search(
            tmdb, _item("The Lion King", year=1994), MediaType.MOVIES
        )
        assert outcome.status == "matched"
        assert outcome.tmdb_id == "8587"

    @pytest.mark.asyncio
    async def test_a_year_one_off_still_counts(self):
        # Release years differ between regions; Radarr tolerates ±1 too.
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [{"id": 42, "title": "Some Film", "release_date": "2011-12-30"}]
        }
        outcome = await _match_via_search(tmdb, _item("Some Film", year=2012), MediaType.MOVIES)
        assert outcome.status == "matched"

    @pytest.mark.asyncio
    async def test_several_equally_good_hits_are_refused(self):
        # Three unrelated films called "Obsession" came out that year. A wrong
        # id is worse than none, because every later refresh would rewrite the
        # item with someone else's film.
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [
                {"id": 1339713, "title": "Obsession", "release_date": "2026-02-01"},
                {"id": 1615708, "title": "Obsession", "release_date": "2026-07-01"},
            ]
        }
        outcome = await _match_via_search(tmdb, _item("Obsession", year=2026), MediaType.MOVIES)
        assert outcome.status == "ambiguous"
        assert outcome.tmdb_id is None

    @pytest.mark.asyncio
    async def test_a_near_miss_title_is_not_accepted(self):
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [{"id": 604, "title": "The Matrix Reloaded", "release_date": "2003-05-15"}]
        }
        outcome = await _match_via_search(tmdb, _item("The Matrix", year=2003), MediaType.MOVIES)
        assert outcome.status == "not_found"

    @pytest.mark.asyncio
    async def test_the_year_must_line_up(self):
        tmdb = AsyncMock()
        tmdb.search_movies.return_value = {
            "results": [{"id": 603, "title": "The Matrix", "release_date": "1999-03-30"}]
        }
        outcome = await _match_via_search(tmdb, _item("The Matrix", year=2015), MediaType.MOVIES)
        assert outcome.status == "not_found"

    @pytest.mark.asyncio
    async def test_without_a_year_nothing_is_written(self):
        tmdb = AsyncMock()
        outcome = await _match_via_search(tmdb, _item("Heat"), MediaType.MOVIES)
        assert outcome.status == "ambiguous"
        tmdb.search_movies.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_shows_use_the_tv_search(self):
        tmdb = AsyncMock()
        tmdb.search_shows.return_value = {
            "results": [{"id": 60059, "name": "Better Call Saul", "first_air_date": "2015-02-08"}]
        }
        outcome = await _match_via_search(
            tmdb, _item("Better Call Saul (2015)", media_type=MediaType.SHOWS), MediaType.SHOWS
        )
        assert outcome.status == "matched"
        assert outcome.tmdb_id == "60059"
        tmdb.search_movies.assert_not_awaited()


class TestPathIdMatching:
    @pytest.mark.asyncio
    async def test_a_tvdb_id_in_the_path_resolves_exactly(self):
        tmdb = AsyncMock()
        tmdb.find_by_external_id.return_value = {
            "tv_results": [{"id": 60059, "name": "Better Call Saul", "first_air_date": "2015-02-08"}]
        }
        outcome = await _match_via_path_id(
            tmdb,
            _item("Better Call Saul (2015)", media_type=MediaType.SHOWS),
            "/library/shows/Better Call Saul (2015) [tvdbid-273181]/Season 01/ep.mkv",
            MediaType.SHOWS,
        )
        assert outcome is not None
        assert outcome.status == "matched"
        assert outcome.tmdb_id == "60059"
        assert outcome.source == "find:tvdb"
        tmdb.find_by_external_id.assert_awaited_once_with("273181", "tvdb_id")

    @pytest.mark.asyncio
    async def test_a_tmdb_id_in_the_path_needs_no_lookup_at_all(self):
        tmdb = AsyncMock()
        outcome = await _match_via_path_id(
            tmdb,
            _item("Dune (2021)"),
            "/library/movies/Dune (2021) [tmdbid-438631]/Dune.mkv",
            MediaType.MOVIES,
        )
        assert outcome.tmdb_id == "438631"
        assert outcome.source == "path:tmdb"
        tmdb.find_by_external_id.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_an_ambiguous_find_result_is_not_used(self):
        tmdb = AsyncMock()
        tmdb.find_by_external_id.return_value = {"tv_results": [{"id": 1}, {"id": 2}]}
        outcome = await _match_via_path_id(
            tmdb,
            _item("Whatever (2020)", media_type=MediaType.SHOWS),
            "/library/shows/Whatever (2020) [tvdbid-999]/S01/ep.mkv",
            MediaType.SHOWS,
        )
        assert outcome is None

    @pytest.mark.asyncio
    async def test_a_path_without_ids_falls_through(self):
        tmdb = AsyncMock()
        outcome = await _match_via_path_id(
            tmdb, _item("Parasite", year=2019), "/library/movies/Parasite (2019)/f.mkv",
            MediaType.MOVIES,
        )
        assert outcome is None

    @pytest.mark.asyncio
    async def test_no_path_falls_through(self):
        assert await _match_via_path_id(AsyncMock(), _item("X", year=2000), None, MediaType.MOVIES) is None
