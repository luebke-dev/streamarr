"""DB-bound integration tests for SmartCollectionService.

These use the in-memory SQLite ``db_session`` fixture from conftest.py
plus a stub builder so we don't hit any external API. They are the
"phase J" smoke tests: they verify the full pipeline
(builder → resolver → filters → ListService.replace_items) actually
populates a List row.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

import pytest

from streamarr.metadata.list_sources import (
    ExternalRef,
    ListSourceMediaType,
)
from streamarr.models.list import List as ListModel, ListItem
from streamarr.models.media import MediaExternalId, MediaItem
from streamarr.models.smart_collection import (
    SmartCollectionMediaType,
    SmartCollectionRule,
    SmartCollectionRun,
    SmartCollectionRunStatus,
    SmartCollectionSyncMode,
)
from streamarr.smart_collections import SmartCollectionService
from streamarr.smart_collections.builders.base import (
    BuildResult,
    SmartCollectionBuilder,
)


class _StubBuilder(SmartCollectionBuilder):
    """In-memory builder that returns a fixed list of refs."""

    def __init__(self, refs: list[ExternalRef], type_: str = "stub") -> None:
        self.type = type_
        self._refs = refs

    async def fetch(self, config, *, media_type, limit, db) -> BuildResult:  # noqa: ARG002
        return BuildResult(refs=list(self._refs), debug={"stub": True})


def _stub_factory(refs):
    return lambda builder_type, api_keys=None: _StubBuilder(refs)  # noqa: ARG005


@pytest.mark.asyncio
async def test_full_run_populates_list(db_session, monkeypatch):
    """End-to-end: create rule + media item → run → list has the item."""

    # 1. Seed a MediaItem with an external TMDb id 42.
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="The Stub",
        release_date=datetime(2020, 1, 1, tzinfo=UTC),
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        MediaExternalId(
            media_item_guid=item.guid,
            provider="tmdb",
            external_id="42",
        )
    )

    # 2. Create a smart-collection rule pointing at a stub builder.
    rule = SmartCollectionRule(
        guid=uuid.uuid4(),
        name="Test rule",
        media_type=SmartCollectionMediaType.MOVIE,
        builder_type="stub",
        builder_config={},
        filters={},
        sync_mode=SmartCollectionSyncMode.SYNC,
        item_limit=20,
        schedule_cron="0 6 * * *",
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    # 3. Patch build_builder to hand back our stub.
    refs = [
        ExternalRef(
            provider="tmdb",
            external_id="42",
            media_type=ListSourceMediaType.MOVIE,
            title="The Stub",
            year=2020,
        )
    ]
    monkeypatch.setattr(
        "streamarr.smart_collections.service.build_builder",
        _stub_factory(refs),
    )

    # 4. Run the service.
    service = SmartCollectionService(db_session)
    result = await service.run(rule.guid)

    # 5. Verify outcome.
    assert result.status == SmartCollectionRunStatus.SUCCESS, result.error
    assert result.items_fetched == 1
    assert result.items_resolved == 1
    assert result.items_added == 1

    # Rule got a list_guid pointing at a freshly-created List.
    await db_session.refresh(rule)
    assert rule.list_guid is not None
    target_list = await db_session.get(ListModel, rule.list_guid)
    assert target_list is not None
    assert target_list.name == "Test rule"
    assert target_list.update_source == f"smart:{rule.guid}"

    # And the ListItem references our MediaItem.
    items = (
        await db_session.execute(
            ListItem.__table__.select().where(
                ListItem.list_guid == rule.list_guid
            )
        )
    ).all()
    assert len(items) == 1
    assert items[0].item_guid == item.guid

    # Run row recorded the metrics.
    runs = (
        await db_session.execute(
            SmartCollectionRun.__table__.select().where(
                SmartCollectionRun.rule_guid == rule.guid
            )
        )
    ).all()
    assert len(runs) == 1
    assert runs[0].status == "SUCCESS"
    assert runs[0].items_added == 1


@pytest.mark.asyncio
async def test_filter_drops_low_rating(db_session, monkeypatch):
    """Filter DSL must screen out items that don't meet ``min_rating``."""
    item = MediaItem(
        guid=uuid.uuid4(),
        media_type="MOVIES",
        title="Low rated",
        release_date=datetime(2021, 1, 1, tzinfo=UTC),
    )
    db_session.add(item)
    await db_session.flush()
    db_session.add(
        MediaExternalId(
            media_item_guid=item.guid, provider="tmdb", external_id="99"
        )
    )

    rule = SmartCollectionRule(
        guid=uuid.uuid4(),
        name="Min rating 9",
        media_type=SmartCollectionMediaType.MOVIE,
        builder_type="stub",
        builder_config={},
        filters={"min_rating": 9.0},
        sync_mode=SmartCollectionSyncMode.SYNC,
        item_limit=20,
        schedule_cron="0 6 * * *",
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    refs = [
        ExternalRef(
            provider="tmdb",
            external_id="99",
            media_type=ListSourceMediaType.MOVIE,
            title="Low rated",
            year=2021,
            extra={"vote_average": 6.5},
        )
    ]
    monkeypatch.setattr(
        "streamarr.smart_collections.service.build_builder",
        _stub_factory(refs),
    )

    service = SmartCollectionService(db_session)
    result = await service.run(rule.guid)
    assert result.status == SmartCollectionRunStatus.SUCCESS
    # Item was fetched and resolved but filtered out by min_rating
    assert result.items_resolved == 1
    assert result.items_filtered == 0
    assert result.items_added == 0


@pytest.mark.asyncio
async def test_unresolved_refs_dont_break_run(db_session, monkeypatch):
    """A ref for an unknown external_id is reported as unresolved, not fatal."""
    rule = SmartCollectionRule(
        guid=uuid.uuid4(),
        name="No matching item",
        media_type=SmartCollectionMediaType.MOVIE,
        builder_type="stub",
        builder_config={},
        filters={},
        sync_mode=SmartCollectionSyncMode.SYNC,
        item_limit=20,
        schedule_cron="0 6 * * *",
        enabled=True,
    )
    db_session.add(rule)
    await db_session.commit()

    refs = [
        ExternalRef(
            provider="tmdb",
            external_id="does-not-exist",
            media_type=ListSourceMediaType.MOVIE,
        )
    ]
    monkeypatch.setattr(
        "streamarr.smart_collections.service.build_builder",
        _stub_factory(refs),
    )

    service = SmartCollectionService(db_session)
    result = await service.run(rule.guid)
    assert result.status == SmartCollectionRunStatus.SUCCESS
    assert result.items_fetched == 1
    assert result.items_resolved == 0
    assert result.items_unresolved == 1
    assert result.items_added == 0
