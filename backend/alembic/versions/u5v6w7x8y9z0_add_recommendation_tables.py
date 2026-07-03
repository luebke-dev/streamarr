"""Add recommendation tables: user_profile_vector + list.context_item_guid

Revision ID: u5v6w7x8y9z0
Revises: t4u5v6w7x8y9
Create Date: 2026-04-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = 'u5v6w7x8y9z0'
down_revision: Union[str, Sequence[str], None] = 't4u5v6w7x8y9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Per-user recommendation system v1.

    Recommendations themselves live in per-user System Lists (table `list`
    with list_type=SYSTEM, auto_update=True, owner_guid=user.guid), so no
    dedicated cache table is needed. This migration only adds:

    - `user_profile_vector`: per-(user, media_type) feature vector used by
      the builder to rank candidates. Working material, not read hot.
    - `list.context_item_guid`: optional anchor for "Because you watched X"
      lists; FK to media_item with ON DELETE CASCADE so orphan lists die
      with the anchor.
    """
    op.create_table(
        'user_profile_vector',
        sa.Column('user_guid', sa.Uuid(), nullable=False),
        sa.Column('media_type', sa.String(), nullable=False),
        sa.Column('genre_weights', JSONB, nullable=True),
        sa.Column('top_cast_guids', JSONB, nullable=True),
        sa.Column('language_weights', JSONB, nullable=True),
        sa.Column('friend_guids', JSONB, nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['user_guid'], ['user.guid'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('user_guid', 'media_type', name='pk_user_profile_vector'),
    )
    op.create_index(
        'ix_user_profile_vector_user_guid',
        'user_profile_vector',
        ['user_guid'],
    )
    op.create_index(
        'ix_user_profile_vector_media_type',
        'user_profile_vector',
        ['media_type'],
    )

    op.add_column(
        'list',
        sa.Column('context_item_guid', sa.Uuid(), nullable=True),
    )
    op.create_foreign_key(
        'fk_list_context_item_guid',
        'list',
        'media_item',
        ['context_item_guid'],
        ['guid'],
        ondelete='CASCADE',
    )
    op.create_index(
        'ix_list_context_item_guid',
        'list',
        ['context_item_guid'],
    )


def downgrade() -> None:
    op.drop_index('ix_list_context_item_guid', table_name='list')
    op.drop_constraint('fk_list_context_item_guid', 'list', type_='foreignkey')
    op.drop_column('list', 'context_item_guid')

    op.drop_index('ix_user_profile_vector_media_type', table_name='user_profile_vector')
    op.drop_index('ix_user_profile_vector_user_guid', table_name='user_profile_vector')
    op.drop_table('user_profile_vector')
