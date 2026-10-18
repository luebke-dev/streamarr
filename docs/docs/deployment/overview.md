# Deployment Overview

streamarr.media ships four supported deployment models, each with a clearly assigned role and a single source of truth in the repository's `deployment/` directory. Change the maintained file for your target — never a downstream copy.

## The four models

| Model | Path | Target | Status |
|-------|------|--------|--------|
| **Helm chart** | `deployment/helm/streamarr` | Kubernetes / production | Authoritative for K8s |
| **Docker Compose (prod)** | `deployment/docker/docker-compose.yml` | Single-host production, pre-built registry images | Authoritative for single-host prod |
| **Root Compose (dev)** | `docker-compose.yml` (repo root) | Local development, all images built locally | Not a production artifact |
| **Podman quadlets** | `deployment/quadlets/*.container` + `streamarr.network` | Single-host Podman + systemd | Lean SABnzbd-only variant |

!!! tip "Rules of thumb"
    Kubernetes → **Helm** (nothing else is kept current for K8s). One box with Docker → **`docker/docker-compose.yml`** or the installer. One box with Podman/systemd → **quadlets**. Hacking on the code → the repo-root compose file.

## Single-host production

The prod Compose file pulls images from `registry.gitlab.com/streamarr.media`. For a fresh box, the interactive installer bootstraps everything:

```bash
git clone https://github.com/luebke-dev/streamarr.git
sudo bash streamarr/deployment/install.sh
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

### The shared network

The units address each other by container name (`streamarr-postgres`, `streamarr-redis`, `streamarr-elasticsearch`, `streamarr-lightrays`). That lookup only works on a network with the built-in DNS server enabled, and Podman's default network ships with DNS **off**. Left on the default network, every unit resolves nothing and the stack fails at startup on the first database connection.

The `streamarr.network` unit in `deployment/quadlets/` defines such a network, and each container unit joins it with `Network=streamarr.network`. Install the `.network` file alongside the `.container` files, otherwise the units cannot start.

The subnet is `10.89.0.0/24`. Change it in `streamarr.network` if that range is already in use.

### Podman's socket

Two units need the container runtime socket, because they start other containers:

| Unit | Why |
|------|-----|
| `streamarr-backend` | Spawns FFmpeg transcode containers |
| `streamarr-lightrays` | Spawns the per-session game containers |

Both units ship mounting `/var/run/docker.sock`, which is the Docker path. Podman listens elsewhere, so on a Podman host point the bind at Podman's socket instead. Because the socket still lands on `/var/run/docker.sock` inside the container, nothing else changes:

```ini
# Rootful Podman
Volume=/run/podman/podman.sock:/var/run/docker.sock:rw,z

# Rootless Podman (root's own socket)
Volume=/run/user/0/podman/podman.sock:/var/run/docker.sock:rw,z
```

!!! warning "Enable the socket service first"
    The socket file only exists once `podman.socket` is running, otherwise the unit starts with an empty mount and container spawning fails at runtime:

    ```bash
    sudo systemctl enable --now podman.socket
    ```

    If Podman rejects the `:z` SELinux label on a socket, drop it. Sockets are never relabelled.

Podman's API is Docker-compatible, and the pieces Streamarr needs were checked against a Podman 5.4 socket: create, start, inspect, logs, exec and the network list all behave as expected, and the Docker API version prefix is accepted. Two behaviours differ from Docker and are worth knowing: a `logs?follow=true` request does not return its HTTP response until the first line arrives, and the Docker socket does not exist at all unless the compatibility shim (`podman-docker`) is installed. That is exactly why the bind above is needed.

The backend's **Docker Host** setting (Admin → Computing) also accepts a Podman URL, for the case where the socket is mounted somewhere other than `/var/run/docker.sock`.

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

Disaster recovery is a `pg_dump --format=custom` archive, and Streamarr produces them itself: the backend image ships the Postgres client tools, the nightly `scheduled_database_backup` task writes one into `STREAMARR_BACKUP_DIR` (default `/backups`, mounted from `<data>/backups` in every compose variant and a dedicated PVC in the chart), and `POST /api/backups/disaster-recovery/pg-dump` does it on demand (`GET /api/backups/disaster-recovery/status` reports availability). Restore with `pg_restore`, run the migrations, and reindex — Elasticsearch holds nothing that is not rebuildable from PostgreSQL, so it needs no separate backup. Media files are best handled by whatever your host already does (snapshots, restic, rclone), since they dwarf everything else and change slowly. This is deliberately separate from the in-app settings export described in [Maintenance & Backups](../administration/maintenance.md). For first-time setup, start with [Installation](../getting-started/installation.md).
