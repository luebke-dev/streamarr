"""Add chromaprint_raw to media_file

Revision ID: n8o9p0q1r2s3
Revises: m7n8o9p0q1r2
Create Date: 2026-03-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'n8o9p0q1r2s3'
down_revision: Union[str, Sequence[str], None] = 'm7n8o9p0q1r2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add chromaprint_raw column for cached audio fingerprints."""
    op.add_column(
        'media_file',
        sa.Column('chromaprint_raw', sa.String(), nullable=True),
    )


def downgrade() -> None:
    """Remove chromaprint_raw column."""
    op.drop_column('media_file', 'chromaprint_raw')
