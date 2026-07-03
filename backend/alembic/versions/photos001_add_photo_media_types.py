"""Add photo and home video media types.

Revision ID: photos001
Revises: activity001
Create Date: 2026-05-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op


revision: str = "photos001"
down_revision: Union[str, Sequence[str], None] = "activity001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'PHOTOS'")
    op.execute("ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'HOME_VIDEOS'")


def downgrade() -> None:
    # PostgreSQL enum values cannot be removed safely in-place.
    pass
