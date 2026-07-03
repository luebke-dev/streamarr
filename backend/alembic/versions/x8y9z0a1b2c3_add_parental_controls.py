"""Add parental-control age fields to media_item and user.

Revision ID: x8y9z0a1b2c3
Revises: w7x8y9z0a1b2
Create Date: 2026-04-17 16:00:00.000000

Movies and TV shows get a raw ``content_rating`` string (e.g. "FSK 16",
"PG-13") plus a normalized ``min_age`` integer. The parental-control
filter compares ``min_age`` against the user's ``parental_max_age``;
NULL on either side opts out.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'x8y9z0a1b2c3'
down_revision: Union[str, Sequence[str], None] = 'w7x8y9z0a1b2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'media_item',
        sa.Column('content_rating', sa.String(), nullable=True),
    )
    op.add_column(
        'media_item',
        sa.Column('min_age', sa.Integer(), nullable=True),
    )
    op.create_index(
        op.f('ix_media_item_min_age'),
        'media_item',
        ['min_age'],
        unique=False,
    )
    op.add_column(
        'user',
        sa.Column('parental_max_age', sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column('user', 'parental_max_age')
    op.drop_index(op.f('ix_media_item_min_age'), table_name='media_item')
    op.drop_column('media_item', 'min_age')
    op.drop_column('media_item', 'content_rating')
