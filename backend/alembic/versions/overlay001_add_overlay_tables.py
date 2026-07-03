"""add overlay_template and overlay_application tables

Revision ID: overlay001
Revises: smartcoll001
Create Date: 2026-05-14 12:05:00.000000

Introduces poster/backdrop overlay templates and a per-item cache table
that records which template+target combination was last rendered for an
item, along with the source_hash used to invalidate the cache.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "overlay001"
down_revision: str | Sequence[str] | None = "smartcoll001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "overlay_template",
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
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.String(), nullable=True),
        sa.Column(
            "media_scope",
            sa.String(),
            nullable=False,
            server_default="BOTH",
        ),
        sa.Column(
            "target", sa.String(), nullable=False, server_default="POSTER"
        ),
        sa.Column(
            "condition",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=True,
        ),
        sa.Column(
            "elements",
            sa.JSON().with_variant(
                sa.dialects.postgresql.JSONB(), "postgresql"
            ),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("z_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "enabled", sa.Boolean(), nullable=False, server_default=sa.true()
        ),
        sa.Column(
            "is_system",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_index(
        "ix_overlay_template_name", "overlay_template", ["name"]
    )
    op.create_index(
        "ix_overlay_template_media_scope",
        "overlay_template",
        ["media_scope"],
    )
    op.create_index(
        "ix_overlay_template_target", "overlay_template", ["target"]
    )
    op.create_index(
        "ix_overlay_template_z_order", "overlay_template", ["z_order"]
    )
    op.create_index(
        "ix_overlay_template_enabled", "overlay_template", ["enabled"]
    )
    op.create_index(
        "ix_overlay_template_is_system",
        "overlay_template",
        ["is_system"],
    )

    op.create_table(
        "overlay_application",
        sa.Column("media_item_guid", sa.Uuid(), nullable=False),
        sa.Column("template_guid", sa.Uuid(), nullable=False),
        sa.Column("target", sa.String(), nullable=False),
        sa.Column(
            "rendered_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("output_path", sa.String(), nullable=False),
        sa.Column("source_hash", sa.String(), nullable=False),
        sa.ForeignKeyConstraint(
            ["media_item_guid"],
            ["media_item.guid"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["template_guid"],
            ["overlay_template.guid"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "media_item_guid", "template_guid", "target"
        ),
    )
    op.create_index(
        "ix_overlay_application_source_hash",
        "overlay_application",
        ["source_hash"],
    )
    op.create_index(
        "ix_overlay_application_item_target",
        "overlay_application",
        ["media_item_guid", "target"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_overlay_application_item_target",
        table_name="overlay_application",
    )
    op.drop_index(
        "ix_overlay_application_source_hash",
        table_name="overlay_application",
    )
    op.drop_table("overlay_application")

    op.drop_index(
        "ix_overlay_template_is_system", table_name="overlay_template"
    )
    op.drop_index(
        "ix_overlay_template_enabled", table_name="overlay_template"
    )
    op.drop_index(
        "ix_overlay_template_z_order", table_name="overlay_template"
    )
    op.drop_index(
        "ix_overlay_template_target", table_name="overlay_template"
    )
    op.drop_index(
        "ix_overlay_template_media_scope", table_name="overlay_template"
    )
    op.drop_index(
        "ix_overlay_template_name", table_name="overlay_template"
    )
    op.drop_table("overlay_template")
