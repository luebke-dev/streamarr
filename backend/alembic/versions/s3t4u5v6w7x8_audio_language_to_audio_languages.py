"""Migrate audio_language to audio_languages JSONB list

Revision ID: s3t4u5v6w7x8
Revises: r2s3t4u5v6w7
Create Date: 2026-03-29 23:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = 's3t4u5v6w7x8'
down_revision: Union[str, Sequence[str], None] = 'r2s3t4u5v6w7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add audio_languages JSONB column, migrate data, drop old column."""
    op.add_column(
        'user',
        sa.Column('audio_languages', JSONB, nullable=True),
    )
    # Migrate existing single-value data into a JSON array
    op.execute(
        """UPDATE "user" SET audio_languages = json_build_array(audio_language) WHERE audio_language IS NOT NULL"""
    )
    op.drop_column('user', 'audio_language')


def downgrade() -> None:
    """Restore audio_language column from audio_languages."""
    op.add_column(
        'user',
        sa.Column('audio_language', sa.String(), nullable=True),
    )
    # Take the first element of the list
    op.execute(
        """UPDATE "user" SET audio_language = audio_languages->>0 WHERE audio_languages IS NOT NULL"""
    )
    op.drop_column('user', 'audio_languages')
