"""add users.token_valid_after for instant session revocation

Revision ID: authtva001
Revises: ctnprof004
Create Date: 2026-07-12 00:00:00.000000

Adds a nullable ``token_valid_after`` timestamp to ``user``. Access/refresh
tokens whose ``iat`` predates this value are rejected, so logout and password
reset can revoke outstanding sessions immediately instead of waiting for the
short access token to expire. NULL means "no cutoff" (all existing sessions
remain valid), so the upgrade is non-disruptive.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "authtva001"
down_revision: str | Sequence[str] | None = "ctnprof004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user",
        sa.Column("token_valid_after", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user", "token_valid_after")
