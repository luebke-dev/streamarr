"""Drop QuickConnect pairing sessions.

Revision ID: qcremove001
Revises: policy001
Create Date: 2026-05-11 00:00:00.000000
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "qcremove001"
down_revision: Union[str, Sequence[str], None] = "policy001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(op.f("ix_quick_connect_session_user_id"), table_name="quick_connect_session")
    op.drop_index(op.f("ix_quick_connect_session_expires_at"), table_name="quick_connect_session")
    op.drop_index(op.f("ix_quick_connect_session_code"), table_name="quick_connect_session")
    op.drop_table("quick_connect_session")


def downgrade() -> None:
    op.create_table(
        "quick_connect_session",
        sa.Column("guid", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("code", sa.String(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("authorized_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("claimed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["user.guid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guid"),
    )
    op.create_index(
        op.f("ix_quick_connect_session_code"),
        "quick_connect_session",
        ["code"],
        unique=True,
    )
    op.create_index(
        op.f("ix_quick_connect_session_expires_at"),
        "quick_connect_session",
        ["expires_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_quick_connect_session_user_id"),
        "quick_connect_session",
        ["user_id"],
        unique=False,
    )
