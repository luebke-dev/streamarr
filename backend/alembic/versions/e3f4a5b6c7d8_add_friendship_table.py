"""add friendship table

Revision ID: e3f4a5b6c7d8
Revises: d2e3f4a5b6c7
Create Date: 2026-02-18

"""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = "e3f4a5b6c7d8"
down_revision = "d2e3f4a5b6c7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "friendship",
        sa.Column("guid", sa.Uuid(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=True),
        sa.Column("requester_id", sa.Uuid(), nullable=False),
        sa.Column("addressee_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.Enum("pending", "accepted", "blocked", name="friendshipstatus"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["addressee_id"], ["user.guid"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["requester_id"], ["user.guid"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("guid"),
        sa.UniqueConstraint("requester_id", "addressee_id", name="uq_friendship_pair"),
    )
    op.create_index(op.f("ix_friendship_requester_id"), "friendship", ["requester_id"])
    op.create_index(op.f("ix_friendship_addressee_id"), "friendship", ["addressee_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_friendship_addressee_id"), table_name="friendship")
    op.drop_index(op.f("ix_friendship_requester_id"), table_name="friendship")
    op.drop_table("friendship")
    op.execute("DROP TYPE IF EXISTS friendshipstatus")
