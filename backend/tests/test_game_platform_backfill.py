"""The GAMES platform backfill (``services.game_platform_backfill``).

Games imported before the platform registry knew a system carry zero ``Platform``
rows, which empties every platform-driven surface (picker, section, filters) even
though the ROMs are present. The backfill rebuilds that from the ROM paths alone
— no metadata provider needed — so it must be correct and safe to re-run.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.models.media import (
    AvailabilityStatus,
    MediaFile,
    MediaItem,
    MediaType,
    media_platform_table,
)
from streamarr.models.platform import Platform
from streamarr.services.game_platform_backfill import backfill_game_platforms


async def _game(db: AsyncSession, title: str, *paths: str, **overrides) -> MediaItem:
    """Create a GAMES item with one MediaFile per path."""
    item = MediaItem(
        guid=uuid.uuid4(),
        title=title,
        media_type=MediaType.GAMES,
        availability_status=AvailabilityStatus.AVAILABLE,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
        **overrides,
    )
    db.add(item)
    await db.flush()
    for path in paths:
        db.add(
            MediaFile(
                guid=uuid.uuid4(),
                media_item_guid=item.guid,
                file_path=path,
                file_name=path.rsplit("/", 1)[-1],
            )
        )
    await db.commit()
    await db.refresh(item)
    return item


async def _platform_names(db: AsyncSession, item_guid: uuid.UUID) -> set[str]:
    """Read an item's platform names straight from the association table.

    Takes a GUID (not an instance) and queries rather than reading
    ``item.platforms``: the relationship is lazy-loaded and a dry run ends in a
    rollback, which expires every instance — both would emit implicit IO that an
    async session forbids.
    """
    rows = await db.execute(
        select(Platform.name)
        .join(
            media_platform_table,
            media_platform_table.c.platform_id == Platform.id,
        )
        .where(media_platform_table.c.media_item_guid == item_guid)
    )
    return set(rows.scalars().all())


class TestPlatformAssignment:
    async def test_assigns_platform_from_rom_directory(self, db_session: AsyncSession):
        # The regression: an Atari .bin must not become "Sega Genesis".
        atari = await _game(
            db_session, "Moon Patrol", "/library/games/roms/atari2600/Moon Patrol.bin"
        )
        genesis = await _game(
            db_session, "Sonic", "/library/games/roms/megadrive/Sonic.bin"
        )
        atari_guid, genesis_guid = atari.guid, genesis.guid

        result = await backfill_game_platforms(db_session)

        assert result.scanned == 2
        assert result.unresolved == 0
        assert await _platform_names(db_session, atari_guid) == {"Atari 2600"}
        assert await _platform_names(db_session, genesis_guid) == {"Sega Genesis"}

    async def test_stamps_canonical_slug_into_extra_data(
        self, db_session: AsyncSession
    ):
        game = await _game(db_session, "Zelda", "/library/games/roms/n64/Zelda.z64")

        await backfill_game_platforms(db_session)

        await db_session.refresh(game)
        assert game.extra_data["platform"] == "n64"

    async def test_multi_platform_game_gets_every_platform(
        self, db_session: AsyncSession
    ):
        game = await _game(
            db_session,
            "Aladdin",
            "/library/games/roms/snes/Aladdin.sfc",
            "/library/games/roms/megadrive/Aladdin.md",
        )
        guid = game.guid

        await backfill_game_platforms(db_session)

        assert await _platform_names(db_session, guid) == {
            "Super Nintendo",
            "Sega Genesis",
        }

    async def test_reuses_existing_platform_row(self, db_session: AsyncSession):
        # An IGDB import may already have created the row; don't duplicate it.
        db_session.add(Platform(name="Nintendo 64", igdb_id=4))
        await db_session.commit()
        game = await _game(db_session, "Mario", "/library/games/roms/n64/Mario.z64")
        guid = game.guid

        result = await backfill_game_platforms(db_session)

        assert "Nintendo 64" not in result.platforms_created
        assert await _platform_names(db_session, guid) == {"Nintendo 64"}
        count = (
            await db_session.execute(
                select(func.count(Platform.id)).where(Platform.name == "Nintendo 64")
            )
        ).scalar_one()
        assert count == 1

    async def test_falls_back_to_existing_extra_data_hint(
        self, db_session: AsyncSession
    ):
        # No platform derivable from the path (no ROM-set directory, unknown
        # extension), but an earlier import left a platform hint.
        game = await _game(
            db_session,
            "Some Switch Game",
            "/library/games/imported/some-game/data.unknownext",
            extra_data={"platform": "Switch"},
        )
        guid = game.guid

        await backfill_game_platforms(db_session)

        assert await _platform_names(db_session, guid) == {"Nintendo Switch"}

    async def test_unresolvable_item_is_counted_not_crashed(
        self, db_session: AsyncSession
    ):
        await _game(db_session, "Mystery", "/library/games/weird/thing.qqq")

        result = await backfill_game_platforms(db_session)

        assert result.unresolved == 1
        assert result.platforms_assigned == 0


class TestBiosPruning:
    async def test_bios_only_item_removed(self, db_session: AsyncSession):
        bios = await _game(
            db_session, "scph1001", "/library/games/roms/bios/psx/scph1001.bin"
        )

        result = await backfill_game_platforms(db_session)

        assert result.bios_removed == 1
        assert (
            await db_session.execute(
                select(MediaItem).where(MediaItem.guid == bios.guid)
            )
        ).scalars().first() is None

    async def test_bios_files_directory_variant_removed(
        self, db_session: AsyncSession
    ):
        await _game(
            db_session,
            "scph5502",
            "/library/games/roms/bios/psx/scph5502.bin",
            "/library/games/roms/psx/BIOS Files/scph5502.bin",
        )

        result = await backfill_game_platforms(db_session)

        assert result.bios_removed == 1

    async def test_real_game_never_removed(self, db_session: AsyncSession):
        game = await _game(db_session, "Zelda", "/library/games/roms/n64/Zelda.z64")
        guid = game.guid

        result = await backfill_game_platforms(db_session)

        assert result.bios_removed == 0
        assert await _platform_names(db_session, guid) == {"Nintendo 64"}

    async def test_remove_bios_can_be_disabled(self, db_session: AsyncSession):
        bios = await _game(
            db_session, "scph1001", "/library/games/roms/bios/psx/scph1001.bin"
        )

        result = await backfill_game_platforms(db_session, remove_bios=False)

        assert result.bios_removed == 0
        assert (
            await db_session.execute(
                select(MediaItem).where(MediaItem.guid == bios.guid)
            )
        ).scalars().first() is not None


class TestSafety:
    async def test_is_idempotent(self, db_session: AsyncSession):
        await _game(db_session, "Zelda", "/library/games/roms/n64/Zelda.z64")
        await _game(db_session, "Sonic", "/library/games/roms/megadrive/Sonic.md")

        first = await backfill_game_platforms(db_session)
        second = await backfill_game_platforms(db_session)

        assert first.platforms_assigned == 2
        assert second.platforms_assigned == 0
        assert second.platforms_created == []
        assert second.bios_removed == 0

    async def test_dry_run_persists_nothing(self, db_session: AsyncSession):
        game = await _game(db_session, "Zelda", "/library/games/roms/n64/Zelda.z64")
        guid = game.guid
        await _game(
            db_session, "scph1001", "/library/games/roms/bios/psx/scph1001.bin"
        )

        result = await backfill_game_platforms(db_session, dry_run=True)

        # Reported as if applied...
        assert result.platforms_assigned == 1
        assert result.bios_removed == 1
        # ...but nothing was written.
        assert await _platform_names(db_session, guid) == set()
        remaining = (
            await db_session.execute(
                select(func.count(MediaItem.guid)).where(
                    MediaItem.media_type == MediaType.GAMES
                )
            )
        ).scalar_one()
        assert remaining == 2

    async def test_ignores_non_game_media_types(self, db_session: AsyncSession):
        movie = MediaItem(
            guid=uuid.uuid4(),
            title="The Matrix",
            media_type=MediaType.MOVIES,
            availability_status=AvailabilityStatus.AVAILABLE,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        db_session.add(movie)
        await db_session.commit()
        guid = movie.guid

        result = await backfill_game_platforms(db_session)

        assert result.scanned == 0
        assert await _platform_names(db_session, guid) == set()

    async def test_empty_library_is_a_noop(self, db_session: AsyncSession):
        result = await backfill_game_platforms(db_session)

        assert result.scanned == 0
        assert result.platforms_assigned == 0
