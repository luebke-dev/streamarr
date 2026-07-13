"""Shared host-path sanitization for Docker / Kubernetes bind mounts.

Both computing providers accept caller-supplied paths that ultimately become
host bind mounts on the Docker daemon (or hostPath volumes in K8s). A
malformed path doesn't just produce a runtime error — a path that escapes
the intended directory exposes the host filesystem. The sanitiser enforces
the invariants both providers need: the path must be a non-empty string,
absolute, and must not contain ``..`` traversal segments after symlinks
are resolved.
"""

from __future__ import annotations

import os


def sanitize_bind_host_path(host_path: str) -> str:
    """Return the canonical absolute form of a bind host path, or raise.

    Raises ``ValueError`` for empty input, non-string input, relative paths,
    or paths whose realpath contains ``..`` traversal segments.
    """
    if not host_path or not isinstance(host_path, str):
        raise ValueError(
            f"Volume host path must be a non-empty string: {host_path!r}"
        )
    if not os.path.isabs(host_path):
        raise ValueError(
            f"Volume host path must be absolute (Docker rejects relative paths): {host_path!r}"
        )
    resolved = os.path.realpath(host_path)
    if ".." in resolved.split(os.sep):
        raise ValueError(
            f"Volume host path contains traversal segments: {host_path!r}"
        )
    return resolved
