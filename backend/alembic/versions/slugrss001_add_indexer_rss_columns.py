"""add rss/availability columns to indexer

Revision ID: slugrss001
Revises: qualprof001
Create Date: 2026-05-16 17:32:00.000000

Adds per-indexer enable/priority flags and RSS-sync opt-in + bookkeeping.
``rss_enabled`` defaults false so the periodic latest-feed poll is strictly
operator opt-in. Existing rows backfill via server defaults.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "slugrss001"
down_revision: str | Sequence[str] | None = "qualprof001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "indexer",
        sa.Column(
            "enabled", sa.Boolean(), server_default=sa.true(), nullable=False
        ),
    )
    op.add_column(
        "indexer",
        sa.Column(
            "supports_rss",
            sa.Boolean(),
            server_default=sa.true(),
            nullable=False,
        ),
    )
    op.add_column(
        "indexer",
        sa.Column(
            "rss_enabled",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "indexer",
        sa.Column(
            "priority",
            sa.Integer(),
            server_default=sa.text("25"),
            nullable=False,
        ),
    )
    op.add_column(
        "indexer",
        sa.Column("last_rss_sync_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_indexer_enabled", "indexer", ["enabled"])
    op.create_index("ix_indexer_rss_enabled", "indexer", ["rss_enabled"])
    op.create_index("ix_indexer_rss", "indexer", ["enabled", "rss_enabled"])


def downgrade() -> None:
    op.drop_index("ix_indexer_rss", table_name="indexer")
    op.drop_index("ix_indexer_rss_enabled", table_name="indexer")
    op.drop_index("ix_indexer_enabled", table_name="indexer")
    op.drop_column("indexer", "last_rss_sync_at")
    op.drop_column("indexer", "priority")
    op.drop_column("indexer", "rss_enabled")
    op.drop_column("indexer", "supports_rss")
    op.drop_column("indexer", "enabled")
