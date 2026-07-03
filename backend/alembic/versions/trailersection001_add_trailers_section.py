"""add trailers page section

Revision ID: trailersection001
Revises: d5e6f7a8b9c0, qcremove001
Create Date: 2026-05-12 14:55:00.000000

"""

import json
import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "trailersection001"
down_revision: str | Sequence[str] | None = ("d5e6f7a8b9c0", "qcremove001")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    """Add trailers as a default home layout section."""
    bind = op.get_bind()
    home_layouts = bind.execute(
        sa.text("SELECT guid FROM page_layout WHERE slug = 'home'")
    ).fetchall()

    for (layout_guid,) in home_layouts:
        exists = bind.execute(
            sa.text(
                "SELECT 1 FROM page_section "
                "WHERE layout_guid = :layout_guid AND section_type = 'trailers' LIMIT 1"
            ),
            {"layout_guid": layout_guid},
        ).scalar()
        if exists:
            continue

        next_order = bind.execute(
            sa.text(
                "SELECT COALESCE(MAX(order_index), -1) + 1 "
                "FROM page_section WHERE layout_guid = :layout_guid"
            ),
            {"layout_guid": layout_guid},
        ).scalar_one()

        bind.execute(
            sa.text(
                "INSERT INTO page_section "
                "(guid, layout_guid, section_type, order_index, title, config, is_enabled) "
                "VALUES (:guid, :layout_guid, 'trailers', :order_index, NULL, :config, true)"
            ),
            {
                "guid": uuid.uuid4(),
                "layout_guid": layout_guid,
                "order_index": next_order,
                "config": json.dumps({"max_items": 20}),
            },
        )


def downgrade() -> None:
    """Remove seeded trailers sections from home layouts."""
    op.execute(
        sa.text(
            "DELETE FROM page_section "
            "WHERE section_type = 'trailers' "
            "AND layout_guid IN (SELECT guid FROM page_layout WHERE slug = 'home')"
        )
    )
