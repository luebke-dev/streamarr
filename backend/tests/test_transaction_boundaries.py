"""Regression tests for caller-owned transaction boundaries."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.activity_log import ActivityLog
from streamarr.models.list import List, ListType, ListVisibility
from streamarr.models.media import MediaExternalId, MediaItem, MediaType
from streamarr.schemas.activity_log import ActivityLogCreate
from streamarr.schemas.list import ListCreate
from streamarr.services.activity_log import ActivityLogService
from streamarr.services.list import ListService
from streamarr.services.media import MediaService


async def test_media_create_and_external_id_can_roll_back_together(
    db_session: AsyncSession,
):
    service = MediaService(db_session)

    item = await service.create_media_item(
        media_type=MediaType.MOVIES,
        title="Atomic Movie",
        commit=False,
    )
    await service.add_external_id(
        media_item_guid=item.guid,
        provider="tmdb",
        external_id="123",
        commit=False,
    )
    await db_session.rollback()

    media_result = await db_session.execute(
        select(MediaItem).where(MediaItem.title == "Atomic Movie")
    )
    external_id_result = await db_session.execute(
        select(MediaExternalId).where(MediaExternalId.external_id == "123")
    )
    assert media_result.scalar_one_or_none() is None
    assert external_id_result.scalar_one_or_none() is None


async def test_activity_log_can_share_caller_transaction(
    db_session: AsyncSession,
):
    media_item = MediaItem(
        guid=uuid.uuid4(),
        title="Rollback Log Movie",
        media_type=MediaType.MOVIES,
    )
    db_session.add(media_item)
    await db_session.flush()

    await ActivityLogService(db_session).create(
        ActivityLogCreate(
            event_type="metadata.manual_update",
            message="Updated metadata",
            entity_type="media_item",
            entity_guid=media_item.guid,
        ),
        actor_guid=None,
        commit=False,
    )
    await db_session.rollback()

    media_result = await db_session.execute(
        select(MediaItem).where(MediaItem.title == "Rollback Log Movie")
    )
    log_result = await db_session.execute(
        select(ActivityLog).where(ActivityLog.event_type == "metadata.manual_update")
    )
    assert media_result.scalar_one_or_none() is None
    assert log_result.scalar_one_or_none() is None


async def test_list_create_can_share_caller_transaction(
    db_session: AsyncSession,
):
    await ListService(db_session).create(
        ListCreate(
            name="Rollback Trending",
            list_type=ListType.SYSTEM,
            visibility=ListVisibility.PUBLIC,
            update_source="rollback_trending",
        ),
        owner_guid=None,
        commit=False,
    )
    await db_session.rollback()

    result = await db_session.execute(
        select(List).where(List.update_source == "rollback_trending")
    )
    assert result.scalar_one_or_none() is None
