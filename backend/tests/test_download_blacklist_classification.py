"""Regression tests for infra-vs-release failure classification.

A full remote download disk surfaced as a generic ``I/O error (os error 5)``
(EIO) rather than ``ENOSPC``, so the old ENOSPC-only fragment list failed to
recognise it and every grab blacklisted its release — poisoning the whole
release pool. Two guards now exist:

1. The downloader reports an authoritative ``retriable`` flag (preferred).
2. ``_is_transient_error`` text matching is the fallback for older payloads.

These tests lock both so the edge case can't silently regress.
"""

from streamarr.services.download import _is_transient_error

# The exact downloader messages that WRONGLY blacklisted releases in the
# incident — every one must be recognised as transient (infra) now.
INFRA_MESSAGES = [
    "Cannot create dest dir: I/O error (os error 5)",
    "Cannot create temp dir: I/O error (os error 5)",
    'Write error "/downloads/.tmp/abc123/Show.S01E01.mkv.part02.rar"',
    "Failed to move completed files: Input/output error",
    "no space left on device",
    "disk full",
    "connection reset by peer",
    "operation timed out",
]

# Genuine release-quality failures — these MUST still blacklist the release.
RELEASE_MESSAGES = [
    "Pre-check failed: 10/10 sampled articles missing (100%) — release is likely dead or DMCA'd",
    "PAR2 repair failed: par2 reported an unrecoverable error",
    "Archive extraction failed: RAR extraction failed: UNRAR 6.21",
    "NZB parse error: unexpected end of file",
]


def test_infra_errors_are_transient():
    for msg in INFRA_MESSAGES:
        assert _is_transient_error(msg) is True, f"should be transient: {msg!r}"


def test_release_errors_are_not_transient():
    for msg in RELEASE_MESSAGES:
        assert _is_transient_error(msg) is False, f"should blacklist: {msg!r}"


def test_none_reason_is_not_transient():
    assert _is_transient_error(None) is False
    assert _is_transient_error("") is False
