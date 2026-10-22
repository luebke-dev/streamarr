import uuid
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import MediaExternalId, MediaItem, MediaType
from streamarr.services.media import MediaService
from streamarr.services.metadata_refresh import MetadataService


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
    assert episodes[1].extra_data["id"] == 1002

    ext_result = await db_session.execute(
        select(MediaExternalId)
        .where(MediaExternalId.media_item_guid.in_([season.guid, episodes[1].guid]))
        .order_by(MediaExternalId.external_id)
    )
    external_ids = {(row.media_item_guid, row.provider, row.external_id) for row in ext_result.scalars()}

    assert (season.guid, "tmdb", "449260") in external_ids
    assert (episodes[1].guid, "tmdb", "1002") in external_ids


@pytest.mark.asyncio
async def test_a_created_season_and_episode_get_their_own_media_type(
    db_session: AsyncSession,
):
    """A refresh must not type the whole tree as SHOWS.

    ``_upsert_season`` and ``_upsert_episode`` hardcoded ``MediaType.SHOWS`` for
    the rows they create, so a metadata refresh built a second tree of
    "seasons" and "episodes" typed as shows, hanging off the real one. Nothing
    referenced them - no media file, no view - so the only symptom was the UI
    listing "Staffel 1" as a series. On this instance that produced ~64k rows
    in a week.
    """
    from streamarr.services.media_hierarchy import episode_type, season_type

    media_service = MediaService(db_session)
    show = await media_service.create_media_item(
        media_type=MediaType.SHOWS,
        title="Severance",
    )

    plugin = AsyncMock()
    plugin.get_show_season.return_value = {
        "id": 2001,
        "name": "Staffel 1",
        "overview": None,
        "poster_path": None,
        "air_date": "2022-02-18",
        "episodes": [
            {
                "id": 3001,
                "episode_number": 1,
                "name": "Gute Nachrichten zur Hölle",
                "overview": None,
                "still_path": None,
                "air_date": "2022-02-18",
            }
        ],
    }

    seasons, episodes = await MetadataService(db_session)._refresh_seasons(
        show, plugin, "95396", [{"season_number": 1}]
    )
    assert (seasons, episodes) == (1, 1)

    rows = (
        await db_session.execute(
            select(MediaItem).where(MediaItem.parent_guid == show.guid)
        )
    ).scalars().all()
    assert len(rows) == 1
    season = rows[0]
    assert season.media_type == season_type()
    assert season.media_type != MediaType.SHOWS

    episodes = (
        await db_session.execute(
            select(MediaItem).where(MediaItem.parent_guid == season.guid)
        )
    ).scalars().all()
    assert len(episodes) == 1
    assert episodes[0].media_type == episode_type()
    assert episodes[0].media_type != MediaType.SHOWS


@asynccontextmanager
async def _session_context(session):
    yield session


@pytest.mark.asyncio
async def test_worker_refreshes_season_with_parent_show_tmdb_id():
    from streamarr.worker import refresh_media_item_metadata

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
        patch("streamarr.worker.sessionmanager") as sessionmanager_mock,
        patch("streamarr.worker.get_tmdb_api_key", AsyncMock(return_value="key")),
        patch("streamarr.worker.TMDB", return_value=tmdb_plugin),
        patch(
            "streamarr.services.metadata_refresh.MetadataService",
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


class TestApplyNormalizedReleaseDate:
    """A provider hands dates back as ISO strings; the column is a timestamp."""

    def _item(self):
        return MediaItem(
            guid=uuid.uuid4(),
            media_type=MediaType.MOVIES,
            title="War for the Planet of the Apes",
        )

    def test_iso_string_becomes_a_date(self):
        from datetime import date

        from streamarr.metadata.base import NormalizedMetadata

        item = self._item()
        MetadataService._apply_normalized(
            item,
            NormalizedMetadata(title="Planet der Affen - Survival", release_date="2017-07-11"),
        )
        # asyncpg rejects the raw string outright, so every refresh of an item
        # carrying a release date used to die before writing anything.
        assert item.release_date == date(2017, 7, 11)

    def test_an_unparsable_date_is_dropped_rather_than_written(self):
        from streamarr.metadata.base import NormalizedMetadata

        item = self._item()
        MetadataService._apply_normalized(
            item, NormalizedMetadata(title="Something", release_date="tba")
        )
        assert item.release_date is None

    def test_other_fields_still_come_through(self):
        from streamarr.metadata.base import NormalizedMetadata

        item = self._item()
        MetadataService._apply_normalized(
            item,
            NormalizedMetadata(
                title="Planet der Affen - Survival",
                original_title="War for the Planet of the Apes",
                release_date="2017-07-11",
                poster_path="/poster.jpg",
            ),
        )
        assert item.title == "Planet der Affen - Survival"
        assert item.poster_path == "/poster.jpg"
