"""Process runner that applies persisted network settings before uvicorn starts."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os

import uvicorn

from pyrate.database import sessionmanager
from pyrate.services.network_runtime import get_network_runtime_config

logger = logging.getLogger(__name__)


async def _load_runtime_config():
    async with sessionmanager.session() as db:
        return await get_network_runtime_config(db)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run pyrate API server")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    config = asyncio.run(_load_runtime_config())

    os.environ["PYRATE_EFFECTIVE_BIND_HOST"] = config.bind_host
    os.environ["PYRATE_EFFECTIVE_BIND_PORT"] = str(config.bind_port)
    os.environ["PYRATE_EFFECTIVE_ENABLE_HTTPS"] = str(config.enable_https).lower()

    uvicorn_kwargs = {
        "host": config.bind_host,
        "port": config.bind_port,
        "reload": args.reload,
    }
    if config.enable_https:
        if config.ssl_files_present:
            uvicorn_kwargs["ssl_certfile"] = config.ssl_certificate_path
            uvicorn_kwargs["ssl_keyfile"] = config.ssl_key_path
        else:
            logger.warning(
                "HTTPS is enabled but certificate/key files are missing; "
                "starting without TLS"
            )

    uvicorn.run("pyrate.web:app", **uvicorn_kwargs)


if __name__ == "__main__":
    main()
