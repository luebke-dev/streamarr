# Developer Guide Overview

pyrate.media is a monorepo: a Python backend, a Quasar/Vue frontend, several Rust services, and everything needed to deploy and observe the stack. This page orients you in the repository and gets a development environment running. For running the stack in production, see the [Deployment Overview](../deployment/overview.md).

## Monorepo layout

| Path | Contents |
|------|----------|
| `backend/` | FastAPI REST API + TaskIQ workers (Python 3.13, SQLModel/SQLAlchemy async, Alembic) |
| `frontend/` | Quasar 2 / Vue 3 SPA — web, Tauri 2 desktop, Capacitor 7 Android |
| `lightrays/` | WebRTC game-streaming server (Rust, GStreamer) |
| `downloaders/` | `torrent/`, `spotify/`, `usenet/` — standalone Rust downloader services |
| `deployment/` | Docker Compose, Helm chart, Podman quadlets, installer, backup tooling |
| `containers/` | Wine and RetroArch game-streaming images |
| `observability/` | Prometheus config and provisioned Grafana dashboard |
| `docs/` | This MkDocs Material site |

Each component has its own README with deeper development notes. The backend serves the API under `/api/v1` and a WebSocket at `/api/ws`; data lives in PostgreSQL 16, Redis 7 (queue/cache/pub-sub), and Elasticsearch 9.2 (search index).

## Running the full stack

The root `docker-compose.yml` builds all images locally and starts the complete stack — nginx backend proxy, API, worker, scheduler, frontend, Lightrays, the three downloaders, PostgreSQL, Redis, Elasticsearch, Prometheus, and Grafana. Create a `.env` in the repo root first (at minimum `SECRET_KEY`, `DATABASE_URL`, `REDIS_URL`), then:

```bash
docker compose up -d --build
```

!!! note "Migrations run as a one-shot service"
    The `migrate` service runs `alembic upgrade head` once; API, worker, and scheduler wait for it to complete. You never race migrations by scaling workers.

## Working on a single component

=== "Backend (uv)"

    The backend uses [uv](https://docs.astral.sh/uv/) — not pip or Poetry — and requires Python ≥ 3.13.

    ```bash
    cd backend
    uv sync

    # API with hot reload
    uv run uvicorn pyrate.web:app --reload --port 8000

    # Background worker and cron scheduler
    uv run taskiq worker pyrate.worker:broker
    uv run taskiq scheduler pyrate.worker:scheduler

    # Database migrations
    uv run alembic upgrade head
    ```

    Key packages under `backend/src/pyrate/`: `api/` (routers), `models/` and `schemas/`, `services/`, `libraries/` (library-type plugins), `indexers/`, `downloaders/`, `metadata/`, `workers/`, `smart_collections/`, `overlays/`.

=== "Frontend (yarn)"

    Node 20+ and Yarn. The dev server runs on **:9000** and proxies `/api` to the backend on **:8000** (and `/api/lightrays-ws` to Lightrays on **:8009**), so run it against a local or compose-started backend.

    ```bash
    cd frontend
    yarn install
    yarn dev          # dev server on :9000 with hot reload
    yarn dev:tauri    # desktop shell against the same dev server
    yarn build        # production SPA build
    ```

=== "Rust services"

    Each downloader is a standard Cargo project:

    ```bash
    cd downloaders/torrent   # or spotify/, usenet/
    cargo build --release
    ./target/release/torrent-downloader
    ```

    Lightrays needs GStreamer and (for hardware encoding) a VA-API GPU, so it is easiest to develop through its compose override, which disables auth and bind-mounts the source:

    ```bash
    cd lightrays/docker
    docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
    ```

=== "Docs"

    The docs site is uv-managed too:

    ```bash
    cd docs
    uv sync
    uv run mkdocs serve
    ```

## Testing and linting

```bash
# Backend — tests run against in-memory SQLite
cd backend
uv run pytest
uv run pytest -k "search" -v
uv run pytest --cov=pyrate

# Frontend — Vitest + happy-dom
cd frontend
yarn test:unit        # single run
yarn test             # watch mode
yarn lint             # ESLint
yarn format           # Prettier
```

Backend linting and typing use **ruff** and **mypy** (see `[dependency-groups] dev` in `backend/pyproject.toml`); a pre-commit config is included.

## Key ports

| Service | Port (root compose) | Notes |
|---------|--------------------|-------|
| Backend (nginx proxy) | 8000 | Proxies to the FastAPI container |
| Frontend | 3001 | `yarn dev` uses **9000** instead |
| Lightrays | 8009 (API), 8099 (stream WS) | |
| Torrent / usenet / spotify downloader | 3002 / 3003 / 3004 | Each listens on 3000 internally |
| PostgreSQL / Elasticsearch | 5432 / 9200 | Bound to localhost only |
| Prometheus / Grafana | 9090 / 3005 | See [Monitoring](../administration/monitoring.md) |

!!! tip
    Trigger background jobs (scans, index sync, refreshes) from the admin **Tasks** page rather than the CLI — see the [Administration Overview](../administration/overview.md) and [Maintenance & Backups](../administration/maintenance.md).
