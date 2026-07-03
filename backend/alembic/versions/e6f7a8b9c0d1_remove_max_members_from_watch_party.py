"""Remove max_members from watch_party

Revision ID: e6f7a8b9c0d1
Revises: d5f6a7b8c9e0
Create Date: 2026-03-12 20:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'e6f7a8b9c0d1'
down_revision: Union[str, Sequence[str], None] = 'd5f6a7b8c9e0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_column('watch_party', 'max_members')


def downgrade() -> None:
    op.add_column(
        'watch_party',
        sa.Column('max_members', sa.Integer(), nullable=False, server_default='10'),
    )
