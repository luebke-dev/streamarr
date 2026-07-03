"""Drop installed_plugins table

Revision ID: k5l6m7n8o9p0
Revises: j4k5l6m7n8o9
Create Date: 2026-03-22

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "k5l6m7n8o9p0"
down_revision: str | None = "j4k5l6m7n8o9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_table("installed_plugins")


def downgrade() -> None:
    op.create_table(
        "installed_plugins",
        sa.Column("guid", sa.Uuid(), nullable=False),
        sa.Column("domain", sa.String(), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("configured", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("builtin", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("config", sa.JSON(), nullable=True),
        sa.Column("version", sa.String(), nullable=True),
        sa.Column(
            "installed_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index("ix_installed_plugins_domain", "installed_plugins", ["domain"], unique=True)
    op.create_index("ix_installed_plugins_enabled", "installed_plugins", ["enabled"])
    op.create_index("ix_installed_plugins_configured", "installed_plugins", ["configured"])
