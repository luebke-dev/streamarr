"""Liveness and readiness probes.

These endpoints are intentionally unauthenticated and are mounted at the app
root (``/healthz`` / ``/readyz``) rather than under ``/api`` so orchestrators
(Docker healthchecks, Kubernetes probes, load balancers) can reach them without
credentials.

- ``/healthz`` — liveness: cheap, no external I/O. Answers "is the process
  running and able to serve HTTP?". Never touches the database/Redis/ES so a
  transient dependency outage does not cause the container to be killed.
- ``/readyz`` — readiness: verifies the backing services (Postgres, Redis,
  Elasticsearch) are reachable. Returns 503 when any dependency is down so
  traffic is withheld until the instance can actually serve requests.
"""

from __future__ import annotations

import logging

import redis.asyncio as redis_async
from fastapi import APIRouter
from sqlalchemy import text
from starlette.responses import JSONResponse

from pyrate.config import settings
from pyrate.database import sessionmanager
from pyrate.services.elasticsearch import elasticsearch_service

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/healthz", include_in_schema=False)
async def healthz() -> dict[str, str]:
    """Liveness probe — cheap, no external dependencies."""
    return {"status": "ok"}


async def _check_database() -> bool:
    try:
        async with sessionmanager.session() as db:
            await db.execute(text("SELECT 1"))
    except Exception:
        logger.warning("Readiness: database check failed", exc_info=True)
        return False
    return True


async def _check_redis() -> bool:
    client = redis_async.from_url(settings.redis_url)
    try:
        await client.ping()
    except Exception:
        logger.warning("Readiness: redis check failed", exc_info=True)
        return False
    else:
        return True
    finally:
        await client.aclose()


async def _check_elasticsearch() -> bool:
    try:
        return bool(
            elasticsearch_service.client and await elasticsearch_service.client.ping()
        )
    except Exception:
        logger.warning("Readiness: elasticsearch check failed", exc_info=True)
        return False


@router.get("/readyz", include_in_schema=False)
async def readyz() -> JSONResponse:
    """Readiness probe — verifies DB, Redis and Elasticsearch are reachable."""
    checks = {
        "database": await _check_database(),
        "redis": await _check_redis(),
        "elasticsearch": await _check_elasticsearch(),
    }
    ready = all(checks.values())
    return JSONResponse(
        status_code=200 if ready else 503,
        content={
            "status": "ready" if ready else "not_ready",
            "checks": {name: "up" if ok else "down" for name, ok in checks.items()},
        },
    )
