# pyrate.media deployment

This directory holds the deployment models for pyrate.media:

- `docker/docker-compose.yml` — production Docker Compose (pre-built images).
- `quadlets/*.container` — Podman Quadlet units (systemd-managed rootless/root Podman).
- `helm/pyrate` — Helm chart for Kubernetes.

The repo-root `docker-compose.yml` is the local dev stack (all images built
locally).

## Database migrations

Migrations run as a dedicated **one-shot step that executes exactly once**
before any application process (backend / worker / scheduler) starts. The
backend container image's default `CMD` no longer runs `alembic upgrade head`
— that keeps every app container from racing to apply DDL on startup.

How the single migration step is wired in each model:

- **Compose (root dev + `docker/` prod):** a `migrate` service runs
  `uv run alembic upgrade head` with `restart: "no"` and
  `depends_on: db (service_healthy)`. The `backend` (`backend-python`),
  `worker`, and `scheduler` services declare
  `depends_on: migrate (condition: service_completed_successfully)`, so Compose
  starts them only after the migration exits 0.

- **Helm:** a `pre-install,pre-upgrade` hook Job (`templates/migrate-job.yaml`,
  `hook-weight: -5`, `hook-delete-policy: before-hook-creation`) runs
  `alembic upgrade head` once per release before the Deployments roll out. It
  uses the `backend.python` image. Toggle via `migrations.enabled` (default
  `true`). The per-pod alembic init container was removed.

- **Quadlets:** `pyrate-migrate.container` is a `Type=oneshot`
  (`RemainAfterExit=yes`) unit running `alembic upgrade head`. The
  `pyrate-backend`, `pyrate-worker`, and `pyrate-scheduler` units order
  themselves `After=pyrate-migrate.service` and `Requires=pyrate-migrate.service`,
  so they start only once the migration has completed successfully. If you drive
  the units manually rather than via `default.target`, run
  `systemctl start pyrate-migrate.service` (and wait for it to finish) before
  starting the app units.

## Elasticsearch version

The Python client is pinned to `elasticsearch>=9.2.0` and refuses the version
handshake against an 8.x server, so every model runs Elasticsearch **9.2.0**:

- Compose (root + prod): image tag comes from `ES_IMAGE_TAG` (default `9.2.0`,
  documented in `docker/.env.example`).
- Quadlets: pinned in `pyrate-elasticsearch.container`.
- Helm: pinned via `elasticsearch.image.tag` in `values.yaml`.
