"""Library database models for managing media libraries."""

import uuid
from datetime import datetime

from sqlalchemy import TIMESTAMP, String, types
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Library(Base):
    """
    Database model for media libraries.

    Each library represents a storage location for a specific type of media.
    Libraries can be enabled/disabled and have configurable paths.

    The type field is dynamic and validated against installed library plugins.
    """

    __tablename__ = "libraries"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        default=uuid.uuid4,
    )
    name: Mapped[str] = mapped_column(index=True, nullable=False)
    type: Mapped[str] = mapped_column(
        String, nullable=False, index=True
    )  # Dynamic library type from plugins
    plugin_id: Mapped[str] = mapped_column(nullable=False, index=True)
    path: Mapped[str] = mapped_column(nullable=False)
    enabled: Mapped[bool] = mapped_column(default=True, nullable=False)

    # Library-specific settings (stored as JSON)
    settings: Mapped[str | None] = mapped_column(nullable=True)

    # Metadata
    created_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        TIMESTAMP(timezone=True), nullable=False
    )

    # Optional description
    description: Mapped[str | None] = mapped_column(nullable=True)
