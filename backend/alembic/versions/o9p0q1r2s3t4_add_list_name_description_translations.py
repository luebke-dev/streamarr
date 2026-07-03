"""Add name_translations and description_translations to list

Revision ID: o9p0q1r2s3t4
Revises: n8o9p0q1r2s3
Create Date: 2026-03-28 12:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB
from alembic import op

# revision identifiers, used by Alembic.
revision: str = 'o9p0q1r2s3t4'
down_revision: Union[str, Sequence[str], None] = 'n8o9p0q1r2s3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('list', sa.Column('name_translations', JSONB, nullable=True))
    op.add_column('list', sa.Column('description_translations', JSONB, nullable=True))


def downgrade() -> None:
    op.drop_column('list', 'description_translations')
    op.drop_column('list', 'name_translations')
