from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select

from streamarr.models.library import Library
from streamarr.models.media import (
    AvailabilityStatus,
    MediaExternalId,
    MediaFile,
    MediaItem,
    MediaType,
)
from streamarr.services.library_scanner import (
    LibraryScanIncompleteError,
    LibraryScanner,
)


@pytest.mark.asyncio
async def test_reconcile_adds_idempotently_and_marks_removed(db_session, tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    path = root / "Arrival (2016).mkv"
    path.write_bytes(b"media")
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()

    scanner = LibraryScanner(db_session)
    discovered = [{"path": str(path), "title": "Arrival", "year": 2016, "size": 5}]
    first = await scanner.reconcile(library, discovered)
    second = await scanner.reconcile(library, discovered)

    assert first.added == 1
    assert second.added == 0
    assert await db_session.scalar(select(func.count(MediaFile.guid))) == 1
    item = (await db_session.execute(select(MediaItem))).scalar_one()
    assert item.media_type == MediaType.MOVIES
    assert item.availability_status == AvailabilityStatus.AVAILABLE
    media_file = (await db_session.execute(select(MediaFile))).scalar_one()
    assert media_file.library_guid == library.guid

    path.unlink()
    removed = await scanner.reconcile(library, [])
    await db_session.refresh(item)
    assert removed.removed == 1
    assert item.availability_status == AvailabilityStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_fails_closed_on_suspicious_empty_scan(db_session, tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    path = root / "Movie.mkv"
    path.write_bytes(b"media")
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    item = MediaItem(media_type=MediaType.MOVIES, title="Movie")
    db_session.add_all([library, item])
    await db_session.flush()
    db_session.add(
        MediaFile(
            media_item_guid=item.guid,
            library_guid=library.guid,
            file_path=str(path),
        )
    )
    await db_session.commit()

    with pytest.raises(LibraryScanIncompleteError):
        await LibraryScanner(db_session).reconcile(library, [])

    assert await db_session.scalar(select(func.count(MediaFile.guid))) == 1


@pytest.mark.asyncio
async def test_reconcile_rejects_paths_outside_library(db_session, tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    outside = tmp_path / "outside.mkv"
    outside.write_bytes(b"media")
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()

    result = await LibraryScanner(db_session).reconcile(
        library, [{"path": str(outside), "title": "Outside"}]
    )

    assert result.skipped == 1
    assert await db_session.scalar(select(func.count(MediaFile.guid))) == 0


@pytest.mark.asyncio
async def test_reconcile_assigns_episode_hierarchy(db_session, tmp_path):
    root = tmp_path / "shows"
    path = root / "Severance" / "Season 01" / "S01E02.mkv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"media")
    library = Library(
        name="Shows",
        type="SHOWS",
        plugin_id="shows",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()

    await LibraryScanner(db_session).reconcile(
        library,
        [
            {
                "path": str(path),
                "show_name": "Severance",
                "season": 1,
                "episode": 2,
                "episode_end": 3,
            }
        ],
    )

    items = (await db_session.execute(select(MediaItem))).scalars().all()
    by_type = {item.media_type: item for item in items}
    assert by_type[MediaType.SEASONS].parent_guid == by_type[MediaType.SHOWS].guid
    assert by_type[MediaType.EPISODES].parent_guid == by_type[MediaType.SEASONS].guid
    assert by_type[MediaType.EPISODES].sequence_number == 2
    assert by_type[MediaType.EPISODES].extra_data["episode_end"] == 3


@pytest.mark.asyncio
async def test_reconcile_uses_existing_episode_numbers_and_updates_ancestors(
    db_session, tmp_path
):
    root = tmp_path / "shows"
    path = root / "Severance" / "Season 01" / "S01E02.mkv"
    path.parent.mkdir(parents=True)
    path.write_bytes(b"media")
    library = Library(
        name="Shows",
        type="SHOWS",
        plugin_id="shows",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    show = MediaItem(media_type=MediaType.SHOWS, title="Severance")
    db_session.add_all([library, show])
    await db_session.flush()
    season = MediaItem(
        media_type=MediaType.SEASONS,
        title="First Season",
        parent_guid=show.guid,
        sequence_number=1,
    )
    db_session.add(season)
    await db_session.flush()
    episode = MediaItem(
        media_type=MediaType.EPISODES,
        title="Good News About Hell",
        parent_guid=season.guid,
        sequence_number=2,
    )
    db_session.add(episode)
    await db_session.commit()

    scanner = LibraryScanner(db_session)
    await scanner.reconcile(
        library,
        [{"path": str(path), "show_name": "Severance", "season": 1, "episode": 2}],
    )

    assert await db_session.scalar(select(func.count(MediaItem.guid))) == 3
    media_file = (await db_session.execute(select(MediaFile))).scalar_one()
    assert media_file.media_item_guid == episode.guid
    for item in (show, season, episode):
        await db_session.refresh(item)
        assert item.availability_status == AvailabilityStatus.AVAILABLE

    path.unlink()
    await scanner.reconcile(library, [])
    for item in (show, season, episode):
        await db_session.refresh(item)
        assert item.availability_status == AvailabilityStatus.UNKNOWN


@pytest.mark.asyncio
async def test_reconcile_preserves_file_identity_across_rename(db_session, tmp_path):
    root = tmp_path / "movies"
    root.mkdir()
    original = root / "Arrival (2016).mkv"
    original.write_bytes(b"media")
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()
    scanner = LibraryScanner(db_session)

    await scanner.reconcile(library, [{"path": str(original), "title": "Arrival"}])
    media_file = (await db_session.execute(select(MediaFile))).scalar_one()
    original_guid = media_file.guid

    renamed = root / "Arrival (2016) - 4K.mkv"
    original.rename(renamed)
    result = await scanner.reconcile(
        library, [{"path": str(renamed), "title": "Arrival"}]
    )
    media_file = (await db_session.execute(select(MediaFile))).scalar_one()

    assert result.added == 0
    assert result.updated == 1
    assert result.removed == 0
    assert media_file.guid == original_guid
    assert media_file.file_path == str(renamed)


@pytest.mark.asyncio
async def test_reconcile_scopes_removal_to_physical_root(db_session, tmp_path):
    first_root = tmp_path / "movies-a"
    second_root = tmp_path / "movies-b"
    first_root.mkdir()
    second_root.mkdir()
    first_path = first_root / "Arrival.mkv"
    second_path = second_root / "Alien.mkv"
    first_path.write_bytes(b"first")
    second_path.write_bytes(b"second")
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(first_root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()
    scanner = LibraryScanner(db_session)

    await scanner.reconcile(
        library, [{"path": str(first_path), "title": "Arrival"}], root_path=first_root
    )
    await scanner.reconcile(
        library, [{"path": str(second_path), "title": "Alien"}], root_path=second_root
    )
    first_path.unlink()
    result = await scanner.reconcile(library, [], root_path=first_root)
    remaining = (await db_session.execute(select(MediaFile))).scalars().all()

    assert result.removed == 1
    assert [row.file_path for row in remaining] == [str(second_path)]
    assert remaining[0].library_root == str(second_root)


@pytest.mark.asyncio
async def test_reconcile_imports_local_nfo_ids_and_locks(db_session, tmp_path):
    root = tmp_path / "movies"
    folder = root / "Arrival (2016) [tmdbid-329865]"
    folder.mkdir(parents=True)
    path = folder / "Arrival (2016) [tmdbid-329865].mkv"
    path.write_bytes(b"media")
    path.with_suffix(".nfo").write_text(
        """<movie><title>Arrival Local</title><plot>Local plot</plot>"
        "<uniqueid type=\"imdb\">tt2543164</uniqueid>"
        "<lockedfields>Name|Overview</lockedfields></movie>""",
        encoding="utf-8",
    )
    library = Library(
        name="Movies",
        type="MOVIES",
        plugin_id="movies",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()

    await LibraryScanner(db_session).reconcile(
        library, [{"path": str(path), "title": "Arrival", "year": 2016}]
    )
    item = (await db_session.execute(select(MediaItem))).scalar_one()
    external_ids = (await db_session.execute(select(MediaExternalId))).scalars().all()

    assert item.title == "Arrival Local"
    assert item.description == "Local plot"
    assert set(item.extra_data["locked_fields"]) == {"description", "title"}
    assert item.extra_data["metadata_provenance"]["title"] == "local"
    assert {(row.provider, row.external_id) for row in external_ids} == {
        ("imdb", "tt2543164"),
        ("tmdb", "329865"),
    }
