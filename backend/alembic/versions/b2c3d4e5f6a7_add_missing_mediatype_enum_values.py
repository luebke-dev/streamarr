"""Add missing mediatype enum values

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-03-15 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2c3d4e5f6a7"
down_revision: Union[str, Sequence[str], None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Values that need to be added to the existing 'mediatype' PostgreSQL enum.
# Existing values: MOVIES, SHOWS, GAMES, MUSIC, BOOKS, AUDIOBOOKS
NEW_VALUES = ["SEASONS", "EPISODES", "ARTISTS", "ALBUMS", "SONGS", "AUDIOBOOK_CHAPTERS"]


def upgrade() -> None:
    for value in NEW_VALUES:
        op.execute(f"ALTER TYPE mediatype ADD VALUE IF NOT EXISTS '{value}'")


def downgrade() -> None:
    # PostgreSQL does not support removing individual enum values.
    # A full enum recreation would be required which is risky; leave as-is.
    pass
