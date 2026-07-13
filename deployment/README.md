# streamarr.media deployment

This directory holds the deployment models for streamarr.media. To avoid drift they
now have **clearly assigned roles and a single source of truth per target**
(Architecture 3.1). Change the maintained file for a target, not a downstream
copy.

## Roles — which model is authoritative for what

| Model | Path | Target | Status |
|-------|------|--------|--------|
| **Helm chart** | `helm/streamarr` | **Kubernetes / production** | **Authoritative** for K8s. Maintained. |
| **Docker Compose (prod)** | `docker/docker-compose.yml` | **Single-host production** (pre-built registry images) | **Authoritative** for single-host prod. Maintained. |
| **Root Compose (dev)** | `../docker-compose.yml` | **Local development only** (all images built locally) | Maintained for dev; **not** a production artifact. |
| **Quadlets** | `quadlets/*.container` | Single-host **Podman / systemd** alternative | Alternative to Docker Compose prod. **SABnzbd-only variant** (see below). |
| **install.sh** | `install.sh` | Interactive single-host bootstrap | Convenience wrapper. Emits a **generated subset** of the prod Compose (see below). |

Rules of thumb:

- Deploying to Kubernetes → use **Helm**. Nothing else is kept current for K8s.
- One box, Docker → use **`docker/docker-compose.yml`** (or `install.sh`, which
  writes a subset of it).
- One box, Podman + systemd → use **quadlets** (SABnzbd-only downloader set).
- Hacking locally → use the **repo-root `docker-compose.yml`**.

When a change affects the runtime contract (a new env var, a new volume, an
image bump), apply it to Helm **and** `docker/docker-compose.yml` first, then
propagate to quadlets / root dev / install.sh as needed.

## Secret injection per model

No secrets are ever committed in clear text. Each model injects them differently:

- **Compose (root dev + `docker/` prod):** via a git-ignored `.env` file next to
  the compose file (`env_file: .env`). Copy `docker/.env.example` to `.env` and
  fill in `SECRET_KEY`, `POSTGRES_PASSWORD`, `LIGHTRAYS_JWT_SECRET`,
  `DOWNLOADER_WEBHOOK_SECRET`. `install.sh` generates these with
  `openssl rand` and writes a `chmod 600` `.env`.
- **Helm:** via the `secrets:` block in `values.yaml`. Either let the chart
  create a Secret (`templates/secrets.yaml`) from the values you pass on the CLI
  / a `-f values-prod.yaml`, or set `secrets.existingSecret` to mount a
  pre-provisioned Secret. Values default to empty so the chart fails fast if a
  secret is missing.
- **Quadlets:** via a systemd `EnvironmentFile=/etc/streamarr/streamarr.env` declared
  in every unit that references `${...}` (all except the frontend). Create that
  file `root:root`, mode `0600`, with the same keys as the Compose `.env`
  (`POSTGRES_PASSWORD`, `SECRET_KEY`, `LIGHTRAYS_JWT_SECRET`,
  `DOWNLOADER_WEBHOOK_SECRET`, plus `DATA_DIR` / `PROJECT_ROOT`). systemd expands
  the `${...}` references in the units from this file — without it the units
  start with empty passwords/paths.

## Volume / mount naming convention

Container mount points are identical across all models; only the **host**
sub-paths differ, and there is one deliberate, code-driven divergence:

| Container path | Producer | Host sub-path (dev / prod-compose / quadlet) |
|----------------|----------|----------------------------------------------|
| `/library/{movies,shows,music,books}` | libraries | `library/*` (all models) |
| `/downloads` | primary usenet download share | dev: `usenet-remote/downloads` · prod+quadlet: `sabnzbd/downloads` |
| `/usenet-downloads` | Rust usenet-downloader | `usenet/downloads` (dev + prod-compose) |
| `/spotdl-downloads` | spotdl | `spotdl/downloads` |
| `/torrent-downloads` | torrent-downloader | `torrent/downloads` |
| `/cache`, `/temp`, `/user-data` | backend/worker | `cache`, `temp`, `users` |

**The `/downloads` divergence is intentional but has a code coupling worth
knowing about.** `backend/src/streamarr/services/computing.py` bind-mounts
`${PROJECT_ROOT}/usenet-remote/downloads` into every FFmpeg/transcode container
it spawns via the host Docker socket (Docker runtime only; the Kubernetes
runtime uses the `downloads` PVC and is unaffected). So:

- **Dev** maps the backend/worker `/downloads` to `usenet-remote/downloads`,
  which matches the spawned-container path exactly — dev ships no SABnzbd, so
  the Rust usenet-downloader owns `/downloads`.
