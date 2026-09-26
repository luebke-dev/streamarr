"""Games-library ingest: BIOS exclusion + platform rows at scan time.

Two defects made the games library unusable even with every ROM present:

* the scanner ingested BIOS/firmware images (they share the ROM extensions), so
  the library filled up with "titles" like ``scph1001``; and
* ingest only wrote an ``extra_data.platform`` hint, never a ``Platform`` row —
  and the platform picker, the "Platforms" page section and ``?platform_id=``
  filters all read the association table, so every platform surface was empty.

Both are locked here, against the real ROM-set directory layout.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from streamarr.libraries.games import GameLibraryPlugin
from streamarr.models.library import Library
from streamarr.models.media import MediaItem, MediaType, media_platform_table
from streamarr.models.platform import Platform
from streamarr.services.library_scanner import LibraryScanner


def _rom_set(tmp_path):
    """A miniature multi-system ROM collection, BIOS files included."""
    root = tmp_path / "games"
    for rel, payload in {
        "roms/n64/Super Mario 64 (Europe).z64": b"rom",
        "roms/atari2600/Moon Patrol (1983) (CCE).bin": b"rom",
        "roms/megadrive/Sonic (Europe).md": b"rom",
        "roms/gamegear/Sonic (Europe).gg": b"rom",
        # Support data that must never become a game.
        "roms/bios/psx/scph1001.bin": b"bios",
        "roms/psx/BIOS Files/scph5502.bin": b"bios",
    }.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
    return root


async def _games_library(db_session, root) -> Library:
    library = Library(
        name="Spiele",
        type="GAMES",
        plugin_id="games",
        path=str(root),
        enabled=True,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    db_session.add(library)
    await db_session.commit()
    return library


async def _platforms_of(db_session, title: str) -> set[str]:
    item = (
        await db_session.execute(select(MediaItem).where(MediaItem.title == title))
    ).scalars().first()
    assert item is not None, f"expected an item titled {title!r}"
    rows = await db_session.execute(
        select(Platform.name)
        .join(media_platform_table, media_platform_table.c.platform_id == Platform.id)
        .where(media_platform_table.c.media_item_guid == item.guid)
    )
    return set(rows.scalars().all())


class TestScanSkipsSupportFiles:
    @pytest.mark.asyncio
    async def test_bios_files_are_not_discovered(self, tmp_path):
        root = _rom_set(tmp_path)

        discovered = await GameLibraryPlugin().scan_library(str(root))

        paths = {entry["path"] for entry in discovered}
        assert not any("/bios/" in p or "/BIOS Files/" in p for p in paths)
        assert len(discovered) == 4

    @pytest.mark.asyncio
    async def test_real_roms_still_discovered(self, tmp_path):
        root = _rom_set(tmp_path)

        discovered = await GameLibraryPlugin().scan_library(str(root))

        assert {entry["title"] for entry in discovered} == {
            "Super Mario 64",
            "Moon Patrol",
            "Sonic",
        }

    @pytest.mark.asyncio
    async def test_platform_comes_from_rom_set_directory(self, tmp_path):
        root = _rom_set(tmp_path)

        discovered = await GameLibraryPlugin().scan_library(str(root))

        by_ext = {entry["extension"]: entry["platform"] for entry in discovered}
        # The regression: .bin under atari2600/ is not a Mega Drive ROM.
        assert by_ext[".bin"] == "atari2600"
        assert by_ext[".md"] == "genesis"
        assert by_ext[".gg"] == "gamegear"
        assert by_ext[".z64"] == "n64"


class TestIngestPersistsPlatforms:
    @pytest.mark.asyncio
    async def test_reconcile_creates_platform_rows(self, db_session, tmp_path):
        root = _rom_set(tmp_path)
        library = await _games_library(db_session, root)
        discovered = await GameLibraryPlugin().scan_library(str(root))

        await LibraryScanner(db_session).reconcile(library, discovered)

        assert await _platforms_of(db_session, "Super Mario 64") == {"Nintendo 64"}
        assert await _platforms_of(db_session, "Moon Patrol") == {"Atari 2600"}

    @pytest.mark.asyncio
    async def test_reconcile_is_idempotent(self, db_session, tmp_path):
        root = _rom_set(tmp_path)
        library = await _games_library(db_session, root)
        discovered = await GameLibraryPlugin().scan_library(str(root))
        scanner = LibraryScanner(db_session)

        first = await scanner.reconcile(library, discovered)
        second = await scanner.reconcile(library, discovered)

        assert first.added == 4
        assert second.added == 0
        # No duplicate association rows on a re-scan.
        assert await _platforms_of(db_session, "Super Mario 64") == {"Nintendo 64"}

    @pytest.mark.asyncio
    async def test_bios_never_becomes_a_media_item(self, db_session, tmp_path):
        root = _rom_set(tmp_path)
        library = await _games_library(db_session, root)
        discovered = await GameLibraryPlugin().scan_library(str(root))

        await LibraryScanner(db_session).reconcile(library, discovered)

        titles = set(
            (
                await db_session.execute(
                    select(MediaItem.title).where(
                        MediaItem.media_type == MediaType.GAMES
                    )
                )
            ).scalars().all()
        )
        assert not {t for t in titles if t.lower().startswith("scph")}

    @pytest.mark.asyncio
    async def test_platform_row_is_reused_across_games(self, db_session, tmp_path):
        root = _rom_set(tmp_path)
        (root / "roms/n64/Zelda (Europe).z64").write_bytes(b"rom")
        library = await _games_library(db_session, root)
        discovered = await GameLibraryPlugin().scan_library(str(root))

        await LibraryScanner(db_session).reconcile(library, discovered)

        rows = (
            await db_session.execute(
                select(Platform).where(Platform.name == "Nintendo 64")
            )
        ).scalars().all()
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_retro_profile_still_stamped(self, db_session, tmp_path):
        root = _rom_set(tmp_path)
        library = await _games_library(db_session, root)
        discovered = await GameLibraryPlugin().scan_library(str(root))

        await LibraryScanner(db_session).reconcile(library, discovered)

        item = (
            await db_session.execute(
                select(MediaItem).where(MediaItem.title == "Super Mario 64")
            )
        ).scalars().first()
        assert item.extra_data["lightrays"]["profile"] == "retro"
        assert item.extra_data["platform"] == "n64"
