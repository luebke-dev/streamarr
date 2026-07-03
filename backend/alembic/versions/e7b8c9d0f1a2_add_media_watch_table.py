"""Add media_watch table

Revision ID: e7b8c9d0f1a2
Revises: d6a7b8c9e0f1
Create Date: 2026-03-19
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "e7b8c9d0f1a2"
down_revision: Union[str, None] = "d6a7b8c9e0f1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "media_watch",
        sa.Column("guid", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("user_guid", sa.Uuid(), sa.ForeignKey("user.guid", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("media_item_guid", sa.Uuid(), sa.ForeignKey("media_item.guid", ondelete="CASCADE"), nullable=False, index=True),
        sa.UniqueConstraint("user_guid", "media_item_guid", name="uq_media_watch_user_item"),
    )


def downgrade() -> None:
    op.drop_table("media_watch")
