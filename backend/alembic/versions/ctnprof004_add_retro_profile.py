"""seed builtin retro (libretro) container profile

Revision ID: ctnprof004
Revises: ctnprof003
Create Date: 2026-07-04 00:00:00.000000

Seeds a single builtin ``retro`` profile backing the generic
``streamarr-retro`` (RetroArch kiosk) image, so any GAMES item that references
``extra_data.lightrays.profile = "retro"`` launches a libretro core + ROM
with no per-game plumbing. The core is chosen per-game via
``extra_data.lightrays.env.RETRO_CORE``; the ROM travels as ``app_ref`` and
is substituted into ``RETRO_ROM = "{app_ref}"`` by the launch resolver.

Idempotent: only inserts when no ``retro`` profile exists, so it is safe to
re-run. state_scope = "game" keeps each game's saves/savestates isolated.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ctnprof004"
down_revision: str | Sequence[str] | None = "ctnprof003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_SEED_RETRO = sa.text(
    """
    INSERT INTO container_profile (
        guid, name, kind, docker_image, runtime_profile, state_scope, env,
        is_builtin, created_at, updated_at
    )
    SELECT
        gen_random_uuid(), 'retro', 'libretro',
        'ghcr.io/luebke-dev/streamarr-retro:latest', 'gow-app', 'game',
        CAST('{"RETRO_ROM": "{app_ref}", "RETRO_SYSTEM_DIR": "/system"}' AS JSONB),
        true, NOW(), NOW()
    WHERE NOT EXISTS (
        SELECT 1 FROM container_profile WHERE name = 'retro'
    )
    """
)


def upgrade() -> None:
    op.execute(_SEED_RETRO)


def downgrade() -> None:
    op.execute(
        sa.text("DELETE FROM container_profile WHERE name = 'retro' AND is_builtin = true")
    )
