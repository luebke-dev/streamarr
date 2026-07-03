"""Add person and media_cast tables

Revision ID: b3f5a7c91d42
Revises: a9891e02c659
Create Date: 2026-02-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'b3f5a7c91d42'
down_revision: Union[str, Sequence[str], None] = 'a9891e02c659'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create person and media_cast tables for actor/crew tracking."""
    # Create person table
    op.create_table('person',
        sa.Column('guid', sa.Uuid(), nullable=False),
        sa.Column('tmdb_id', sa.Integer(), nullable=True),
        sa.Column('name', sa.String(), nullable=False),
        sa.Column('profile_path', sa.String(), nullable=True),
        sa.Column('known_for_department', sa.String(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint('guid'),
        sa.UniqueConstraint('tmdb_id'),
    )
    op.create_index(op.f('ix_person_name'), 'person', ['name'], unique=False)
    op.create_index(op.f('ix_person_tmdb_id'), 'person', ['tmdb_id'], unique=True)

    # Create media_cast table
    op.create_table('media_cast',
        sa.Column('guid', sa.Uuid(), nullable=False),
        sa.Column('media_item_guid', sa.Uuid(), nullable=False),
        sa.Column('person_guid', sa.Uuid(), nullable=False),
        sa.Column('character', sa.String(), nullable=True),
        sa.Column('department', sa.String(), nullable=True),
        sa.Column('job', sa.String(), nullable=True),
        sa.Column('cast_order', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['media_item_guid'], ['media_item.guid'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['person_guid'], ['person.guid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('guid'),
    )
    op.create_index(op.f('ix_media_cast_media_item_guid'), 'media_cast', ['media_item_guid'], unique=False)
    op.create_index(op.f('ix_media_cast_person_guid'), 'media_cast', ['person_guid'], unique=False)


def downgrade() -> None:
    """Drop media_cast and person tables."""
    op.drop_index(op.f('ix_media_cast_person_guid'), table_name='media_cast')
    op.drop_index(op.f('ix_media_cast_media_item_guid'), table_name='media_cast')
    op.drop_table('media_cast')

    op.drop_index(op.f('ix_person_tmdb_id'), table_name='person')
    op.drop_index(op.f('ix_person_name'), table_name='person')
    op.drop_table('person')
