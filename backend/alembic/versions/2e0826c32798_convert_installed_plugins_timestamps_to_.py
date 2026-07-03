"""Convert installed_plugins timestamps to timezone-aware

Revision ID: 2e0826c32798
Revises: 7aae23857229
Create Date: 2026-01-17 22:58:19.017915

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '2e0826c32798'
down_revision: Union[str, Sequence[str], None] = '7aae23857229'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    pass


def downgrade() -> None:
    """Downgrade schema."""
    pass
