"""Cron utilities for smart-collection rules.

Wraps ``croniter`` so the rest of the code can stay agnostic to the
library and ``parse_cron`` provides a single validation entry point
(used by both the worker tick and the admin-API form validation).
"""

from __future__ import annotations

from datetime import UTC, datetime

from croniter import CroniterBadCronError, croniter


def parse_cron(expression: str) -> bool:
    """Return True when ``expression`` is a valid 5-field cron spec."""
    try:
        croniter(expression)
    except (CroniterBadCronError, ValueError, KeyError):
        return False
    return True


def next_run_after(
    expression: str,
    reference: datetime | None = None,
) -> datetime:
    """Compute the next firing time strictly after ``reference``.

    Raises ``ValueError`` for invalid expressions so the caller can mark
    the rule as failed instead of silently dropping the schedule.
    """
    base = reference or datetime.now(UTC)
    try:
        itr = croniter(expression, base)
    except (CroniterBadCronError, ValueError, KeyError) as exc:
        raise ValueError(f"Invalid cron expression {expression!r}: {exc}")
    nxt = itr.get_next(datetime)
    # croniter returns naive datetimes when fed a UTC-aware one with no
    # tzinfo; force UTC so downstream code compares like-for-like.
    if nxt.tzinfo is None:
        nxt = nxt.replace(tzinfo=UTC)
    return nxt
