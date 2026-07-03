"""add voucher and voucher_redemption tables

Revision ID: a1b2c3d4e5f6
Revises: z0a1b2c3d4e5
Create Date: 2026-04-19 17:00:00.000000

Introduces a Voucher / gift-code system that grants memberships without
going through Stripe. A ``voucher`` is bound to a ``subscription_package``
and grants ``duration_days`` of that package's membership when redeemed.
``voucher_redemption`` is an audit trail.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "voucher001"
down_revision: str | None = "z0a1b2c3d4e5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "voucher",
        sa.Column(
            "guid",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("code", sa.String(length=64), nullable=False),
        sa.Column("package_id", sa.Uuid(), nullable=False),
        sa.Column("duration_days", sa.Integer(), nullable=False),
        sa.Column("max_uses", sa.Integer(), nullable=False, server_default="1"),
        sa.Column(
            "current_uses", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column("note", sa.String(length=255), nullable=True),
        sa.Column("created_by_id", sa.Uuid(), nullable=True),
        sa.ForeignKeyConstraint(
            ["package_id"], ["subscription_package.guid"], ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["created_by_id"], ["user.guid"], ondelete="SET NULL"
        ),
        sa.UniqueConstraint("code", name="uq_voucher_code"),
    )
    op.create_index("ix_voucher_code", "voucher", ["code"], unique=False)
    op.create_index("ix_voucher_package_id", "voucher", ["package_id"])

    op.create_table(
        "voucher_redemption",
        sa.Column(
            "guid",
            sa.Uuid(),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "redeemed_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("voucher_id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("subscription_id", sa.Uuid(), nullable=False),
        sa.ForeignKeyConstraint(
            ["voucher_id"], ["voucher.guid"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["user.guid"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["subscription_id"], ["user_subscription.guid"], ondelete="RESTRICT"
        ),
    )
    op.create_index(
        "ix_voucher_redemption_voucher_id",
        "voucher_redemption",
        ["voucher_id"],
    )
    op.create_index(
        "ix_voucher_redemption_user_id", "voucher_redemption", ["user_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_voucher_redemption_user_id", table_name="voucher_redemption")
    op.drop_index(
        "ix_voucher_redemption_voucher_id", table_name="voucher_redemption"
    )
    op.drop_table("voucher_redemption")
    op.drop_index("ix_voucher_package_id", table_name="voucher")
    op.drop_index("ix_voucher_code", table_name="voucher")
    op.drop_table("voucher")
