"""Schemas for the recommendation system."""

from __future__ import annotations

from pydantic import BaseModel


class FriendAttribution(BaseModel):
    """One friend who watched a given item, attached to
    rec:friends_watching:* list items by the API enrichment layer."""

    user_guid: str
    display_name: str
    avatar_url: str | None = None
    last_watched_at: str | None = None
