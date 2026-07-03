"""Add composite indexes for media queries

Revision ID: a1b2c3d4e5f6
Revises: f5a6b7c8d9e1
Create Date: 2025-01-01 00:00:00.000000

"""

from typing import Sequence, Union

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "f5a6b7c8d9e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add composite indexes to speed up common media listing queries."""
    # Covers: list by library + type sorted by created_at (most common list query)
    op.create_index(
        "ix_media_item_library_type_created",
        "media_item",
        ["library_guid", "media_type", "created_at"],
    )
    # Covers: top-level items query (parent_guid IS NULL)
    op.create_index(
        "ix_media_item_parent_created",
        "media_item",
        ["parent_guid", "created_at"],
    )
    # Covers: genre filtering via junction table
    op.create_index(
        "ix_media_genre_genre_id_item_guid",
        "media_genre",
        ["genre_id", "media_item_guid"],
    )


def downgrade() -> None:
    """Remove composite indexes."""
    op.drop_index("ix_media_genre_genre_id_item_guid", table_name="media_genre")
    op.drop_index("ix_media_item_parent_created", table_name="media_item")
    op.drop_index("ix_media_item_library_type_created", table_name="media_item")
