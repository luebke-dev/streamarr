"""Shared rules for the show -> season -> episode hierarchy.

The show plugin types the three levels ``SHOWS -> SEASONS -> EPISODES``, but
rows written by older importers (and by some library imports) are typed
``SHOWS`` all the way down. A bare ``media_type == MediaType.SHOWS`` test
therefore matches the top level and nothing else, which is how a scanned
episode ended up with no show title in the player while the very same episode
resolved fine in the continue-watching row: that code keyed off
``parent_guid`` instead.

Both shapes have to resolve, so the rule lives here once instead of being
open-coded per call site. ``MediaType`` is generated from the registered
plugins, which is why its members are read with ``getattr`` - an unloaded
plugin means the member does not exist at all.
"""

from __future__ import annotations

from typing import Any

from streamarr.models.media import MediaItem, MediaType

SHOW = "show"
SEASON = "season"
EPISODE = "episode"


def episode_type() -> Any | None:
    """The media type the show plugin uses for an episode, if registered."""
    return getattr(MediaType, "EPISODES", None)


def season_type() -> Any | None:
    """The media type the show plugin uses for a season, if registered."""
    return getattr(MediaType, "SEASONS", None)


def show_tree_types() -> frozenset[Any]:
    """Every media type that belongs to the show tree."""
    return frozenset(
        media_type
        for name in ("SHOWS", "SEASONS", "EPISODES")
        if (media_type := getattr(MediaType, name, None)) is not None
    )


def is_show_tree(media_type: Any) -> bool:
    """Whether ``media_type`` is a show, a season or an episode."""
    return media_type in show_tree_types()


def show_level(media_item: MediaItem, parent: MediaItem | None) -> str:
    """Level of ``media_item`` in the show tree: show, season or episode.

    ``parent`` is the item's own parent row - ``None`` when it is missing or
    was not loaded. The explicit episode type wins, so an episode hanging
    directly off a show is still an episode; for the legacy SHOWS-only shape
    the depth of the chain decides.
    """
    if not media_item.parent_guid:
        return SHOW
    if media_item.media_type == episode_type():
        return EPISODE
    if parent is not None and parent.parent_guid:
        return EPISODE
    return SEASON


def hierarchy_labels(
    media_item: MediaItem,
    parent: MediaItem | None,
    grandparent: MediaItem | None,
) -> dict[str, Any]:
    """Season/episode numbers and the owning show for a show-tree item.

    Returns the four keys the detail payload and the viewing-history payloads
    carry. A season reports its own number and no episode number, a show
    reports neither. ``grandparent`` is only consulted for an episode, where
    it is the show; for a season the parent already is the show.
    """
    labels: dict[str, Any] = {
        "show_title": None,
        "show_guid": None,
        "season_number": None,
        "episode_number": None,
    }
    level = show_level(media_item, parent)
    if level == SHOW:
        return labels

    if level == EPISODE:
        labels["episode_number"] = media_item.sequence_number
        if parent is not None:
            labels["season_number"] = parent.sequence_number
        # The parent of an episode is normally its season, which has no title
        # worth showing; only an episode that hangs directly off the show uses
        # the parent as the show.
        show = parent
        if parent is not None and (
            parent.parent_guid or parent.media_type == season_type()
        ):
            show = grandparent
    else:
        labels["season_number"] = media_item.sequence_number
        show = parent

    if show is not None:
        labels["show_title"] = show.title
        labels["show_guid"] = show.guid
    return labels
