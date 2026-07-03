"""Add email_verified column to user table

Existing users are set to email_verified=True since they were already
active before this feature was introduced.

Revision ID: d6a7b8c9e0f1
Revises: c3d4e5f6a7b8
Create Date: 2026-03-18
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d6a7b8c9e0f1"
down_revision: Union[str, Sequence[str], None] = "c3d4e5f6a7b8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add column with server_default=True so existing rows get True
    op.add_column(
        "user",
        sa.Column(
            "email_verified",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    # Remove server_default after backfill — new users should get False from the ORM
    op.alter_column("user", "email_verified", server_default=None)


def downgrade() -> None:
    op.drop_column("user", "email_verified")
