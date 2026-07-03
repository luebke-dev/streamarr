"""add container_profile.state_scope and make builtin steam user-scoped

Revision ID: ctnprof003
Revises: ctnprof002
Create Date: 2026-07-04 00:20:00.000000

Adds a per-profile ``state_scope`` controlling how the launch's persistent
``/home/retro`` mount key is derived:

- ``"game"`` (default, legacy): each game gets its own state — a per-user,
  per-game key.
- ``"user"``: one shared state per user across every game on the profile, so
  all of a user's Steam games share a single Steam login + library.

The builtin ``steam`` profile is switched to ``"user"`` so Steam games stop
spawning a fresh, empty ``/home/retro`` (and a fresh login) per game.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ctnprof003"
down_revision: str | Sequence[str] | None = "ctnprof002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "container_profile",
        sa.Column(
            "state_scope",
            sa.String(),
            nullable=False,
            server_default="game",
        ),
    )
    # The builtin steam profile shares one persistent state per user so all of
    # a user's Steam games use a single Steam login + shared library.
    op.execute(
        sa.text(
            "UPDATE container_profile "
            "SET state_scope = 'user', updated_at = NOW() "
            "WHERE name = 'steam' AND is_builtin = true"
        )
    )


def downgrade() -> None:
    op.drop_column("container_profile", "state_scope")
