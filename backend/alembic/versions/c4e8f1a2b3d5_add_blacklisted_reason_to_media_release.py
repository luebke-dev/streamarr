"""Add blacklisted_reason to media_release

Revision ID: c4e8f1a2b3d5
Revises: 7aae23857229
Create Date: 2026-03-06 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c4e8f1a2b3d5'
down_revision: Union[str, Sequence[str], None] = 'a5b6c7d8e9f0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add blacklisted_reason column to media_release."""
    op.add_column(
        'media_release',
        sa.Column('blacklisted_reason', sa.String(), nullable=True),
    )
    op.create_index(
        op.f('ix_media_release_blacklisted_reason'),
        'media_release',
        ['blacklisted_reason'],
    )


def downgrade() -> None:
    """Remove blacklisted_reason column from media_release."""
    op.drop_index(op.f('ix_media_release_blacklisted_reason'), table_name='media_release')
    op.drop_column('media_release', 'blacklisted_reason')
