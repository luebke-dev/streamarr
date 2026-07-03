"""Add playback_preferences to user

Revision ID: r2s3t4u5v6w7
Revises: q1r2s3t4u5v6
Create Date: 2026-03-29 23:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 'r2s3t4u5v6w7'
down_revision: Union[str, Sequence[str], None] = 'q1r2s3t4u5v6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add playback_preferences JSONB column for per-user skip settings."""
    op.add_column(
        'user',
        sa.Column('playback_preferences', JSONB, nullable=True),
    )


def downgrade() -> None:
    """Remove playback_preferences column."""
    op.drop_column('user', 'playback_preferences')
