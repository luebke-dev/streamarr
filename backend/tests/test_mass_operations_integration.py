"""DB-bound integration tests for MassOperationService."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from streamarr.models.genre import Genre
from streamarr.models.mass_operation import (
    MassOperationRule,
    MassOperationRunStatus,
)
from streamarr.models.media import MediaItem
from streamarr.services.mass_operation import MassOperationService


@pytest.mark.asyncio
async def test_dry_run_returns_match_count_without_mutating(db_session):
    """Dry-run must report matches but never modify rows."""
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="X",
        release_date=datetime(2022, 1, 1, tzinfo=UTC),
        description="original",
    )
    db_session.add(item)
    rule = MassOperationRule(
        guid=uuid.uuid4(),
        name="Force-set description",
        target_filter={"media_type_in": ["MOVIES"], "min_year": 2020},
        action={"type": "set_description", "value": "changed"},
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    service = MassOperationService(db_session)
    result = await service.run(rule.guid, dry_run=True)
    assert result.status == MassOperationRunStatus.SUCCESS
    assert result.dry_run is True
    assert result.items_matched == 1
    assert result.items_updated == 1
    # The actual row was NOT mutated.
    await db_session.refresh(item)
    assert item.description == "original"


@pytest.mark.asyncio
async def test_set_description_applies_in_non_dry_run(db_session):
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="Y",
        release_date=datetime(2022, 1, 1, tzinfo=UTC),
        description="original",
    )
    db_session.add(item)
    rule = MassOperationRule(
        guid=uuid.uuid4(),
        name="Force-set description (real)",
        target_filter={"media_type_in": ["MOVIES"], "min_year": 2020},
        action={"type": "set_description", "value": "changed"},
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    service = MassOperationService(db_session)
    result = await service.run(rule.guid, dry_run=False)
    assert result.status == MassOperationRunStatus.SUCCESS
    assert result.items_matched == 1
    assert result.items_updated == 1

    await db_session.refresh(item)
    assert item.description == "changed"


@pytest.mark.asyncio
async def test_set_genre_replaces_in_set_mode(db_session):
    drama = Genre(name="Drama")
    action_genre = Genre(name="Action")
    db_session.add_all([drama, action_genre])
    await db_session.flush()

    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="Z",
        release_date=datetime(2022, 1, 1, tzinfo=UTC),
    )
    item.genres = [drama]
    db_session.add(item)

    rule = MassOperationRule(
        guid=uuid.uuid4(),
        name="Force genre set",
        target_filter={"media_type_in": ["MOVIES"]},
        action={"type": "set_genre", "values": ["Action"], "mode": "set"},
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    service = MassOperationService(db_session)
    result = await service.run(rule.guid, dry_run=False)
    assert result.status == MassOperationRunStatus.SUCCESS
    assert result.items_updated == 1

    fresh = (
        await db_session.execute(
            select(MediaItem)
            .options(selectinload(MediaItem.genres))
            .where(MediaItem.guid == item.guid)
        )
    ).scalar_one()
    names = {g.name.lower() for g in fresh.genres}
    assert names == {"action"}


@pytest.mark.asyncio
async def test_clear_field_nulls_existing(db_session):
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="A",
        release_date=datetime(2022, 1, 1, tzinfo=UTC),
        tagline="something witty",
    )
    db_session.add(item)
    rule = MassOperationRule(
        guid=uuid.uuid4(),
        name="Clear taglines",
        target_filter={"media_type_in": ["MOVIES"]},
        action={"type": "clear", "field": "tagline"},
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    service = MassOperationService(db_session)
    result = await service.run(rule.guid, dry_run=False)
    assert result.status == MassOperationRunStatus.SUCCESS
    assert result.items_updated == 1
    await db_session.refresh(item)
    assert item.tagline is None
