"""Add platform table and media_platform association

Revision ID: q1r2s3t4u5v6
Revises: p0q1r2s3t4u5
Create Date: 2026-03-29 14:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'q1r2s3t4u5v6'
down_revision: Union[str, Sequence[str], None] = 'p0q1r2s3t4u5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'platform',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('logo_url', sa.String(), nullable=True),
        sa.Column('igdb_id', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name'),
    )
    op.create_index('ix_platform_name', 'platform', ['name'])

    op.create_table(
        'media_platform',
        sa.Column('media_item_guid', sa.Uuid(), nullable=False),
        sa.Column('platform_id', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['platform_id'], ['platform.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('media_item_guid', 'platform_id'),
    )


def downgrade() -> None:
    op.drop_table('media_platform')
    op.drop_index('ix_platform_name', table_name='platform')
    op.drop_table('platform')
