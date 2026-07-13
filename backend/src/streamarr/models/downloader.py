import uuid
from datetime import datetime

from sqlalchemy import func, text, types
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class Downloader(Base):
    __tablename__ = "downloader"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        primary_key=True,
        server_default=text("gen_random_uuid()"),  # use what you have on your server
    )
    created_at: Mapped[datetime | None] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(
        server_default=func.now(), onupdate=func.now()
    )
    label: Mapped[str] = mapped_column(index=True)
    host: Mapped[str] = mapped_column(index=True)
    api_key: Mapped[str | None] = mapped_column(index=True, nullable=True)
    type: Mapped[str] = mapped_column(index=True)
    ssl: Mapped[bool] = mapped_column(default=False)
    verify_ssl: Mapped[bool] = mapped_column(default=True)
