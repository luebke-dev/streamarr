"""add speed_bps to download

Revision ID: slugspd001
Revises: slugupg001
Create Date: 2026-05-16 18:30:00.000000

Stores the live download speed (bytes/sec) polled from the downloader so
the UI can show throughput. Paused state is represented via the existing
``status`` column ("Paused"), so no extra boolean is needed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "slugspd001"
down_revision: str | Sequence[str] | None = "slugupg001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download",
        sa.Column("speed_bps", sa.BigInteger(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("download", "speed_bps")
