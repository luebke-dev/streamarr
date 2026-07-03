"""add user_guid to download

Revision ID: a5b6c7d8e9f0
Revises: f4a5b6c7d8e9
Create Date: 2026-02-27

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5b6c7d8e9f0"
down_revision: str | None = "f4a5b6c7d8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "download",
        sa.Column("user_guid", sa.Uuid(), nullable=True),
    )
    op.create_index(op.f("ix_download_user_guid"), "download", ["user_guid"], unique=False)
    op.create_foreign_key(
        "fk_download_user_guid",
        "download",
        "user",
        ["user_guid"],
        ["guid"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_download_user_guid", "download", type_="foreignkey")
    op.drop_index(op.f("ix_download_user_guid"), table_name="download")
    op.drop_column("download", "user_guid")
