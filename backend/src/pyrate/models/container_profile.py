import uuid
from datetime import datetime

from sqlalchemy import func, text, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ContainerProfile(Base):
    """Global (not per-user) container profile for Lightrays game launches.

    Describes how a "game" (a generic container) is launched: which Docker
    image, which server-side ``runtime_profile`` Lightrays resolves, and a
    shared, admin-controlled container environment (``env``). Individual games
    reference a profile by name/guid via ``extra_data.lightrays.profile`` and
    may override the image or extend the env per-game.
    """

    __tablename__ = "container_profile"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )

    name: Mapped[str] = mapped_column(unique=True, index=True)
    kind: Mapped[str] = mapped_column(index=True)
    docker_image: Mapped[str] = mapped_column()
    runtime_profile: Mapped[str] = mapped_column(
        default="gow-app", server_default="gow-app"
    )

    # Shared, admin-controlled container env (string→string). Merged with the
    # per-game env at launch time; JSONB on PostgreSQL, JSON on SQLite (tests).
    env: Mapped[dict] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"),
        nullable=False,
        default=dict,
        server_default=text("'{}'"),
    )

    is_builtin: Mapped[bool] = mapped_column(
        default=False, server_default=text("false"), index=True
    )
