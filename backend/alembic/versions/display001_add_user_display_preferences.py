"""Add display preferences to user.

Revision ID: display001
Revises: photos001
Create Date: 2026-05-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "display001"
down_revision: Union[str, Sequence[str], None] = "photos001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("display_preferences", JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "display_preferences")
