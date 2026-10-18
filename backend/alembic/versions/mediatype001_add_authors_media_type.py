"""Add the AUTHORS media type the books plugin declares.

The books plugin exposes AUTHORS as the parent type of BOOKS, and three
endpoints query it by name (`/api/trailers`, `/api/filters`,
`/api/suggestions/autocomplete/typed`). The PostgreSQL enum never learned the
value: `MediaType` is generated from the plugin registry at import time, so
neither the models nor the test suite (SQLite) can tell that the two drifted
apart - the endpoints just return 500 with `invalid input value for enum
mediatype: "AUTHORS"`.

Revision ID: mediatype001
Revises: ctnprof005
Create Date: 2026-10-18 18:10:00.000000
"""

from typing import Sequence, Union

from alembic import op

revision: str = "mediatype001"
down_revision: Union[str, Sequence[str], None] = "ctnprof005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TYPE mediatype ADD VALUE IF NOT EXISTS 'AUTHORS'")


def downgrade() -> None:
    # PostgreSQL cannot remove individual enum values in place.
    pass
