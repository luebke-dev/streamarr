"""Add indexes for MediaItem.sequence_number and composite lookup paths.

Revision ID: w7x8y9z0a1b2
Revises: v6w7x8y9z0a1
Create Date: 2026-04-17 15:30:00.000000

Hot paths that were table-scanning:

- ``MediaItem.sequence_number`` feeds ``ORDER BY`` on episode/track lists and
  several ``WHERE sequence_number = ?`` lookups for seasons/episodes.
- ``MediaExternalId (provider, external_id)`` is always queried together
  (search-by-tmdb-id, get_by_external_id) — a composite index beats two
  single-column indexes for the AND case.
- ``MediaItem (parent_guid, sequence_number)`` serves episode navigation
  (next/previous episode in a season) without sorting a full season set.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'w7x8y9z0a1b2'
down_revision: Union[str, Sequence[str], None] = 'v6w7x8y9z0a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        op.f('ix_media_item_sequence_number'),
        'media_item',
        ['sequence_number'],
        unique=False,
    )
    op.create_index(
        'ix_media_external_id_provider_external',
        'media_external_id',
        ['provider', 'external_id'],
        unique=False,
    )
    op.create_index(
        'ix_media_item_parent_sequence',
        'media_item',
        ['parent_guid', 'sequence_number'],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index('ix_media_item_parent_sequence', table_name='media_item')
    op.drop_index('ix_media_external_id_provider_external', table_name='media_external_id')
    op.drop_index(op.f('ix_media_item_sequence_number'), table_name='media_item')
