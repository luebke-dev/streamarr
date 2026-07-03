"""add monitored columns to media_item

Revision ID: favmon001
Revises: enumfix001
Create Date: 2026-05-16 17:30:00.000000

Adds the "monitored" concept used by favorites auto-download / upgrades.
A media item (and its whole subtree) becomes monitored when favorited by a
user with effective ``favorites_permanent``. The one-time backfill marks the
existing favorited lineage so retention is correct immediately after deploy.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "favmon001"
down_revision: str | Sequence[str] | None = "enumfix001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "media_item",
        sa.Column(
            "monitored",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "media_item", sa.Column("monitored_source", sa.String(), nullable=True)
    )
    op.add_column(
        "media_item",
        sa.Column("monitored_reconciled_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_media_item_monitored", "media_item", ["monitored"])

    # Backfill: monitor every favorited root and its whole descendant subtree
    # (mirrors storage_cleanup._collect_favorited_lineage, but walking down).
    op.execute(
        sa.text(
            """
            WITH RECURSIVE fav_roots AS (
                SELECT li.item_guid AS guid
                FROM list_item li
                JOIN list l ON l.guid = li.list_guid
                WHERE l.list_type = 'FAVORITES'
            ),
            subtree AS (
                SELECT mi.guid
                FROM media_item mi
                WHERE mi.guid IN (SELECT guid FROM fav_roots)
                UNION
                SELECT child.guid
                FROM media_item child
                JOIN subtree s ON child.parent_guid = s.guid
            )
            UPDATE media_item
            SET monitored = true,
                monitored_source = 'favorite',
                monitored_reconciled_at = now()
            WHERE guid IN (SELECT guid FROM subtree)
            """
        )
    )

    # Match the model (client-side default only, no server default).
    op.alter_column("media_item", "monitored", server_default=None)


def downgrade() -> None:
    op.drop_index("ix_media_item_monitored", table_name="media_item")
    op.drop_column("media_item", "monitored_reconciled_at")
    op.drop_column("media_item", "monitored_source")
    op.drop_column("media_item", "monitored")
