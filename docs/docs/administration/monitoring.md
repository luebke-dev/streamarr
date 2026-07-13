# Monitoring

streamarr.media can be monitored on two levels: inside the app via the admin UI (dashboard, active sessions, logs, watch parties) and from the outside via Prometheus metrics, a provisioned Grafana dashboard, health probes, and Postgres query statistics.

## Monitoring in the admin UI

- The **[Admin Dashboard](dashboard.md)** shows system health, active streams, downloads, user counts, and storage at a glance.
- **Admin** → **Active Sessions** lists running transcoding sessions (with terminate and cleanup actions) plus connected device sessions and what they are playing. See [Transcoding](transcoding.md) for details.
- **Admin** → **Parties** shows all active watch parties: stat cards for **Active Parties**, **Connected Users**, and **Total Members**, and a table with name, owner, media, members, guest control, created/expires times. Admins can end a party, which disconnects all members.

### Logs

**Admin** → **Logs** combines two views:

**Transcoding session logs** — pick a transcoding session (each option shows title, user, and video/audio codec, with a green marker for running sessions), choose how many lines to tail (50–1000), and press **Load**. The **Auto** toggle re-fetches the log every few seconds for live monitoring.

**Activity Logs** — a filterable table of application events with columns **Created**, **Severity**, **Event Type**, **Entity Type**, and **Message**. Filter by event type, severity (`info` / `warning` / `error`), entity type, and date range.

!!! tip
    Full process logs go to the container's stdout — use `docker compose logs backend-python` (or `kubectl logs`). Set `LOG_LEVEL` and `LOG_FORMAT=json` on the backend/worker for structured log shipping; every API request is logged with a request ID that is also returned in the `X-Request-ID` response header.

## Health endpoints

The backend serves two unauthenticated probes at the application root (not under `/api`), intended for Docker healthchecks, Kubernetes probes, and load balancers:

| Endpoint | Purpose | Behavior |
|----------|---------|----------|
| `/healthz` | Liveness | Cheap, no external I/O — answers whether the process serves HTTP |
| `/readyz` | Readiness | Checks PostgreSQL, Redis, and Elasticsearch; returns **503** with per-check `up`/`down` status when any dependency is down |

## Prometheus metrics

**Backend** — the API exposes `/metrics` on port 8000: standard HTTP metrics (request counts, latency histograms, in-progress requests) plus `streamarr_*` domain metrics such as `streamarr_media_items_total`, `streamarr_downloads_total`, `streamarr_websocket_connections`, `streamarr_service_health`, and `streamarr_storage_bytes`. Database-backed gauges are refreshed by a sampler every 30 seconds (`STREAMARR_METRICS_SAMPLE_INTERVAL_SECONDS`).

!!! warning "Metrics are fail-closed"
    `/metrics` returns **404** until you set the `METRICS_TOKEN` environment variable on the backend, and then requires `Authorization: Bearer <token>`. The endpoint reveals route names, user counts, and latency data — keep it off the public internet even with a token.

**Worker** — each Taskiq worker serves its own metrics on port `9100` (`WORKER_METRICS_PORT`): task throughput and failures (`streamarr_worker_task_events_total`), indexer and download counters, and a `streamarr_worker_up` gauge. This port is unauthenticated, so expose it only on the internal container network.

```yaml
scrape_configs:
  - job_name: streamarr-backend
    metrics_path: /metrics
    authorization:
      credentials: <METRICS_TOKEN value>
    static_configs:
      - targets: ["backend-python:8000"]
  - job_name: streamarr-worker
    static_configs:
      - targets: ["worker:9100"]
```

!!! note
    With multiple worker replicas behind one Compose DNS name, scrapes round-robin across replicas. Counter rates summed across the job stay correct; for per-replica accuracy use per-instance discovery (e.g. Kubernetes pod discovery).

## Grafana dashboard

The development Compose stack ships Prometheus (port 9090) and Grafana (port 3005, default login `admin` / `streamarr`) with an auto-provisioned datasource and the **streamarr.media Overview** dashboard (22 panels). For the other [deployment models](../deployment/overview.md), point your own Prometheus at the endpoints above and import `observability/grafana/dashboards/streamarr-overview.json`.

| Panel group | Panels |
|-------------|--------|
| API traffic | Request rate, error rate, latency percentiles, requests by status, top-10 slowest API handlers |
| Library & users | Media items, media files, missing artwork, user/device/favorite/list signals |
| Downloads | Active downloads, status transitions & retries, downloader client jobs, indexer searches |
| Caches & rendering | Artwork cache files/size/events, rendered layout cache events and render p95 |
| Workers & realtime | Worker task events by category and status, WebSocket connections |
| Health & storage | Per-component service health, downloader client health, storage used per path |

## Postgres query statistics

The development Compose file and the Helm chart provision PostgreSQL with `pg_stat_statements` (tracking all statements) and slow-query logging: any statement over **500 ms** is written to the Postgres log. On other deployments, add the same server flags to get identical visibility.

```sql
SELECT calls, round(mean_exec_time) AS avg_ms, query
FROM pg_stat_statements
ORDER BY mean_exec_time DESC
LIMIT 10;
```

For database backups and storage cleanup, see [Maintenance & Backups](maintenance.md).
