"""Unit tests for the smart-collection engine.

Covers the pure-Python pieces (filters, cron, registry) — database-bound
pieces (resolver, service) are exercised in integration tests under
``tests/api/test_smart_collections_api.py`` once Phase G lands.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from streamarr.metadata.list_sources import (
    ExternalRef,
    ListSourceError,
    ListSourceMediaType,
)
from streamarr.smart_collections import (
    build_builder,
    builder_types,
    next_run_after,
    parse_cron,
)
from streamarr.smart_collections.builders.library_filter import (
    LIBRARY_FILTER_TYPE,
    LibraryFilterBuilder,
)
from streamarr.smart_collections.builders.list_source import ListSourceBuilder
from streamarr.smart_collections.filters import filter_resolved


# ---------------------------------------------------------------------------
# Builder registry
# ---------------------------------------------------------------------------


class TestBuilderRegistry:
    def test_builder_types_include_library_and_sources(self):
        types_ = builder_types()
        assert LIBRARY_FILTER_TYPE in types_
        assert "tmdb" in types_
        assert "trakt" in types_
        assert "imdb" in types_

    def test_library_filter_factory_returns_concrete_class(self):
        builder = build_builder(LIBRARY_FILTER_TYPE)
        assert isinstance(builder, LibraryFilterBuilder)

    def test_list_source_factory_returns_wrapper(self):
        # imdb is keyless; build it without raising.
        builder = build_builder("imdb")
        assert isinstance(builder, ListSourceBuilder)
        assert builder.type == "imdb"

    def test_unknown_builder_type_raises(self):
        with pytest.raises(ListSourceError):
            build_builder("not-a-source")

    def test_keyed_source_requires_api_key(self):
        with pytest.raises(ListSourceError):
            build_builder("tmdb", {})


# ---------------------------------------------------------------------------
# Cron
# ---------------------------------------------------------------------------


class TestCron:
    def test_parse_cron_accepts_valid(self):
        assert parse_cron("0 6 * * *") is True
        assert parse_cron("*/5 * * * *") is True

    def test_parse_cron_rejects_invalid(self):
        assert parse_cron("not-a-cron") is False
        assert parse_cron("99 99 * * *") is False
        assert parse_cron("") is False

    def test_next_run_after_returns_future(self):
        base = datetime(2026, 5, 14, 5, 30, tzinfo=UTC)
        nxt = next_run_after("0 6 * * *", reference=base)
        assert nxt > base
        assert nxt.hour == 6 and nxt.minute == 0

    def test_next_run_after_raises_on_invalid(self):
        with pytest.raises(ValueError):
            next_run_after("not-a-cron")


# ---------------------------------------------------------------------------
# Filter DSL
# ---------------------------------------------------------------------------


def _ref(**extra) -> ExternalRef:
    return ExternalRef(
        provider="tmdb",
        external_id="1",
        media_type=ListSourceMediaType.MOVIE,
        title="Film",
        year=extra.pop("year", 2020),
        extra=extra,
    )


def _item(
    *,
    title="Film",
    release_year=2020,
    genres=(),
    min_age=None,
    availability="available",
    files=(),
) -> MagicMock:
    item = SimpleNamespace(
        title=title,
        release_date=datetime(release_year, 6, 1, tzinfo=UTC) if release_year else None,
        genres=[SimpleNamespace(name=g) for g in genres],
        files=list(files),
        min_age=min_age,
        availability_status=availability,
        guid="00000000-0000-0000-0000-000000000001",
    )
    return item


class TestFilterDsl:
    def test_no_rules_keeps_everything(self):
        pairs = [(_ref(), _item())]
        assert filter_resolved(pairs, {}) == pairs
        assert filter_resolved(pairs, None) == pairs

    def test_min_rating_drops_low_and_missing(self):
        keep = (_ref(vote_average=8.2), _item())
        drop_low = (_ref(vote_average=5.0), _item())
        drop_missing = (_ref(), _item())
        kept = filter_resolved(
            [keep, drop_low, drop_missing], {"min_rating": 7.0}
        )
        assert kept == [keep]

    def test_max_rating_drops_high(self):
        a = (_ref(vote_average=8.0), _item())
        b = (_ref(vote_average=9.5), _item())
        assert filter_resolved([a, b], {"max_rating": 9.0}) == [a]

    def test_year_window_uses_item_then_ref(self):
        early = (_ref(year=1995), _item(release_year=1995))
        mid = (_ref(year=2005), _item(release_year=2005))
        late = (_ref(year=2025), _item(release_year=2025))
        kept = filter_resolved(
            [early, mid, late], {"min_year": 2000, "max_year": 2020}
        )
        assert kept == [mid]

    def test_genre_in_and_not_in(self):
        action = (_ref(), _item(genres=["Action", "Drama"]))
        horror = (_ref(), _item(genres=["Horror"]))
        kept = filter_resolved(
            [action, horror], {"genre_in": ["Action"]}
        )
        assert kept == [action]
        kept = filter_resolved(
            [action, horror], {"genre_not_in": ["Horror"]}
        )
        assert kept == [action]

    def test_require_files(self):
        with_files = (_ref(), _item(files=[object()]))
        without_files = (_ref(), _item(files=[]))
        kept = filter_resolved(
            [with_files, without_files], {"require_files": True}
        )
        assert kept == [with_files]

    def test_availability_set(self):
        a = (_ref(), _item(availability="available"))
        b = (_ref(), _item(availability="unknown"))
        kept = filter_resolved(
            [a, b], {"availability": ["available"]}
        )
        assert kept == [a]

    def test_min_age_band(self):
        pg = (_ref(), _item(min_age=6))
        teen = (_ref(), _item(min_age=12))
        adult = (_ref(), _item(min_age=18))
        kept = filter_resolved(
            [pg, teen, adult], {"min_age": 12, "max_age": 16}
        )
        assert kept == [teen]
