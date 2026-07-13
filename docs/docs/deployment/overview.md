# Deployment Overview

streamarr.media ships four supported deployment models, each with a clearly assigned role and a single source of truth in the repository's `deployment/` directory. Change the maintained file for your target — never a downstream copy.

## The four models

| Model | Path | Target | Status |
|-------|------|--------|--------|
| **Helm chart** | `deployment/helm/streamarr` | Kubernetes / production | Authoritative for K8s |
| **Docker Compose (prod)** | `deployment/docker/docker-compose.yml` | Single-host production, pre-built registry images | Authoritative for single-host prod |
| **Root Compose (dev)** | `docker-compose.yml` (repo root) | Local development, all images built locally | Not a production artifact |
| **Podman quadlets** | `deployment/quadlets/*.container` | Single-host Podman + systemd | Lean SABnzbd-only variant |

!!! tip "Rules of thumb"
    Kubernetes → **Helm** (nothing else is kept current for K8s). One box with Docker → **`docker/docker-compose.yml`** or the installer. One box with Podman/systemd → **quadlets**. Hacking on the code → the repo-root compose file.

## Single-host production

The prod Compose file pulls images from `registry.gitlab.com/streamarr.media`. For a fresh box, the interactive installer bootstraps everything:

```bash
curl -fsSL https://get.streamarr.media | sudo bash
```

It installs Docker (Debian/Fedora/RHEL), generates secrets with `openssl rand`, writes a `chmod 600` `.env` plus a systemd unit, and emits a **generated subset** of the maintained Compose file with only the services you opt into. For the full service set (the three Rust downloaders in addition to SABnzbd), deploy `docker/docker-compose.yml` directly — it remains the source of truth.

## Kubernetes (Helm)

The chart is published as an OCI artifact:

```bash
helm install streamarr oci://registry.gitlab.com/streamarr.media/deployment/streamarr \
  --namespace streamarr --create-namespace \
  --set secrets.postgresPassword=$(openssl rand -hex 32) \
  --set secrets.secretKey=$(openssl rand -hex 32) \
  --set secrets.lightraysJwtSecret=$(openssl rand -hex 32) \
  --set secrets.downloaderWebhookSecret=$(openssl rand -hex 32)
```

Production options in `values.yaml`:

- **External PostgreSQL** — set `postgres.enabled: false` and point `postgres.external` at a CloudNativePG cluster (`existingSecret` supported).
- **Persistence** — `persistence.mode: pvc` (default; needs RWX-capable storage such as NFS, CephFS, or Longhorn-RWX) or `hostPath`, mounting `<hostPath.base>/data/{key}` off the node filesystem.
- **Ingress/TLS** — optional single-host Ingress with separate paths for frontend, backend, and Lightrays.
- **GPU & node pools** — `lightrays.gpu.enabled`, plus `nodeSelector`s to pin app, gaming, and transcode workloads to dedicated pools.

The backend auto-detects Kubernetes and runs FFmpeg, ffprobe, chromaprint, and trickplay work as **per-task Job pods**. The chart provisions the required ServiceAccount and Role (jobs, pods, pods/log) and forwards `transcoding.nodeSelector`/`tolerations` to every spawned Job.

!!! warning "Known caveats"
    - **Lightrays has no Kubernetes session provider yet** — it mounts the host Docker socket, so schedule it on a node running Docker as the container runtime, not pure containerd.
    - **`hostPath` persistence is required** when transcode Job pods must see the same files as the app pods; pin both to the same node pool.
    - **The Rust usenet downloader runs off-cluster** in the Helm model and is reached via `downloaders.usenetRemote.url` or an rclone-mounted download share.

## Podman quadlets

The leanest single-host option: systemd `.container` units with SABnzbd as the **only** downloader — no Rust downloader services and no nginx backend proxy (the backend unit publishes port 8000 directly). Secrets come from `EnvironmentFile=/etc/streamarr/streamarr.env` (`root:root`, mode `0600`); without it the units start with empty passwords and paths.

## Migrations, secrets, Elasticsearch

Database migrations run as a dedicated **one-shot step** before any app process starts — app containers never race to apply DDL:

=== "Compose"
    A `migrate` service runs `alembic upgrade head` once; backend, worker, and scheduler declare `depends_on: migrate (service_completed_successfully)`.

=== "Helm"
    A `pre-install,pre-upgrade` hook Job applies migrations once per release before the Deployments roll out (`migrations.enabled`, default `true`).

=== "Quadlets"
    `streamarr-migrate.container` is a `Type=oneshot` unit; the app units order themselves `After=`/`Requires=` it.

Secrets are never committed. Compose reads a git-ignored `.env` (copy `docker/.env.example`; keys: `SECRET_KEY`, `POSTGRES_PASSWORD`, `LIGHTRAYS_JWT_SECRET`, `DOWNLOADER_WEBHOOK_SECRET`); Helm uses the `secrets:` values block or `secrets.existingSecret` and fails fast when one is missing; quadlets use the systemd EnvironmentFile above.

!!! note "Elasticsearch is pinned to 9.2.0"
    The backend's Python client requires 9.x and refuses the handshake against an 8.x server. Every model pins **Elasticsearch 9.2.0** (`ES_IMAGE_TAG` in Compose, `elasticsearch.image.tag` in Helm, hardcoded in the quadlet).

## Service topology and ports

The stack: one-shot migrate, FastAPI backend, TaskIQ workers plus a singleton scheduler, the Quasar frontend, Lightrays game streaming, downloaders (SABnzbd and/or the Rust torrent/spotify/usenet services), PostgreSQL 16, Redis 7, and Elasticsearch 9.2.0. The dev Compose and Helm additionally run an nginx proxy in front of the backend.

Default host ports on the single-host prod model (all overridable via `.env`):

| Service | Port | Notes |
|---------|------|-------|
| Frontend | `3000` | `FRONTEND_PORT` (dev compose maps 3001) |
| Backend API | `8000` | `BACKEND_PORT` |
| Lightrays | `8009` | `network_mode: host` for WebRTC UDP (`LIGHTRAYS_PORT`) |
| SABnzbd | `8080` | `SABNZBD_PORT` |
| spotify / torrent / usenet downloaders | `3001` / `3002` / `3003` | each serves `:3000` internally |
| PostgreSQL / Redis / Elasticsearch | loopback or unpublished | not exposed by default |

## Observability and disaster recovery

The dev Compose ships Prometheus (v2.55.1) and a fully provisioned Grafana with the "streamarr.media Overview" dashboard (`observability/`); in production, point your own Prometheus at the backend's `/metrics` endpoint and the worker metrics port. See [Monitoring](../administration/monitoring.md).

Real disaster recovery lives in `deployment/backup/`: `backup.sh`/`restore.sh` wrap `pg_dump --format=custom`/`pg_restore`, tar the config, optionally snapshot Elasticsearch (the index is rebuildable from PostgreSQL via the admin reindex endpoints), optionally tar media, and can push sets off-site via rclone or S3 with retention pruning. This is deliberately separate from the in-app settings export described in [Maintenance & Backups](../administration/maintenance.md). For first-time setup, start with [Installation](../getting-started/installation.md).
