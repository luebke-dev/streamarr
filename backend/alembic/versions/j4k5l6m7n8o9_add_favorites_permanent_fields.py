"""Add favorites_permanent to group and user models

Revision ID: j4k5l6m7n8o9
Revises: i3j4k5l6m7n8
Create Date: 2026-03-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "j4k5l6m7n8o9"
down_revision: str | None = "i3j4k5l6m7n8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "group",
        sa.Column("favorites_permanent", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column(
        "user",
        sa.Column("favorites_permanent", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "favorites_permanent")
    op.drop_column("group", "favorites_permanent")
