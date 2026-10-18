"""rename the builtin retro profile image to streamarr-retro

Revision ID: ctnprof005
Revises: modeldrift001
Create Date: 2026-09-27 00:00:00.000000

The ``retro`` profile's ``docker_image`` still points at
``ghcr.io/luebke-dev/pyrate-retro:latest``, the name it had when
``ctnprof004`` seeded it. The project was renamed pyrate -> Streamarr
afterwards and ``ctnprof004``'s source was updated to match, but a migration
that has already run is never re-executed, so every database installed before
the rename kept the old string while a fresh database got the new one. The two
would then disagree about which image to launch.

Rewriting the already-applied migration is not an option (it would not
re-run), so the correction ships as its own migration. It is idempotent and
scoped to the builtin profile: a user-edited image, or one that never carried
the old name, is left alone.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "ctnprof005"
down_revision: str | Sequence[str] | None = "modeldrift001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_OLD_IMAGE = "ghcr.io/luebke-dev/pyrate-retro:latest"
_NEW_IMAGE = "ghcr.io/luebke-dev/streamarr-retro:latest"


def upgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE container_profile
            SET docker_image = :new_image,
                updated_at = NOW()
            WHERE name = 'retro'
              AND docker_image = :old_image
            """
        ).bindparams(new_image=_NEW_IMAGE, old_image=_OLD_IMAGE)
    )


def downgrade() -> None:
    op.execute(
        sa.text(
            """
            UPDATE container_profile
            SET docker_image = :old_image,
                updated_at = NOW()
            WHERE name = 'retro'
              AND docker_image = :new_image
            """
        ).bindparams(new_image=_NEW_IMAGE, old_image=_OLD_IMAGE)
    )
