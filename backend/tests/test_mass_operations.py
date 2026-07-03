"""Unit tests for the mass-operation service.

The DB-bound side of the service is exercised end-to-end by Phase G's
API tests against a real test database; here we focus on validation and
the pure SQL-translation helper.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select

from pyrate.models.media import MediaItem
from pyrate.services.mass_operation import (
    MassOperationError,
    MassOperationService,
)
from pyrate.smart_collections.filters import apply_media_filters_to_query


# ---------------------------------------------------------------------------
# Action validation
# ---------------------------------------------------------------------------


class TestValidation:
    def test_empty_action_rejected(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action({})

    def test_unknown_action_rejected(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action({"type": "make_coffee"})

    def test_set_genre_requires_values(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action({"type": "set_genre"})
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "set_genre", "values": []}
            )

    def test_set_genre_invalid_mode_rejected(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "set_genre", "values": ["Action"], "mode": "merge"}
            )

    def test_set_genre_valid_set_mode_passes(self):
        MassOperationService._validate_action(
            {"type": "set_genre", "values": ["Action"], "mode": "set"}
        )

    def test_set_min_age_requires_int(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "set_min_age", "value": "12"}
            )
        MassOperationService._validate_action(
            {"type": "set_min_age", "value": 12}
        )

    def test_set_availability_requires_string(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "set_availability", "value": ""}
            )
        MassOperationService._validate_action(
            {"type": "set_availability", "value": "available"}
        )

    def test_clear_allows_only_known_fields(self):
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "clear", "field": "guid"}
            )
        with pytest.raises(MassOperationError):
            MassOperationService._validate_action(
                {"type": "clear", "field": "unknown"}
            )
        MassOperationService._validate_action(
            {"type": "clear", "field": "tagline"}
        )


# ---------------------------------------------------------------------------
# SQL filter translation
# ---------------------------------------------------------------------------


def _compiled(stmt):
    """Render a Select to a literal SQL string for assertions."""
    return str(stmt.compile(compile_kwargs={"literal_binds": True}))


class TestFilterTranslation:
    def test_no_filters_returns_stmt_unchanged(self):
        stmt = select(MediaItem)
        result = apply_media_filters_to_query(stmt, {})
        assert _compiled(stmt) == _compiled(result)

    def test_media_type_in_translated_to_in_clause(self):
        stmt = apply_media_filters_to_query(
            select(MediaItem),
            {"media_type_in": ["MOVIES", "SHOWS"]},
        )
        sql = _compiled(stmt).upper()
        assert "MEDIA_ITEM.MEDIA_TYPE IN" in sql

    def test_year_window_uses_extract(self):
        stmt = apply_media_filters_to_query(
            select(MediaItem),
            {"min_year": 2000, "max_year": 2020},
        )
        sql = _compiled(stmt)
        assert "EXTRACT" in sql.upper()
        assert "2000" in sql
        assert "2020" in sql

    def test_genre_filters_use_subquery(self):
        stmt = apply_media_filters_to_query(
            select(MediaItem),
            {"genre_in": ["Action"]},
        )
        sql = _compiled(stmt).lower()
        assert "media_genre" in sql
        assert "genre" in sql

    def test_require_files_emits_exists(self):
        stmt = apply_media_filters_to_query(
            select(MediaItem),
            {"require_files": True},
        )
        assert "EXISTS" in _compiled(stmt).upper()

    def test_availability_translated_to_in_clause(self):
        stmt = apply_media_filters_to_query(
            select(MediaItem),
            {"availability": ["available", "downloadable"]},
        )
        sql = _compiled(stmt).lower()
        assert "availability_status" in sql
        assert "in" in sql


# ---------------------------------------------------------------------------
# _apply_action over fake items (in-memory)
# ---------------------------------------------------------------------------


def _item(*, genres=(), min_age=None, availability="unknown", description=None):
    return SimpleNamespace(
        guid="00000000-0000-0000-0000-000000000001",
        genres=[SimpleNamespace(name=g) for g in genres],
        min_age=min_age,
        availability_status=availability,
        description=description,
        poster_path=None,
        tagline=None,
    )


@pytest.fixture
def service():
    """Service with mocked DB for the in-memory action tests."""
    db = AsyncMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.add = MagicMock()

    svc = MassOperationService(db)
    # Sidestep DB by pre-stubbing the genre-fetch helper. It returns the
    # same list of "Genre" stand-ins as requested.
    svc._get_or_create_genres = AsyncMock(
        side_effect=lambda names: [SimpleNamespace(name=n) for n in names]
    )
    return svc


class TestApplyAction:
    @pytest.mark.asyncio
    async def test_set_genre_set_mode_replaces(self, service):
        items = [_item(genres=("Drama",)), _item(genres=("Action",))]
        updated, skipped = await service._apply_action(
            items, {"type": "set_genre", "values": ["Action"], "mode": "set"}
        )
        assert updated == 1
        assert skipped == 1
        assert [g.name for g in items[0].genres] == ["Action"]
        assert [g.name for g in items[1].genres] == ["Action"]

    @pytest.mark.asyncio
    async def test_set_genre_add_mode_appends(self, service):
        items = [_item(genres=("Drama",))]
        updated, skipped = await service._apply_action(
            items, {"type": "set_genre", "values": ["Action"], "mode": "add"}
        )
        assert updated == 1
        names = {g.name.lower() for g in items[0].genres}
        assert names == {"drama", "action"}

    @pytest.mark.asyncio
    async def test_set_min_age(self, service):
        items = [_item(min_age=6), _item(min_age=12)]
        updated, skipped = await service._apply_action(
            items, {"type": "set_min_age", "value": 12}
        )
        assert updated == 1
        assert skipped == 1
        assert items[0].min_age == 12

    @pytest.mark.asyncio
    async def test_set_availability(self, service):
        items = [_item(availability="unknown"), _item(availability="available")]
        updated, skipped = await service._apply_action(
            items, {"type": "set_availability", "value": "available"}
        )
        assert updated == 1
        assert skipped == 1
        assert items[0].availability_status == "available"

    @pytest.mark.asyncio
    async def test_clear_field_sets_null(self, service):
        items = [_item(description="foo"), _item(description=None)]
        updated, skipped = await service._apply_action(
            items, {"type": "clear", "field": "description"}
        )
        assert updated == 1
        assert skipped == 1
        assert items[0].description is None
