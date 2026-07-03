"""Add person biography and metadata import fields

Revision ID: g1h2i3j4k5l6
Revises: b3f5a7c91d42
Create Date: 2026-03-22 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = 'g1h2i3j4k5l6'
down_revision: Union[str, Sequence[str], None] = 'b3f5a7c91d42'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('person', sa.Column('biography', sa.Text(), nullable=True))
    op.add_column('person', sa.Column('birthday', sa.Date(), nullable=True))
    op.add_column('person', sa.Column('deathday', sa.Date(), nullable=True))
    op.add_column('person', sa.Column('place_of_birth', sa.String(), nullable=True))
    op.add_column('person', sa.Column('homepage', sa.String(), nullable=True))
    op.add_column('person', sa.Column('metadata_imported', sa.Boolean(), nullable=False, server_default='false'))
    op.add_column('person', sa.Column('metadata_imported_at', sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column('person', 'metadata_imported_at')
    op.drop_column('person', 'metadata_imported')
    op.drop_column('person', 'homepage')
    op.drop_column('person', 'place_of_birth')
    op.drop_column('person', 'deathday')
    op.drop_column('person', 'birthday')
    op.drop_column('person', 'biography')
