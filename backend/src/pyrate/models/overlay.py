import uuid
from datetime import UTC, datetime
from enum import StrEnum

from sqlalchemy import ForeignKey, Index, types
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class _CaseInsensitiveStrEnum(StrEnum):
    @classmethod
    def _missing_(cls, value):
        if isinstance(value, str):
            upper = value.upper()
            for member in cls:
                if member.value == upper:
                    return member
        return None


class OverlayMediaScope(_CaseInsensitiveStrEnum):
    MOVIE = "MOVIE"
    SHOW = "SHOW"
    BOTH = "BOTH"


class OverlayTarget(_CaseInsensitiveStrEnum):
    POSTER = "POSTER"
    BACKDROP = "BACKDROP"


class OverlayTemplate(Base):
    __tablename__ = "overlay_template"

    guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid, primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    name: Mapped[str] = mapped_column(index=True)
    description: Mapped[str | None] = mapped_column()

    media_scope: Mapped[OverlayMediaScope] = mapped_column(
        default=OverlayMediaScope.BOTH, index=True
    )
    target: Mapped[OverlayTarget] = mapped_column(
        default=OverlayTarget.POSTER, index=True
    )

    # Condition tree:
    # {"all": [{"field": "resolution.height", "op": "gte", "value": 2160}]}
    # An empty/null condition means "applies to every item".
    condition: Mapped[dict | None] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=None
    )
    # Render elements: ordered list of text/image elements with position & style.
    elements: Mapped[list] = mapped_column(
        types.JSON().with_variant(JSONB, "postgresql"), default=list
    )

    z_order: Mapped[int] = mapped_column(default=0, index=True)
    enabled: Mapped[bool] = mapped_column(default=True, index=True)
    is_system: Mapped[bool] = mapped_column(default=False, index=True)

    # Bumped whenever elements/condition/target change. Renderer hashes this
    # into source_hash so OverlayApplication rows invalidate automatically.
    version: Mapped[int] = mapped_column(default=1)

    applications = relationship(
        "OverlayApplication", back_populates="template", cascade="all, delete-orphan"
    )


class OverlayApplication(Base):
    __tablename__ = "overlay_application"

    media_item_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("media_item.guid", ondelete="CASCADE"),
        primary_key=True,
    )
    template_guid: Mapped[uuid.UUID] = mapped_column(
        types.Uuid,
        ForeignKey("overlay_template.guid", ondelete="CASCADE"),
        primary_key=True,
    )
    target: Mapped[OverlayTarget] = mapped_column(primary_key=True)

    rendered_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))
    output_path: Mapped[str] = mapped_column()
    # sha256(original_path + sorted(template versions for this item)).
    source_hash: Mapped[str] = mapped_column(index=True)

    template = relationship("OverlayTemplate", back_populates="applications")

    __table_args__ = (
        Index(
            "ix_overlay_application_item_target", "media_item_guid", "target"
        ),
    )
