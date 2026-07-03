"""Add partial unique indexes to close check-then-insert races.

Revision ID: v6w7x8y9z0a1
Revises: u5v6w7x8y9z0
Create Date: 2026-04-17 14:00:00.000000

Two check-then-insert sites could produce duplicates under concurrency:

- ``media_marker``: ``create_marker`` for intro/outro/credits does read-then-
  update-or-insert. A partial unique index on the repeatable-marker subset
  lets ``INSERT ... ON CONFLICT DO UPDATE`` serialise the write at the DB
  level. SONG/AD markers are intentionally repeatable and stay outside
  the constraint.
- ``list``: trending system lists are singletons keyed on
  ``(list_type=SYSTEM, update_source)``. A partial unique index on
  ``update_source`` for SYSTEM lists makes the scheduler idempotent.
"""
from typing import Sequence, Union

from alembic import op


revision: str = 'v6w7x8y9z0a1'
down_revision: Union[str, Sequence[str], None] = 'u5v6w7x8y9z0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        'uq_media_marker_unique_types',
        'media_marker',
        ['media_item_guid', 'marker_type', 'source'],
        unique=True,
        postgresql_where="marker_type IN ('intro', 'outro', 'credits')",
    )
    op.create_index(
        'uq_list_system_update_source',
        'list',
        ['update_source'],
        unique=True,
        postgresql_where="list_type = 'SYSTEM' AND update_source IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_index('uq_list_system_update_source', table_name='list')
    op.drop_index('uq_media_marker_unique_types', table_name='media_marker')
