from datetime import datetime

from pydantic import BaseModel, ConfigDict

from pyrate.schemas.base import BaseSchema

from pyrate.schemas.media import MediaItemSummary


class GenreBase(BaseModel):
    name: str


class GenreCreate(GenreBase):
    id: int


class GenreRead(GenreBase):
    id: int
    created_at: datetime | None = None
    updated_at: datetime | None = None

    model_config = ConfigDict(from_attributes=True)


class GenreUpdate(BaseModel):
    name: str | None = None


class GenreWithItems(BaseSchema):
    """Genre with its media items for the all-genres section."""

    id: int
    name: str
    items: list[MediaItemSummary] = []

