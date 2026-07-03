"""set the builtin steam profile's launch template (auto-launch a game)

Revision ID: ctnprof002
Revises: ctnprof001
Create Date: 2026-07-04 00:10:00.000000

Gives the builtin ``steam`` profile a launch template so a game can be
auto-launched instead of only opening Steam Big Picture. The profile holds
the launch command ONCE via the per-game ``{app_ref}`` placeholder
(resolved in ``resolve_launch_config``): a game that carries
``extra_data.lightrays.app_ref = "<steam app id>"`` produces
``STEAM_STARTUP_FLAGS="-bigpicture steam://rungameid/<app id>"``; a game
without an ``app_ref`` drops the entry entirely and falls back to Big
Picture (GOW's default), so nothing regresses for existing games.

Only applied when the profile's env is still empty, so an operator's custom
env is never clobbered.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ctnprof002"
down_revision: str | Sequence[str] | None = "ctnprof001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_STEAM_LAUNCH_ENV = '{"STEAM_STARTUP_FLAGS": "-bigpicture steam://rungameid/{app_ref}"}'


def upgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE container_profile "
            "SET env = CAST(:env AS JSONB), updated_at = NOW() "
            "WHERE name = 'steam' AND is_builtin = true "
            "AND (env IS NULL OR env = CAST('{}' AS JSONB))"
        ).bindparams(env=_STEAM_LAUNCH_ENV)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            "UPDATE container_profile "
            "SET env = CAST('{}' AS JSONB), updated_at = NOW() "
            "WHERE name = 'steam' AND is_builtin = true AND env = CAST(:env AS JSONB)"
        ).bindparams(env=_STEAM_LAUNCH_ENV)
    )
