"""add newznab_category_id to indexer_category

Revision ID: c1d2e3f4a5b6
Revises: b3f5a7c91d42
Create Date: 2026-02-17 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'c1d2e3f4a5b6'
down_revision: Union[str, Sequence[str], None] = 'b3f5a7c91d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'indexer_category',
        sa.Column('newznab_category_id', sa.Integer(), nullable=True, index=True),
    )


def downgrade() -> None:
    op.drop_column('indexer_category', 'newznab_category_id')
