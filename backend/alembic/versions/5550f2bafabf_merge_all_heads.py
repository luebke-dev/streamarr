"""merge all heads

Revision ID: 5550f2bafabf
Revises: e7b8c9d0f1a2, f6b7c8d9e0f1, h2i3j4k5l6m7
Create Date: 2026-03-22 09:04:52.541930

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '5550f2bafabf'
down_revision: Union[str, Sequence[str], None] = ('e7b8c9d0f1a2', 'f6b7c8d9e0f1', 'h2i3j4k5l6m7')
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
