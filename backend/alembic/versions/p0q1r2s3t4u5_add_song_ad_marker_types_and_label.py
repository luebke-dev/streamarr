"""Add song/ad marker types and label column

Revision ID: p0q1r2s3t4u5
Revises: o9p0q1r2s3t4
Create Date: 2026-03-29 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'p0q1r2s3t4u5'
down_revision: Union[str, Sequence[str], None] = 'o9p0q1r2s3t4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new enum values to markertype
    op.execute("ALTER TYPE markertype ADD VALUE IF NOT EXISTS 'song'")
    op.execute("ALTER TYPE markertype ADD VALUE IF NOT EXISTS 'ad'")

    # Add label column
    op.add_column('media_marker', sa.Column('label', sa.String(), nullable=True))

    # Drop the unique constraint so song/ad markers can have multiples
    op.execute("""
        ALTER TABLE media_marker
        DROP CONSTRAINT IF EXISTS uq_media_marker_item_type_source
    """)


def downgrade() -> None:
    # Re-add unique constraint
    op.create_unique_constraint(
        'uq_media_marker_item_type_source',
        'media_marker',
        ['media_item_guid', 'marker_type', 'source'],
    )
    op.drop_column('media_marker', 'label')
    # Note: PostgreSQL doesn't support removing enum values
