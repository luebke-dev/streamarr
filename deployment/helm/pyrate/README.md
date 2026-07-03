# pyrate Helm chart

In-tree Helm chart for the pyrate.media stack. Mirrors the services from
`docker-compose.yml` (minus the off-cluster usenet downloader and the
in-flight rust backend).

## Quick start

The chart is published as an OCI artifact alongside the container
images:

```bash
helm install pyrate oci://registry.gitlab.com/pyrate.media/deployment/pyrate \
  --version 0.1.0 \
  --namespace pyrate --create-namespace \
  --set secrets.postgresPassword=$(openssl rand -hex 32) \
  --set secrets.secretKey=$(openssl rand -hex 32) \
  --set secrets.lightraysJwtSecret=$(openssl rand -hex 32) \
  --set secrets.downloaderWebhookSecret=$(openssl rand -hex 32)
```

Or install from a local checkout:

```bash
helm install pyrate ./deployment/helm/pyrate \
  --namespace pyrate --create-namespace \
  --set secrets.postgresPassword=$(openssl rand -hex 32) \
  --set secrets.secretKey=$(openssl rand -hex 32) \
  --set secrets.lightraysJwtSecret=$(openssl rand -hex 32) \
  --set secrets.downloaderWebhookSecret=$(openssl rand -hex 32)
```

To use the production nginx routing config from this repo:

```bash
helm install pyrate ./deployment/helm/pyrate \
  ... \
  --set-file backend.proxy.nginxConfig=backend/proxy/nginx.conf
```

## Production: CloudNativePG + transcode pool

Skip the chart's in-tree Postgres and point at a CloudNativePG cluster:

```yaml
# values-prod.yaml
postgres:
  enabled: false
  external:
    host: pyrate-cluster-rw
    user: pyrate
    database: pyrate
    existingSecret:
      name: pyrate-cluster-app   # CloudNativePG default
      passwordKey: password

# Mount data directly off the node FS so the Kubernetes computing provider
# can spawn FFmpeg Job pods that hostPath-mount the same directories.
persistence:
  mode: hostPath
  hostPath:
    base: /var/lib/pyrate          # must exist on every transcode node

# Pin pyrate workloads to the transcode pool.
worker:
  replicas: 2
  nodeSelector:
    pyrate.media/role: transcode
backend:
  python:
    nodeSelector:
      pyrate.media/role: transcode

# Where the per-task FFmpeg Job pods land.
transcoding:
  nodeSelector:
    pyrate.media/role: transcode
  jobTtlSeconds: 3600
  gpuLimit: 0   # bump when nvidia/intel device plugin is in place

lightrays:
  enabled: true
  nodeSelector:
    pyrate.media/role: gaming
  gpu:
    enabled: true

ingress:
  enabled: true
  className: nginx
  host: pyrate.example.com
  tls:
    secretName: pyrate-tls
```

## Computing provider — FFmpeg & chromaprint Jobs

The backend's computing service auto-detects Kubernetes when it sees a
ServiceAccount token at `/var/run/secrets/kubernetes.io/serviceaccount`
and uses `KubernetesComputingProvider` (`backend/src/pyrate/computing/kubernetes.py`)
to create one Job per task. The chart wires this up with:

* a `ServiceAccount` (`<release>-compute` by default) bound to a `Role`
  granting `jobs` (create/get/list/watch/delete), `pods` (get/list/watch),
  and `pods/log` (get) — see `templates/rbac.yaml`
* `serviceAccountName` on backend-python and worker pods
* `COMPUTING_NAMESPACE`, `COMPUTING_JOB_TTL_SECONDS`,
  `COMPUTING_NODE_SELECTOR_JSON`, `COMPUTING_TOLERATIONS_JSON` envs from
  the `transcoding.*` values

The backend reads `COMPUTING_NODE_SELECTOR_JSON` /
`COMPUTING_TOLERATIONS_JSON` at startup and forwards them as
`node_selector` / `tolerations` kwargs into every `start_task()` call,
so all FFmpeg, ffprobe, chromaprint, and trickplay Job pods inherit the
configured pool pinning. Per-call kwargs win over env defaults, so a
specific task type can override the global pool.

Because `services/computing.py:_data_root()` builds **host paths** for
the spawned containers, transcode-eligible nodes still need the data
layout under `<persistence.hostPath.base>/data/{library,downloads,…}`.
That's exactly what `persistence.mode: hostPath` mounts into the worker,
so the worker pod and the spawned Job pods see the same files.

## What's in the chart

| Component        | Kind         | Notes                                                                 |
|------------------|--------------|-----------------------------------------------------------------------|
| postgres         | StatefulSet  | RWO PVC, pg_stat_statements + slow-query log preconfigured            |
| redis            | StatefulSet  | RWO PVC                                                               |
| elasticsearch    | StatefulSet  | RWO PVC, optional privileged init for `vm.max_map_count`              |
| backend (proxy)  | Deployment   | nginx, ConfigMap-driven, ClusterIP `:8000`                            |
| backend-python   | Deployment   | FastAPI; mounts shared data; uses `<release>-compute` SA              |
| worker           | Deployment   | TaskIQ; default 2 replicas; uses `<release>-compute` SA               |
| scheduler        | Deployment   | Singleton                                                             |
| frontend         | Deployment   | Quasar SPA on nginx, ClusterIP `:3000`                                |
| lightrays        | Deployment   | Disabled by default. Privileged + hostPath state + optional GPU       |
| spotdl           | Deployment   | Webhook-driven Spotify downloader                                     |
| torrent          | Deployment   | UDP/6881 DHT exposed via NodePort by default                          |
| RBAC             | SA + RoleB.  | `<release>-compute`: jobs + pods + pods/log inside the namespace      |
| ingress          | Ingress      | Optional. Single host, separate paths for frontend/backend/lightrays  |

## Persistence modes

| Mode       | What it does                                              | When to use                                                                                  |
|------------|-----------------------------------------------------------|----------------------------------------------------------------------------------------------|
| `pvc`      | Creates RWX PVCs and mounts them into pyrate pods         | Default. OK when transcoding doesn't need to spawn separate pods (e.g. small dev clusters)   |
| `hostPath` | Mounts `<hostPath.base>/data/{key}` directly on each pod  | Required for FFmpeg Job pods to see the same files. Pin pyrate pods + transcode Jobs to the same node pool |

## Caveats

* **Lightrays still uses the host docker socket** for spawning gaming
  containers — no Kubernetes provider for it yet. The lightrays template
  mounts `/var/run/docker.sock` as `hostPath`. Schedule it on a node that
  runs Docker as the container runtime, not pure containerd.
* **The docker-compose path is unchanged.** Compose (vydra prod) still
  runs worker/backend/lightrays with `privileged: true` + docker.sock —
  the auto-detect in `utils/environment.py` falls back to the Docker
  provider when no SA token is present. Same image, both worlds.
* **RWX PVCs in `pvc` mode.** NFS, CephFS, or Longhorn-RWX work; hostPath
  PV provisioners don't.
* **Usenet downloader is out of scope.** It runs off-cluster and is
  reached via rclone-mounted downloads (or the
  `downloaders.usenetRemote.url` value in this chart).
