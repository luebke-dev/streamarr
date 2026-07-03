"""Migrate favorites to lists system

Creates a Favorites list for each user who has favorites,
then migrates their favorite entries to list items.

Revision ID: i3j4k5l6m7n8
Revises: 5550f2bafabf
Create Date: 2026-03-22

"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "i3j4k5l6m7n8"
down_revision: str | None = "5550f2bafabf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Mapping from MediaType enum to ListItemType
# Map MediaType to ListItemType enum values (all uppercase)
MEDIA_TYPE_MAP = {
    "MOVIES": "MOVIE",
    "SHOWS": "SHOW",
    "GAMES": "GAME",
    "MUSIC": "MUSIC",
    "BOOKS": "BOOK",
    "AUDIOBOOKS": "AUDIOBOOK",
    "EPISODES": "EPISODE",
    "SEASONS": "SHOW",
    "ARTISTS": "MUSIC",
    "ALBUMS": "MUSIC",
    "SONGS": "MUSIC",
}


def upgrade() -> None:
    # Add new enum values to list_type
    # PostgreSQL requires explicit ALTER TYPE for enums
    op.execute("ALTER TYPE listtype ADD VALUE IF NOT EXISTS 'FAVORITES'")
    op.execute("ALTER TYPE listitemtype ADD VALUE IF NOT EXISTS 'MUSIC'")
    op.execute("ALTER TYPE listitemtype ADD VALUE IF NOT EXISTS 'BOOK'")
    op.execute("ALTER TYPE listitemtype ADD VALUE IF NOT EXISTS 'AUDIOBOOK'")

    # Commit the enum changes before using them
    op.execute("COMMIT")

    conn = op.get_bind()

    # Get all users who have favorites
    users_with_favs = conn.execute(
        sa.text("SELECT DISTINCT user_id FROM favorite")
    ).fetchall()

    now = datetime.now(UTC)

    for (user_id,) in users_with_favs:
        # Create a Favorites list for this user
        list_guid = uuid.uuid4()
        conn.execute(
            sa.text(
                """
                INSERT INTO list (guid, created_at, updated_at, name, list_type, owner_guid, visibility, is_active, auto_update, item_count, like_count, follow_count)
                VALUES (:guid, :now, :now, 'Favorites', 'FAVORITES', :owner, 'PRIVATE', true, false, 0, 0, 0)
                """
            ),
            {"guid": list_guid, "now": now, "owner": user_id},
        )

        # Get all favorites for this user with media type info
        favorites = conn.execute(
            sa.text(
                """
                SELECT f.guid, f.media_item_guid, f.created_at, m.media_type
                FROM favorite f
                JOIN media_item m ON f.media_item_guid = m.guid
                WHERE f.user_id = :user_id
                ORDER BY f.created_at
                """
            ),
            {"user_id": user_id},
        ).fetchall()

        item_count = 0
        for fav_guid, media_guid, fav_created, media_type in favorites:
            item_type = MEDIA_TYPE_MAP.get(media_type, "movie")
            item_guid = uuid.uuid4()

            conn.execute(
                sa.text(
                    """
                    INSERT INTO list_item (guid, created_at, list_guid, item_type, item_guid, added_by_guid)
                    VALUES (:guid, :created_at, :list_guid, :item_type, :item_guid, :added_by)
                    """
                ),
                {
                    "guid": item_guid,
                    "created_at": fav_created or now,
                    "list_guid": list_guid,
                    "item_type": item_type,
                    "item_guid": media_guid,
                    "added_by": user_id,
                },
            )
            item_count += 1

        # Update item count
        conn.execute(
            sa.text("UPDATE list SET item_count = :count WHERE guid = :guid"),
            {"count": item_count, "guid": list_guid},
        )


def downgrade() -> None:
    conn = op.get_bind()

    # Delete all favorites lists and their items (cascade handles items)
    conn.execute(sa.text("DELETE FROM list WHERE list_type = 'favorites'"))

    # Note: we cannot remove enum values in PostgreSQL, so the enum types
    # will keep the new values. This is safe.
