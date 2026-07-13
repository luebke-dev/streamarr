"""Normalize content rating strings into a ``min_age`` integer.

Media providers hand us certifications in a zoo of national systems (FSK,
MPAA, BBFC, TV Parental Guidelines, ESRB for games). We collapse them into a
single "minimum viewer age in years" number so the parental-control filter
is trivial: a user with ``parental_max_age = 12`` sees everything with
``min_age <= 12``.

``None`` out means "unknown" — the caller decides whether to treat unknown
as allowed (we do, so unrated content isn't hidden from adults) or blocked.
"""

from __future__ import annotations

import re

_MPAA = {
    "G": 0,
    "PG": 6,
    "PG-13": 12,
    "PG13": 12,
    "R": 16,
    "NC-17": 18,
    "NC17": 18,
}

_UK = {
    "U": 0,
    "PG": 6,
    "12": 12,
    "12A": 12,
    "15": 15,
    "18": 18,
}

# TMDB TV Parental Guidelines (US)
_TV_US = {
    "TV-Y": 0,
    "TV-Y7": 7,
    "TV-G": 0,
    "TV-PG": 10,
    "TV-14": 14,
    "TV-MA": 18,
}

_NUMERIC_PREFIX = re.compile(r"^\s*(\d{1,2})\b")


def parse_min_age(raw: str | None) -> int | None:
    """Return the minimum viewer age for a certification string, or None.

    Accepts the various formats TMDB hands us: ``"FSK 16"``, ``"16"``,
    ``"PG-13"``, ``"TV-MA"``, ``"PG"`` etc. Unknown inputs return ``None``.
    """
    if not raw:
        return None
    s = raw.strip().upper()
    if not s:
        return None

    # German FSK / Austrian JMK / Swiss number-only → take the leading number
    stripped = s.removeprefix("FSK").removeprefix("JMK").removeprefix("USK").strip()
    m = _NUMERIC_PREFIX.match(stripped)
    if m:
        try:
            age = int(m.group(1))
            if 0 <= age <= 21:
                return age
        except ValueError:
            pass

    if s in _TV_US:
        return _TV_US[s]
    if s in _MPAA:
        return _MPAA[s]
    if s in _UK:
        return _UK[s]

    # Some providers stick the country code on: "US:PG-13"
    if ":" in s:
        _, tail = s.split(":", 1)
        return parse_min_age(tail)

    return None


def is_allowed(min_age: int | None, parental_max_age: int | None) -> bool:
    """True if a user with ``parental_max_age`` may view media tagged ``min_age``.

    Unknown on either side is treated as permissive: NULL user setting → no
    gate, NULL media rating → counts as allowed (we don't block unrated
    content). Only both sides populated trigger the comparison.
    """
    if parental_max_age is None:
        return True
    if min_age is None:
        return True
    return min_age <= parental_max_age


def age_filter_clause(user_max_age: int | None):
    """Return a SQLAlchemy clause that keeps rows a user is allowed to see.

    Usage:
        query = query.where(age_filter_clause(user.parental_max_age))

    Resolves to ``True`` when the user has no limit so it's a no-op; otherwise
    allows rows where ``min_age IS NULL`` OR ``min_age <= user_max_age``.
    Superusers should pass ``None`` (no gate) from the call site.
    """
    from sqlalchemy import or_, true
    from streamarr.models.media import MediaItem

    if user_max_age is None:
        return true()
    return or_(MediaItem.min_age.is_(None), MediaItem.min_age <= user_max_age)
