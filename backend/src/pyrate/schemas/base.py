"""Shared Pydantic schema base classes and common response shapes.

Pre-existing schemas across the codebase repeated two patterns dozens of
times each: ``model_config = ConfigDict(from_attributes=True)`` (~77 sites
when this module landed) and a generic ``PaginatedResponse[T]`` (defined
identically in three modules). Centralising both here lets us evolve
shared config and pagination behaviour in one place.
"""

from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict


__all__ = ["BaseSchema", "PaginatedResponse"]


class BaseSchema(BaseModel):
    """Project-wide base for read/write schemas.

    Sets ``from_attributes=True`` so the schema can be ``model_validate``-d
    directly from SQLAlchemy ORM instances without an intermediate dict.
    Add cross-cutting Pydantic config knobs here, not on individual schemas.
    """

    model_config = ConfigDict(from_attributes=True)


T = TypeVar("T")


class PaginatedResponse(BaseSchema, Generic[T]):
    """Standard pagination envelope used by every list endpoint."""

    items: list[T]
    total: int
    page: int
    per_page: int
    total_pages: int
