"""Episode acquisition: the path that makes series automation possible.

Before the hierarchy got its own `SEASONS`/`EPISODES` types, episodes were stored
as `SHOWS`. Several places only ever listed `MOVIES`/`SHOWS`, so once episodes had
their own type every episode release search skipped itself: no releases were
stored, no quality profile could match, and no episode was ever grabbed - by RSS,
by the reconcile sweep or by hand.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.libraries.movies import MovieLibraryPlugin
from streamarr.models.media import MediaItem, MediaType
from streamarr.services.indexer import IndexerService
from streamarr.services.release_search import ReleaseSearchService
from streamarr.services.rss_sync import RssSyncService


async def _show_tree(db: AsyncSession, *, with_file: bool = False):
    """Show -> Season 1 -> Episode 3, optionally with an existing file."""
    from streamarr.models.media import MediaFile

    show = MediaItem(title="Silo", media_type=MediaType.SHOWS)
    db.add(show)
    await db.flush()
    season = MediaItem(
        title="Staffel 1", media_type=MediaType.SEASONS,
        parent_guid=show.guid, sequence_number=1,
    )
    db.add(season)
    await db.flush()
    episode = MediaItem(
        title="Freiheitstag", media_type=MediaType.EPISODES,
        parent_guid=season.guid, sequence_number=3,
    )
    db.add(episode)
    await db.flush()
    if with_file:
        db.add(MediaFile(
            guid=uuid.uuid4(), media_item_guid=episode.guid,
            file_path="/library/shows/Silo/S01E03.mkv", file_name="S01E03.mkv",
        ))
        await db.flush()
    return show, season, episode


class TestEpisodeReleaseSearch:
    async def test_episodes_are_searchable(self, db_session: AsyncSession):
        _, _, episode = await _show_tree(db_session)
        svc = ReleaseSearchService(db_session)
        assert svc._is_searchable(episode) is True

    async def test_seasons_are_searchable(self, db_session: AsyncSession):
        _, season, _ = await _show_tree(db_session)
        svc = ReleaseSearchService(db_session)
        assert svc._is_searchable(season) is True

    async def test_a_root_show_is_still_skipped_unless_forced(
        self, db_session: AsyncSession
    ):
        show, _, _ = await _show_tree(db_session)
        svc = ReleaseSearchService(db_session)
        assert svc._is_searchable(show) is False
        assert svc._is_searchable(show, force=True) is True

    async def test_show_context_resolves_season_and_episode(
        self, db_session: AsyncSession
    ):
        """Without this the caller refuses to search at all."""
        _, _, episode = await _show_tree(db_session)
        svc = ReleaseSearchService(db_session)
        ids: dict[str, str | None] = {}
        context = await svc._resolve_show_context(episode, ids)

        assert context["show_title"] == "Silo"
        assert context["season_number"] == 1
        assert context["episode_number"] == 3

    async def test_show_context_for_a_season_has_no_episode(
        self, db_session: AsyncSession
    ):
        _, season, _ = await _show_tree(db_session)
        svc = ReleaseSearchService(db_session)
        context = await svc._resolve_show_context(season, {})

        assert context["season_number"] == 1
        assert context["episode_number"] is None

    async def test_episodes_use_the_shows_plugin_for_metadata(
        self, db_session: AsyncSession
    ):
        """No plugin means no release metadata, hence "480p" and a profile reject."""
        svc = ReleaseSearchService(db_session)
        from streamarr.libraries.shows import ShowLibraryPlugin

        assert isinstance(svc._library_plugin_for(MediaType.EPISODES), ShowLibraryPlugin)
        assert isinstance(svc._library_plugin_for(MediaType.SEASONS), ShowLibraryPlugin)
        assert isinstance(svc._library_plugin_for(MediaType.MOVIES), MovieLibraryPlugin)


class TestRssAnnouncedEpisode:
    async def test_a_feed_hit_resolves_to_the_announced_episode(
        self, db_session: AsyncSession
    ):
        """A feed item means "this episode is out", not "backfill the whole show"."""
        show, _, episode = await _show_tree(db_session)
        svc = RssSyncService(db_session)

        leaves = await svc._resolve_announced_leaves({
            str(show.guid): ["Silo.S01E03.1080p.WEB.H264-GLHF"],
        })

        assert leaves == [episode.guid]

    async def test_an_already_imported_episode_is_not_grabbed_again(
        self, db_session: AsyncSession
    ):
        show, _, _ = await _show_tree(db_session, with_file=True)
        svc = RssSyncService(db_session)

        leaves = await svc._resolve_announced_leaves({
            str(show.guid): ["Silo.S01E03.1080p.WEB.H264-GLHF"],
        })

        assert leaves == []

    async def test_an_unknown_episode_does_not_fall_back_to_the_whole_show(
        self, db_session: AsyncSession
    ):
        show, _, _ = await _show_tree(db_session)
        svc = RssSyncService(db_session)

        leaves = await svc._resolve_announced_leaves({
            str(show.guid): ["Silo.S09E99.1080p.WEB.H264-GLHF"],
        })

        assert leaves == []

    async def test_a_movie_root_is_its_own_leaf(self, db_session: AsyncSession):
        movie = MediaItem(title="Heat", media_type=MediaType.MOVIES)
        db_session.add(movie)
        await db_session.flush()
        svc = RssSyncService(db_session)

        leaves = await svc._resolve_announced_leaves({
            str(movie.guid): ["Heat.1995.1080p.BluRay.x264-GRP"],
        })

        assert leaves == [movie.guid]


class TestRssCategoryFilter:
    def test_filter_uses_movie_and_show_categories(self):
        class _Cat:
            def __init__(self, cid, kind):
                self.newznab_category_id = cid
                self.category_type = kind

        class _Indexer:
            categories = [_Cat(2000, "movie"), _Cat(5000, "show"),
                          _Cat(3000, "music"), _Cat(1000, "game")]

        assert IndexerService._rss_category_filter(_Indexer()) == "2000,5000"

    def test_filter_is_none_without_relevant_categories(self):
        class _Cat:
            newznab_category_id = 3000
            category_type = "music"

        class _Indexer:
            categories = [_Cat()]

        assert IndexerService._rss_category_filter(_Indexer()) is None


class TestPromotionRecordsProvenance:
    async def test_promote_sets_imported_at_and_library(
        self, db_session: AsyncSession, tmp_path
    ):
        """A promoted file must look imported and belong to a library root."""
        from streamarr.models.library import Library
        from streamarr.models.media import MediaFile

        library_path = tmp_path / "library"
        library_path.mkdir()
        library = Library(
            guid=uuid.uuid4(), name="Filme", type="MOVIES", plugin_id="movies",
            path=str(library_path), enabled=True,
            created_at=datetime.now(UTC), updated_at=datetime.now(UTC),
        )
        db_session.add(library)

        movie = MediaItem(
            title="Heat", media_type=MediaType.MOVIES,
        )
        db_session.add(movie)
        await db_session.flush()

        source = tmp_path / "downloads" / "Heat.1995.mkv"
        source.parent.mkdir()
        source.write_bytes(b"payload")
        media_file = MediaFile(
            guid=uuid.uuid4(), media_item_guid=movie.guid,
            file_path=str(source), file_name=source.name, file_size=7,
        )
        db_session.add(media_file)
        await db_session.commit()

        plugin = MovieLibraryPlugin()
        result = await plugin.promote_to_library(media_file, db_session)

        assert result["success"] is True
        assert str(library_path) in media_file.file_path
        assert media_file.imported_at is not None
        assert media_file.library_root == str(library_path)
        assert str(media_file.library_guid) == str(library.guid)
