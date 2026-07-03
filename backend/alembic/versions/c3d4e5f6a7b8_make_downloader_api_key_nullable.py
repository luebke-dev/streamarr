"""Make downloader api_key nullable

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-03-15 01:00:00.000000

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision: str = "c3d4e5f6a7b8"
down_revision: Union[str, Sequence[str], None] = "b2c3d4e5f6a7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column("downloader", "api_key", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    op.execute("UPDATE downloader SET api_key = '' WHERE api_key IS NULL")
    op.alter_column("downloader", "api_key", existing_type=sa.String(), nullable=False)
