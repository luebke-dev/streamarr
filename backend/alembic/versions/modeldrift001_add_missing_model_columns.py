"""Add three mapped columns that never got a migration.

Each of these exists on the model but not in the database, so every query
SQLAlchemy builds for the table selects a column Postgres does not have
and fails with ``UndefinedColumnError``. ``download.error_reason`` was the
visible one: ``refresh_downloads`` runs once a minute and failed on it
every single time.

All three are nullable and unindexed on their models, so they can be added
in place without a backfill or a rewrite of existing rows.

Revision ID: modeldrift001
Revises: libscan002
Create Date: 2026-09-07
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "modeldrift001"
down_revision: str | Sequence[str] | None = "libscan002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("download", sa.Column("error_reason", sa.String(), nullable=True))
    op.add_column(
        "media_release_link",
        sa.Column("blacklisted_reason", sa.String(), nullable=True),
    )
    op.add_column(
        "viewing_history", sa.Column("extra_data", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("viewing_history", "extra_data")
    op.drop_column("media_release_link", "blacklisted_reason")
    op.drop_column("download", "error_reason")
