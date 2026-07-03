"""Add deleted_at to list for soft delete

Revision ID: f6b7c8d9e0f1
Revises: e6f7a8b9c0d1
Create Date: 2026-03-22 06:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'f6b7c8d9e0f1'
down_revision: Union[str, Sequence[str], None] = 'e6f7a8b9c0d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Use raw SQL with IF NOT EXISTS since column may already exist
    # (was added manually before this migration was created)
    op.execute("ALTER TABLE list ADD COLUMN IF NOT EXISTS deleted_at TIMESTAMPTZ")
    op.execute("CREATE INDEX IF NOT EXISTS ix_list_deleted_at ON list (deleted_at)")


def downgrade() -> None:
    op.drop_index('ix_list_deleted_at', table_name='list')
    op.drop_column('list', 'deleted_at')