- **Prod Compose / quadlets** map `/downloads` to `sabnzbd/downloads` because
  SABnzbd is the completed-download producer there. If you rely on server-side
  transcoding on the Docker single-host model, make sure
  `${PROJECT_ROOT}/usenet-remote/downloads` resolves to the same directory as
  the backend's `/downloads` (e.g. point both `DATA_DIR/sabnzbd/downloads` and
  `PROJECT_ROOT/usenet-remote/downloads` at one path, or symlink them) — otherwise
  spawned FFmpeg jobs see an empty `/downloads`. Kubernetes/Helm is not affected.

## Service-URL / port notes

`LIGHTRAYS_URL` legitimately differs per network topology and cannot be
collapsed to a single default:

- **Root dev** — `http://lightrays:8080` (bridge network, Compose service DNS,
  internal API port 8080).
- **Quadlets** — `http://streamarr-lightrays:8080` (Podman network, container DNS).
- **Prod Compose** — `http://127.0.0.1:${LIGHTRAYS_PORT:-8009}`: lightrays runs
  `network_mode: host` for WebRTC UDP, so it binds `LIGHTRAYS_PORT` (default
  8009) directly on the host instead of the internal 8080.
- **Helm** — auto-derived from ingress settings (`lightrays.publicUrl`).

Everything else (`SECRET_KEY`, DB URL, Redis URL, ES host/port, the
`LIGHTRAYS_*` tunables) is fed from the shared `.env` / values / EnvironmentFile
so the defaults stay aligned. Ports that differ are dev-only conveniences
(e.g. the dev frontend maps `3001`, prod `3000`).

## install.sh — relationship to the maintained Compose

`install.sh` is a bootstrap convenience (installs Docker, generates secrets,
writes a systemd unit). Its `write_docker_compose` emits a **generated subset**
of `docker/docker-compose.yml` containing only the services the user opts into.
**`docker/docker-compose.yml` remains the source of truth**; the generated file
is kept intentionally aligned with it (same `migrate` one-shot, same
`ES_IMAGE_TAG` default `9.2.0`, same `sabnzbd/*` volume layout). If you need the
full service set (Rust spotdl/torrent/usenet downloaders, the backend nginx
proxy) deploy `docker/docker-compose.yml` directly rather than using the
installer. A matching note lives at the top of `write_docker_compose`.

## Quadlets: SABnzbd-only variant

The Quadlet model is the leanest single-host option and ships **SABnzbd as its
only downloader**. It intentionally does **not** include the Rust
spotdl/torrent/usenet downloader services or the backend nginx proxy that the
Docker Compose (prod) and Helm models run — the backend unit publishes port
8000 directly. If you need the full downloader set or the proxy, use the Docker
Compose prod model or Helm. Bringing the quadlets to full parity is deferred;
they are kept as the minimal Podman/systemd variant, not deprecated.

## Database migrations

Migrations run as a dedicated **one-shot step that executes exactly once**
before any application process (backend / worker / scheduler) starts. The
backend container image's default `CMD` no longer runs `alembic upgrade head`
— that keeps every app container from racing to apply DDL on startup.

How the single migration step is wired in each model:

- **Compose (root dev + `docker/` prod + `install.sh` output):** a `migrate`
  service runs `uv run alembic upgrade head` with `restart: "no"` and
  `depends_on: db (service_healthy)`. The `backend` (`backend-python`),
  `worker`, and `scheduler` services declare
  `depends_on: migrate (condition: service_completed_successfully)`, so Compose
  starts them only after the migration exits 0.

- **Helm:** a `pre-install,pre-upgrade` hook Job (`templates/migrate-job.yaml`,
  `hook-weight: -5`, `hook-delete-policy: before-hook-creation`) runs
  `alembic upgrade head` once per release before the Deployments roll out. It
  uses the `backend.python` image. Toggle via `migrations.enabled` (default
  `true`). The per-pod alembic init container was removed.

- **Quadlets:** `streamarr-migrate.container` is a `Type=oneshot`
  (`RemainAfterExit=yes`) unit running `alembic upgrade head`. The
  `streamarr-backend`, `streamarr-worker`, and `streamarr-scheduler` units order
  themselves `After=streamarr-migrate.service` and `Requires=streamarr-migrate.service`,
  so they start only once the migration has completed successfully. If you drive
  the units manually rather than via `default.target`, run
  `systemctl start streamarr-migrate.service` (and wait for it to finish) before
  starting the app units.

## Elasticsearch version

The Python client is pinned to `elasticsearch>=9.2.0` and refuses the version
handshake against an 8.x server, so every model runs Elasticsearch **9.2.0**:

- Compose (root + prod + `install.sh` output): image tag comes from
  `ES_IMAGE_TAG` (default `9.2.0`, documented in `docker/.env.example`).
- Quadlets: pinned in `streamarr-elasticsearch.container`.
- Helm: pinned via `elasticsearch.image.tag` in `values.yaml`.
