"""Shared date-parsing utilities."""

import logging
from datetime import datetime

logger = logging.getLogger(__name__)


def parse_spotify_date(date_str: str | None):
    """Parse a Spotify date string (YYYY, YYYY-MM, or YYYY-MM-DD) to a date or None."""
    if not date_str:
        return None
    try:
        if len(date_str) == 4:
            return datetime.strptime(date_str, "%Y").date()
        if len(date_str) == 7:
            return datetime.strptime(date_str, "%Y-%m").date()
        return datetime.strptime(date_str, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        logger.debug("Invalid Spotify release date: %s", date_str)
        return None
