"""Server-side pg_dump disaster-recovery helper.

The JSON export endpoints in ``api/v1/backups.py`` are a settings/config
*migration* aid, not disaster recovery. Real DR uses ``pg_dump`` custom-format
archives (plus, optionally, an Elasticsearch snapshot — the index is otherwise
rebuildable from Postgres — and a separate media-file backup). This module
provides a small pg_dump helper shared by the admin API and a scheduled worker
task.

``pg_dump`` must be on the container ``PATH``. In the default deployment the
Postgres client tools live only in the ``db`` container, so this helper no-ops
gracefully (logging a hint to use ``deployment/backup/backup.sh``) when
``pg_dump`` is unavailable. See ``deployment/backup/README.md`` for the primary,
fully-featured backup path.
"""

from __future__ import annotations

import asyncio
import logging
import os
import shutil
import urllib.parse
from datetime import UTC, datetime
from pathlib import Path

from pyrate.config import settings
from pyrate.services.task_events import record_worker_task_event

logger = logging.getLogger(__name__)

_DEFAULT_BACKUP_DIR = "/backups"


def pg_dump_available() -> bool:
    """Return True if a ``pg_dump`` binary is on PATH."""
    return shutil.which("pg_dump") is not None


def backup_dir() -> Path:
    """Directory pg_dump archives are written to (``PYRATE_BACKUP_DIR``)."""
    return Path(os.environ.get("PYRATE_BACKUP_DIR", _DEFAULT_BACKUP_DIR))


def _pg_dump_dsn() -> str:
    """Turn the app's async SQLAlchemy URL into a libpq-compatible DSN."""
    url = settings.database_url
    for async_scheme in ("postgresql+asyncpg://", "postgresql+psycopg://"):
        if url.startswith(async_scheme):
            return "postgresql://" + url[len(async_scheme):]
    return url


def _pg_dump_conn() -> tuple[str, dict[str, str]]:
    """Return a password-stripped DSN plus the subprocess env carrying PGPASSWORD.

    The database password is passed out-of-band via the ``PGPASSWORD`` env var
    rather than inlined in the DSN, so the secret never appears in the process
    command line (``/proc/<pid>/cmdline`` / ``ps``). Host, port, dbname and any
    libpq query params (e.g. ``sslmode``) are preserved in the DSN.
    """
    dsn = _pg_dump_dsn()
    parsed = urllib.parse.urlsplit(dsn)
    if not parsed.password:
        return dsn, dict(os.environ)

    userinfo, _, hostpart = parsed.netloc.rpartition("@")
    username = userinfo.split(":", 1)[0]
    sanitized_netloc = f"{username}@{hostpart}" if username else hostpart
    sanitized_dsn = urllib.parse.urlunsplit(
        parsed._replace(netloc=sanitized_netloc)
    )
    env = dict(os.environ)
    env["PGPASSWORD"] = urllib.parse.unquote(parsed.password)
    return sanitized_dsn, env


async def run_pg_dump_backup(reason: str = "scheduled") -> dict:
    """Write a ``pg_dump --format=custom`` archive to :func:`backup_dir`.

    Returns a status dict. When ``pg_dump`` is not installed the call is a
    graceful no-op (``{"skipped": "pg_dump_unavailable"}``) rather than an
    error, so a scheduled task in an image without client tools does not spam
    failures — the shell scripts are the primary path.
    """
    if not pg_dump_available():
        logger.warning(
            "pg_dump not on PATH; skipping server-side backup. "
            "Use deployment/backup/backup.sh as the primary backup path."
        )
        return {"skipped": "pg_dump_unavailable", "reason": reason}

    out_dir = backup_dir()
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out_file = out_dir / f"pyrate-db-{ts}.dump"

    dsn, env = _pg_dump_conn()
    cmd = [
        "pg_dump",
        "--format=custom",
        "--no-owner",
        "--no-privileges",
        f"--file={out_file}",
        f"--dbname={dsn}",
    ]
    logger.info("Starting pg_dump backup (reason=%s) -> %s", reason, out_file)
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        err = stderr.decode("utf-8", errors="replace")[:2000]
        logger.error("pg_dump failed (rc=%s): %s", proc.returncode, err)
        await record_worker_task_event(
            task_id="database_backup",
            category="maintenance",
            status="failed",
            message="pg_dump backup failed",
            error=err,
        )
        raise RuntimeError(f"pg_dump failed: {err}")

    size = out_file.stat().st_size if out_file.exists() else 0
    logger.info("pg_dump backup complete: %s (%s bytes)", out_file, size)
    await record_worker_task_event(
        task_id="database_backup",
        category="maintenance",
        status="completed",
        message=f"pg_dump wrote {out_file.name} ({size} bytes)",
    )
    return {"status": "completed", "file": str(out_file), "bytes": size, "reason": reason}
