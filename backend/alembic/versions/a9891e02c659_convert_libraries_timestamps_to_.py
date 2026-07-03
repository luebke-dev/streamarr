"""convert_libraries_timestamps_to_timezone_aware

Revision ID: a9891e02c659
Revises: 2e0826c32798
Create Date: 2026-01-18 00:22:18.710912

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'a9891e02c659'
down_revision: Union[str, Sequence[str], None] = '2e0826c32798'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # Convert timestamp columns to timezone-aware
    op.execute("""
        ALTER TABLE libraries 
        ALTER COLUMN created_at TYPE timestamp with time zone 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    op.execute("""
        ALTER TABLE libraries 
        ALTER COLUMN updated_at TYPE timestamp with time zone 
        USING updated_at AT TIME ZONE 'UTC'
    """)


def downgrade() -> None:
    """Downgrade schema."""
    # Convert back to timezone-naive
    op.execute("""
        ALTER TABLE libraries 
        ALTER COLUMN created_at TYPE timestamp without time zone 
        USING created_at AT TIME ZONE 'UTC'
    """)
    
    op.execute("""
        ALTER TABLE libraries 
        ALTER COLUMN updated_at TYPE timestamp without time zone 
        USING updated_at AT TIME ZONE 'UTC'
    """)
