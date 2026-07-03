"""Tests for the Steam library import service (no network: enrich=False)."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaExternalId, MediaItem, MediaType
from pyrate.services.media import MediaService
from pyrate.services.steam_import import import_steam_games


@pytest.mark.asyncio
async def test_import_creates_items(db_session: AsyncSession):
    result = await import_steam_games(
        db_session,
        [{"app_id": "440", "name": "Team Fortress 2", "installed": True}],
        enrich=False,
    )

    assert result["created"] == 1
    assert result["updated"] == 0
    assert result["skipped"] == 0
    assert len(result["items"]) == 1

    item = (
        await db_session.execute(
            select(MediaItem).where(MediaItem.media_type == MediaType.GAMES)
        )
    ).scalar_one()
    assert str(item.guid) in result["items"]
    assert item.title == "Team Fortress 2"
    assert item.extra_data["lightrays"]["profile"] == "steam"
    assert item.extra_data["lightrays"]["app_ref"] == "440"

    ext = (
        await db_session.execute(
            select(MediaExternalId).where(MediaExternalId.provider == "steam")
        )
    ).scalar_one()
    assert ext.external_id == "440"
    assert ext.media_item_guid == item.guid


@pytest.mark.asyncio
async def test_name_none_falls_back_without_network(db_session: AsyncSession):
    result = await import_steam_games(
        db_session,
        [{"app_id": "999", "name": None, "installed": False}],
        enrich=False,
    )

    assert result["created"] == 1
    item = (await db_session.execute(select(MediaItem))).scalar_one()
    assert item.title == "Steam App 999"
    assert item.extra_data["lightrays"]["app_ref"] == "999"


@pytest.mark.asyncio
async def test_reimport_updates_not_duplicates(db_session: AsyncSession):
    games = [{"app_id": "570", "name": "Dota 2", "installed": True}]

    first = await import_steam_games(db_session, games, enrich=False)
    assert first["created"] == 1

    second = await import_steam_games(db_session, games, enrich=False)
    assert second["created"] == 0
    assert second["updated"] == 1
    assert first["items"] == second["items"]  # same guid touched

    item_count = (
        await db_session.execute(
            select(func.count()).select_from(MediaItem).where(
                MediaItem.media_type == MediaType.GAMES
            )
        )
    ).scalar_one()
    assert item_count == 1

    ext_count = (
        await db_session.execute(
            select(func.count())
            .select_from(MediaExternalId)
            .where(MediaExternalId.provider == "steam")
            .where(MediaExternalId.external_id == "570")
        )
    ).scalar_one()
    assert ext_count == 1


@pytest.mark.asyncio
async def test_existing_item_updated_and_unrelated_extra_preserved(
    db_session: AsyncSession,
):
    media_service = MediaService(db_session)
    item = await media_service.create_media_item(
        media_type=MediaType.GAMES,
        title="Old Title",
        extra_data={
            "igdb": {"rating": 92, "cover": "abc"},
            "lightrays": {"docker_image": "custom/steam:latest"},
        },
    )
    await media_service.add_external_id(
        media_item_guid=item.guid,
        provider="steam",
        external_id="620",
    )

    result = await import_steam_games(
        db_session,
        [{"app_id": "620", "name": "Portal 2", "installed": True}],
        enrich=False,
    )

    assert result["created"] == 0
    assert result["updated"] == 1
    assert result["items"] == [str(item.guid)]

    await db_session.refresh(item)
    assert item.title == "Portal 2"
    # Unrelated top-level key preserved.
    assert item.extra_data["igdb"] == {"rating": 92, "cover": "abc"}
    # Unrelated lightrays key preserved, launch keys set.
    assert item.extra_data["lightrays"]["docker_image"] == "custom/steam:latest"
    assert item.extra_data["lightrays"]["profile"] == "steam"
    assert item.extra_data["lightrays"]["app_ref"] == "620"

    # No duplicate item / external id created.
    item_count = (
        await db_session.execute(
            select(func.count()).select_from(MediaItem).where(
                MediaItem.media_type == MediaType.GAMES
            )
        )
    ).scalar_one()
    assert item_count == 1


@pytest.mark.asyncio
async def test_missing_app_id_is_skipped(db_session: AsyncSession):
    result = await import_steam_games(
        db_session,
        [
            {"app_id": "", "name": "No Id", "installed": False},
            {"app_id": "730", "name": "CS2", "installed": True},
        ],
        enrich=False,
    )

    assert result["skipped"] == 1
    assert result["created"] == 1
    assert len(result["items"]) == 1
