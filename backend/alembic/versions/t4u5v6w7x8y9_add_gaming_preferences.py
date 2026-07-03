"""Add gaming_preferences to user

Revision ID: t4u5v6w7x8y9
Revises: s3t4u5v6w7x8
Create Date: 2026-04-12 20:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 't4u5v6w7x8y9'
down_revision: Union[str, Sequence[str], None] = 's3t4u5v6w7x8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add gaming_preferences JSONB column for per-user Lightrays/GOW settings.

    Stores keyboard_layout (XKB layout, e.g. 'de' / 'us') and mouse_speed
    (float multiplier, 1.0 = default) so the gaming settings page can
    persist them and lightrays.launch_session can inject them into the
    spawned Wolf/GOW container.
    """
    op.add_column(
        'user',
        sa.Column('gaming_preferences', JSONB, nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user', 'gaming_preferences')
