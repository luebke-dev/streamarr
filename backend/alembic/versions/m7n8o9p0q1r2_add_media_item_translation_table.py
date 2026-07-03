"""Add media_item_translation table for multi-language metadata

Revision ID: m7n8o9p0q1r2
Revises: l6m7n8o9p0q1
Create Date: 2026-03-23

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "m7n8o9p0q1r2"
down_revision: str | None = "l6m7n8o9p0q1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "media_item_translation",
        sa.Column("guid", sa.Uuid(), nullable=False),
        sa.Column(
            "media_item_guid",
            sa.Uuid(),
            sa.ForeignKey("media_item.guid", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("language", sa.String(), nullable=False),
        sa.Column("title", sa.String(), nullable=True),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column("tagline", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("guid"),
        sa.UniqueConstraint(
            "media_item_guid", "language",
            name="uq_media_translation_item_language",
        ),
    )
    op.create_index("ix_media_item_translation_media_item_guid", "media_item_translation", ["media_item_guid"])
    op.create_index("ix_media_item_translation_language", "media_item_translation", ["language"])


def downgrade() -> None:
    op.drop_index("ix_media_item_translation_language")
    op.drop_index("ix_media_item_translation_media_item_guid")
    op.drop_table("media_item_translation")
