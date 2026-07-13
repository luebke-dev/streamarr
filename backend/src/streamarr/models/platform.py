"""Platform model for game platform categorization."""

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Platform(Base):
    """Platform model for categorizing games by platform (PC, PS5, Switch, etc.)."""

    __tablename__ = "platform"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(unique=True, index=True, nullable=False)
    logo_url: Mapped[str | None] = mapped_column(nullable=True)
    igdb_id: Mapped[int | None] = mapped_column(nullable=True, index=True)

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
