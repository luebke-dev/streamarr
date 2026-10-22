"""Genre import must never take the whole media import down with it.

Import paths that see only `genre_ids` (TMDB list responses) have no genre name,
so an id the local `genre` table does not know cannot be created. Linking it
anyway violates `media_genre.genre_id -> genre.id`, which aborts the PostgreSQL
transaction - and because the failure was swallowed, every following statement of
the import failed with `InFailedSQLTransactionError`. In practice that meant 39 of
87 titles could not be imported at all.
"""

from sqlalchemy import select, text

from streamarr.models.genre import Genre
from streamarr.models.media import media_genre_table
from streamarr.services.library_imports import LibraryImportService


async def _some_media_item_guid(db):
    row = (await db.execute(text("select guid from media_item limit 1"))).first()
    return row[0] if row else None


class TestImportGenresForMedia:
    async def test_unknown_genre_without_name_is_skipped(self, db_session):
        """The id cannot be created, so it must not be linked either."""
        svc = LibraryImportService(db_session)

        # 999999 is not in the local genre table and has no name.
        await svc.import_genres_for_media(guid := __import__("uuid").uuid4(), [999999])

        # The session is still usable - this is the actual regression.
        assert (await db_session.execute(select(Genre))).scalars().all() == []
        assert guid is not None

    async def test_transaction_is_usable_after_unknown_genres(self, db_session):
        """A run of unknown ids must leave the session in a working state."""
        from streamarr.models.media import MediaItem
        from streamarr.models.setting import Setting  # noqa: F401  (metadata)

        svc = LibraryImportService(db_session)
        genre = Genre(id=999998, name="Test Genre")
        db_session.add(genre)
        await db_session.commit()

        # One unknown id, then a known one - the second must still be linked.
        await svc.import_genres_for_media(
            __import__("uuid").uuid4(), [999996, 999998]
        )
        await db_session.commit()

        assert (await db_session.execute(select(Genre))).scalars().first() is not None
        assert (await db_session.execute(select(MediaItem))).scalars().all() == []
        links = (await db_session.execute(select(media_genre_table))).all()
        assert [link.genre_id for link in links] == [999998]

    async def test_known_genre_with_name_is_created_and_linked(self, db_session):
        from streamarr.models.media import MediaItem, MediaType

        svc = LibraryImportService(db_session)
        item = MediaItem(title="Genre Test", media_type=MediaType.MOVIES)
        db_session.add(item)
        await db_session.commit()

        await svc.import_genres_for_media(item.guid, [{"id": 999997, "name": "Neu"}])
        await db_session.commit()

        created = (
            await db_session.execute(select(Genre).where(Genre.id == 999997))
        ).scalars().first()
        assert created is not None and created.name == "Neu"
        links = (await db_session.execute(select(media_genre_table))).all()
        assert len(links) == 1
