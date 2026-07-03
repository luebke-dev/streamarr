"""Shared download status normalization helpers."""

from __future__ import annotations


def download_status_value(status: object | None) -> str | None:
    """Return a lower-case string value for raw strings or enum-like statuses."""
    if status is None:
        return None
    value = getattr(status, "value", status)
    normalized = str(value).strip().lower().replace(" ", "_")
    return normalized or None


def download_phase(status: object | None) -> str | None:
    """Map low-level downloader statuses to user-facing progress phases."""
    normalized = download_status_value(status)
    if normalized in {"failed", "retrying", "retrying_release"}:
        return "retrying_release"
    if normalized in {"completed", "importing", "imported"}:
        return "importing"
    if normalized in {"pending", "queued", "preparing", "downloading", "searching"}:
        return normalized
    return normalized
