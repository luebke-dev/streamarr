"""add upgrade fields to download

Revision ID: slugupg001
Revises: slugrss001
Create Date: 2026-05-16 17:33:00.000000

Tags a download as an upgrade that replaces an existing media file. The
completion handler swaps the old file for the new one only after a
successful import; a failed upgrade keeps the old file untouched.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "slugupg001"
down_revision: str | Sequence[str] | None = "slugrss001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download",
        sa.Column(
            "is_upgrade",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "download",
        sa.Column("replaces_media_file_guid", sa.Uuid(), nullable=True),
    )
    op.create_index("ix_download_is_upgrade", "download", ["is_upgrade"])
    op.create_index(
        "ix_download_replaces_media_file_guid",
        "download",
        ["replaces_media_file_guid"],
    )
    op.create_foreign_key(
        "fk_download_replaces_media_file_guid",
        "download",
        "media_file",
        ["replaces_media_file_guid"],
        ["guid"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_download_replaces_media_file_guid", "download", type_="foreignkey"
    )
    op.drop_index(
        "ix_download_replaces_media_file_guid", table_name="download"
    )
    op.drop_index("ix_download_is_upgrade", table_name="download")
    op.drop_column("download", "replaces_media_file_guid")
    op.drop_column("download", "is_upgrade")
