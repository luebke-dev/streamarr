"""Replace dead media_item library index with type/created index

Revision ID: idxrfr001
Revises: uniqcon001
Create Date: 2026-07-03 00:00:00.000000

The ``library_guid`` column on ``media_item`` is dead: the model no longer maps
it and it is always NULL, so the leading column of
``ix_media_item_library_type_created`` made that index unusable for the most
common list query (filter by ``media_type`` sorted by ``created_at``). Drop the
dead index, the FK and the column, and create a matching
``ix_media_item_type_created`` index instead.
"""

import sqlalchemy as sa

from alembic import op

revision = "idxrfr001"
down_revision = "uniqcon001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_media_item_library_type_created")
    op.execute(
        "ALTER TABLE media_item "
        "DROP CONSTRAINT IF EXISTS media_item_library_guid_fkey"
    )
    op.execute("ALTER TABLE media_item DROP COLUMN IF EXISTS library_guid")
    op.create_index(
        "ix_media_item_type_created",
        "media_item",
        ["media_type", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_media_item_type_created", table_name="media_item")
    op.add_column(
        "media_item",
        sa.Column("library_guid", sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        "media_item_library_guid_fkey",
        "media_item",
        "libraries",
        ["library_guid"],
        ["guid"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_media_item_library_type_created",
        "media_item",
        ["library_guid", "media_type", "created_at"],
    )
