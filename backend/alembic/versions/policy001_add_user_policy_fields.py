"""Add user policy override fields.

Revision ID: policy001
Revises: qc001
Create Date: 2026-05-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "policy001"
down_revision: Union[str, Sequence[str], None] = "qc001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("remote_access_enabled", sa.Boolean(), nullable=True),
    )
    op.add_column(
        "user",
        sa.Column("access_schedules", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "access_schedules")
    op.drop_column("user", "remote_access_enabled")
