"""Add api_key table.

Revision ID: api_key001
Revises: voucher001
Create Date: 2026-05-11 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "api_key001"
down_revision: str | Sequence[str] | None = "voucher001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "api_key",
        sa.Column("guid", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("key_prefix", sa.String(length=16), nullable=False),
        sa.Column("key_hash", sa.String(length=64), nullable=False),
        sa.Column("user_guid", sa.Uuid(), nullable=False),
        sa.Column("created_by_guid", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_guid"], ["user.guid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_guid"], ["user.guid"], ondelete="SET NULL"),
        sa.UniqueConstraint("key_hash", name="uq_api_key_key_hash"),
    )
    op.create_index(op.f("ix_api_key_key_prefix"), "api_key", ["key_prefix"])
    op.create_index(op.f("ix_api_key_key_hash"), "api_key", ["key_hash"])
    op.create_index(op.f("ix_api_key_user_guid"), "api_key", ["user_guid"])


def downgrade() -> None:
    op.drop_index(op.f("ix_api_key_user_guid"), table_name="api_key")
    op.drop_index(op.f("ix_api_key_key_hash"), table_name="api_key")
    op.drop_index(op.f("ix_api_key_key_prefix"), table_name="api_key")
    op.drop_table("api_key")
