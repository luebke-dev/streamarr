import json
import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from pyrate.models.media import MediaExternalId, MediaItem, MediaType
from pyrate.services.media import MediaService
from pyrate.services.metadata_refresh import MetadataService


@pytest.mark.asyncio
async def test_refresh_season_updates_existing_episode_and_adds_new_episode(
    db_session: AsyncSession,
):
    media_service = MediaService(db_session)
    show = await media_service.create_media_item(
        media_type=MediaType.SHOWS,
        title="House of the Dragon",
    )
    season = await media_service.create_media_item(
        media_type=MediaType.SHOWS,
        title="Staffel 3",
        parent_guid=show.guid,
        sequence_number=3,
    )
    existing_episode = await media_service.create_media_item(
        media_type=MediaType.SHOWS,
        title="Old Episode Title",
        parent_guid=season.guid,
        sequence_number=1,
    )

    plugin = AsyncMock()
    plugin.get_show_season.return_value = {
        "id": 449260,
        "name": "Season 3",
        "overview": "Third season",
        "poster_path": "/season-3.jpg",
        "air_date": "2026-06-01",
        "episodes": [
            {
                "id": 1001,
                "episode_number": 1,
                "name": "Updated Episode",
                "overview": "Existing episode metadata changed",
                "still_path": "/episode-1.jpg",
                "air_date": "2026-06-01",
            },
            {
                "id": 1002,
                "episode_number": 2,
                "name": "New Episode",
                "overview": "New episode metadata",
                "still_path": "/episode-2.jpg",
                "air_date": "2026-06-08",
            },
        ],
    }

    refreshed = await MetadataService(db_session).refresh_season(
        season.guid,
        plugin,
        "94997",
        3,
    )

    assert refreshed is not None
    assert refreshed.guid == season.guid
    assert refreshed.title == "Season 3"
    assert refreshed.poster_path == "/season-3.jpg"
    plugin.get_show_season.assert_awaited_once_with(94997, "3")

    result = await db_session.execute(
        select(MediaItem)
        .where(MediaItem.parent_guid == season.guid)
        .order_by(MediaItem.sequence_number)
    )
    episodes = list(result.scalars().all())

    assert [episode.sequence_number for episode in episodes] == [1, 2]
    assert episodes[0].guid == existing_episode.guid
    assert episodes[0].title == "Updated Episode"
    assert episodes[1].title == "New Episode"
    assert json.loads(episodes[1].extra_data)["id"] == 1002

    ext_result = await db_session.execute(
        select(MediaExternalId)
        .where(MediaExternalId.media_item_guid.in_([season.guid, episodes[1].guid]))
        .order_by(MediaExternalId.external_id)
    )
    external_ids = {(row.media_item_guid, row.provider, row.external_id) for row in ext_result.scalars()}

    assert (season.guid, "tmdb", "449260") in external_ids
    assert (episodes[1].guid, "tmdb", "1002") in external_ids


@asynccontextmanager
async def _session_context(session):
    yield session


@pytest.mark.asyncio
async def test_worker_refreshes_season_with_parent_show_tmdb_id():
    from pyrate.worker import refresh_media_item_metadata

    season_guid = uuid.uuid4()
    show_guid = uuid.uuid4()
    season = SimpleNamespace(
        guid=season_guid,
        title="Staffel 3",
        media_type=MediaType.SHOWS,
        parent_guid=show_guid,
        sequence_number=3,
        external_ids=[
            SimpleNamespace(provider="tmdb", external_id="449260"),
        ],
    )
    show = SimpleNamespace(
        guid=show_guid,
        title="House of the Dragon",
        media_type=MediaType.SHOWS,
        parent_guid=None,
        sequence_number=None,
        external_ids=[
            SimpleNamespace(provider="tmdb", external_id="94997"),
        ],
    )

    session = AsyncMock()
    results = [season, show]

    async def execute(_stmt, *_args, **_kwargs):
        result = MagicMock()
        result.scalars.return_value.first.return_value = results.pop(0)
        return result

    session.execute = AsyncMock(side_effect=execute)
    tmdb_plugin = AsyncMock()
    tmdb_plugin.close = AsyncMock()
    metadata_service = AsyncMock()

    with (
        patch("pyrate.worker.sessionmanager") as sessionmanager_mock,
        patch("pyrate.worker.get_tmdb_api_key", AsyncMock(return_value="key")),
        patch("pyrate.worker.TMDB", return_value=tmdb_plugin),
        patch(
            "pyrate.services.metadata_refresh.MetadataService",
            return_value=metadata_service,
        ),
    ):
        sessionmanager_mock.session.return_value = _session_context(session)

        await refresh_media_item_metadata(str(season_guid))

    metadata_service.refresh.assert_not_awaited()
    metadata_service.refresh_season.assert_awaited_once_with(
        season_guid,
        tmdb_plugin,
        "94997",
        3,
    )
    tmdb_plugin.close.assert_awaited_once()
