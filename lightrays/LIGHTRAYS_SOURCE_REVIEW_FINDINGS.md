# Lightrays Source Review Findings

Review date: 2026-05-12  
Reviewed revision: `f071e32`  
Scope: `src/*.rs`, Docker/runtime files, README, CI config

## Executive Summary

Lightrays is compact and pragmatic, but several responsibilities are concentrated in a few large modules: `src/server.rs` handles config-bound routing, auth, lifecycle, session storage, launch orchestration, metrics endpoints, and WebSocket signaling; `src/stream.rs` owns compositor setup, WebRTC pipeline construction, signaling callbacks, resize handling, input bridging, and teardown. The biggest risk is not style, but host security: authenticated launch requests can influence Docker images, container names, bind mounts, devices, capabilities, security options, and IPC mode while Lightrays has Docker socket access.

The recommended loop should start with security boundaries and API contracts, then move into validation, lifecycle cleanup, module extraction, and automated tests.

## Implementation Status

Implementation passes:

- 2026-05-12: initial security/lifecycle pass (commit `ee6e4eb`).
- 2026-05-15: observability, maintainability, and CI follow-up
  (commits `1ab062d`..`4426395`).

The original review findings below describe the reviewed baseline. The Pyrate references in the integration-impact section are the pre-implementation state unless explicitly noted otherwise.

### Completed in Lightrays

- Replaced browser-controlled Docker launch fields with a server-side `runtime_profile` contract. Raw `image`, `container_name`, `env`, `devices`, `mounts`, and `base_create_json` payload fields are now rejected.
- Added a narrow `docker_image` override for trusted backends on the `gow-steam` profile. It is validated as a Docker reference and falls back to `LIGHTRAYS_GOW_IMAGE` when unset.
- Bound sessions to authenticated JWT subjects and added owner/admin authorization for stop, stats, and WebSocket access.
- Removed URL query-token WebSocket auth. Browser clients now use `Sec-WebSocket-Protocol` with `["lightrays", ws_ticket]`; tickets are scoped to `lightrays:ws`, bound to `sid`, and short-lived.
- Added launch validation for resolution, FPS, bitrate, title, app id, runtime profile, keyboard layout, mouse speed, and render node.
- Added reconnect grace for short WebSocket drops and separated WebRTC-pipeline teardown from full session/container teardown.
- Switched the session reaper from age-based to idle-based, tracking `last_activity_at` on WebSocket messages.
- Added PulseAudio module tracking and unloading during stop/shutdown/failure paths.
- Redacted TURN credentials and sensitive container log tokens; container log dumps are opt-in via `LIGHTRAYS_DUMP_CONTAINER_LOGS=true`.
- Added bind-address controls for API/streaming/metrics and defaulted metrics binding to localhost.
- Removed the unused `video_source`/`audio_source` request fields entirely.
- Fixed H.264 ultra-wide scaling by actually inserting the generated `videoscale` fragment into the WebRTC pipeline.
- Added `.dockerignore` so Docker builds do not copy `target/`, `.git`, environment files, or review docs into the image context.
- Updated the README and Docker defaults for the new auth, ticket, bind-address, profile, and lifecycle settings.
- Switched `SessionInner` to `parking_lot::Mutex` (poison-free) and converted the only callback `values[i].get().unwrap()` to checked extraction with a warning.
- Extracted `auth.rs` (Principal, JWT verification, WebSocket ticket minting; with unit tests), `session_store.rs` (`AppState`, `Session`, shared cleanup), and `launch.rs` (LaunchRequest/ValidatedLaunch, validation, `build_container_config`, ICE server assembly) out of `server.rs`. `server.rs` shrank from 1592 to 979 lines and now contains only the router wiring, HTTP/WebSocket handlers, and signaling glue.
- Added Prometheus histograms for launch-stage durations (`compositor`, `pulse`, `container`), plus counters/gauges for WebSocket reconnects, idle-timeout reaps, and last container exit code per runtime profile.
- Added a CI `check` stage that runs `cargo fmt --check`, `cargo clippy --all-targets -- -D warnings` (now blocking — the baseline is at zero warnings), and `cargo test --locked` before image build/push.
- Split `docker/docker-compose.yml` into a privileged baseline plus `docker-compose.dev.yml` (auth off, verbose logging) and `docker-compose.prod.yml` (fail-fast on missing JWT secret / CORS origins, short ticket TTL, metrics on localhost only).
- Extracted `encoder.rs` (encoder detection, selection, pipeline-fragment construction) out of `stream.rs` with four new unit tests covering bitrate fragments, CQP-only encoders, the H.265 branch, and software fallback.
- Introduced a `Phase` lifecycle enum on `SessionInner` (`Created → CompositorRunning → Streaming → Stopped`). `start_compositor`, `start_webrtc`, and `stop` enforce phase transitions; `stop_webrtc_pipeline` correctly drops back to `CompositorRunning` for the reconnect grace window. Five new tests cover the guards.
- Grouped the eight individual Option fields in `SessionInner` into two typed structs (`Compositor`, `Webrtc`). `start_compositor` populates `Option<Compositor>`, `start_webrtc` constructs `Option<Webrtc>`, `stop_webrtc` takes the whole webrtc state back under one `take()`. Invalid intermediate states (e.g. webrtc_pipeline set without webrtcbin) are now unrepresentable.
- Extracted `webrtc.rs` (configure_ice + redact_turn_url, with three redaction tests).
- Extracted `pipeline/bridge.rs` (compositor → WebRTC sample pump as a free function) and `pipeline/compositor.rs` (waylanddisplaysrc startup + stale-socket cleanup). `stream.rs` dropped from 1180 to ~820 lines.
- Moved the GStreamer signal handlers (`create_offer`, `setup_signals`, `setup_data_channel`) into `webrtc.rs`. `SessionInner` and its fields gained `pub(crate)` so the handlers can read state without a shim.
- Introduced a `Runtime` trait abstracting the session-spawning backend; the Docker daemon path lives in `docker.rs` and a Kubernetes-native runtime in `k8s_runtime.rs` uses the cluster API instead of a host Docker socket. `LIGHTRAYS_RUNTIME=docker|kubernetes` picks the implementation at startup.
- Pulled the PulseAudio sink lifecycle out into a runtime-independent `pulse.rs` module — sinks are now created/unloaded the same way regardless of backend.
- Helm chart: lightrays pod drops all capabilities (`cap_drop: ALL`), pins seccomp to `RuntimeDefault`, blocks privilege escalation, and ships a ServiceAccount + Role + RoleBinding (`pods` create/get/list/watch/delete, `pods/log` get, `pods/status` get) scoped to a dedicated `lightrays-sessions` namespace. The host Docker socket is now only mounted when `lightrays.runtime: docker`.

### Completed in Pyrate

- Backend launch payload now sends only compact, allowlisted fields: `title`, dimensions, FPS, bitrate, `runtime_profile`, `app_id`, keyboard layout, mouse speed, and start flags.
- Per-game runtime images are stored under `MediaItem.extra_data.lightrays.docker_image`; the launch API validates the stored reference and forwards it as `docker_image`, leaving blank games on the Steam default image.
- Removed Pyrate-side `GOW_BASE_CREATE_JSON`, arbitrary image selection, generated container names, raw mounts/devices/env, and frontend test-launch raw Docker fields.
- Backend launch uses the Pyrate user guid as JWT `sub`, so Lightrays can bind ownership to the actual user.
- Backend stop/stats now read Redis session metadata and reject other-user access unless the caller is superuser; superuser calls use `scope=lightrays:admin`.
- Launch API now returns `websocket_url` and `ws_ticket` instead of a reusable `lightrays_token`.
- Frontend stores and passes `wsTicket`/`websocketUrl`, connects with WebSocket subprotocol auth, and no longer puts tokens in query strings.
- Frontend intentional disconnect/back actions call Pyrate `/api/lightrays/stop` instead of relying on WebSocket close.
- Frontend launch dimensions are clamped to the new Lightrays bounds before posting.
- Local Quasar dev proxy now forwards `/api/lightrays-ws` with WebSocket upgrade support.
- Compose and Helm deployment values now expose `LIGHTRAYS_PUBLIC_URL`, `LIGHTRAYS_DEFAULT_RUNTIME_PROFILE`, `LIGHTRAYS_GOW_IMAGE`, reconnect grace, and WebSocket ticket TTL.

### Pyrate-Side Follow-Ups (completed in this pass)

- Pyrate's Redis session TTL now derives from `LIGHTRAYS_SESSION_TIMEOUT_SECS` plus a 60s grace, so both sides age out together. `docker-compose.yml`, `deployment/docker/docker-compose.yml`, the deployment `.env.example`, the Helm chart values, and `_helpers.tpl` all pass the same value to backend + Lightrays. Four new unit tests cover the parser (default, explicit, invalid, negative-clamped).
- The Helm chart auto-derives `LIGHTRAYS_PUBLIC_URL` from the ingress config when both are enabled (`{scheme}://{ingress.host}{ingress.paths.lightrays}`, scheme picked from `ingress.tls.secretName`). Operators can still override with an explicit `lightrays.publicUrl`. Verified end-to-end with `helm template` against TLS, HTTP, and override scenarios.
- `tests/test_services_business.py` was leaking state through the process-global `pyrate.services.settings._cache` and had three stale tests pointing at the wrong patch target / making outdated assumptions about the trending service. Added an autouse fixture that clears the cache around every test; corrected the trending and plugin-instance tests to match current behaviour. The file went from 16 failing / 85 passing to 101 passing.

### Review Status

Every finding from the original review (P0 host control, P0 auth/ownership,
P0 WebSocket-token leakage, P1 launch validation, P1 API/README drift,
P1 PulseAudio leak, P1 sensitive-value logging, P1 module ownership,
P1 locking/unwrap hardening, P1 runtime security defaults, P1
observability, P2 idle timeout, P2 WebSocket close grace, P2 unused
request fields, P2 CI reproducibility, P2 pure-logic testability) is
addressed in code, with matching Pyrate-side changes in the backend +
frontend + Helm chart. The original "Remaining Follow-Up" cross-repo
items (Redis TTL alignment, auto-derived `LIGHTRAYS_PUBLIC_URL`,
`test_services_business.py` fixture cleanup) all landed in pyrate.media
on 2026-05-15.

### What's Not Verified Against A Live System

The KubernetesRunner spec compiles, renders correctly via `helm
template`, and parses node selectors in unit tests — but it has not
been deployed against a real cluster yet. The first live deployment
will need to validate:

* the hostPath wayland-socket share between the lightrays pod and the
  session pod (`PodSpec.nodeSelector` co-location, `fs_group: 1000` for
  socket permissions);
* audio routing between pods (the current code assumes the
  PulseAudio server is reachable from session pods — in a multi-pod
  setup this needs either a shared socket volume or a network PulseAudio
  endpoint);
* GPU access via the device plugin instead of the current hostPath
  `/dev/dri` mount, once production runs on a multi-node GPU pool.

These aren't findings from the original review — they're integration
work that follows naturally from moving the session backend to the
cluster API.

### Verification

- `docker run --rm -v /root/pyrate.media/lightrays:/work -w /work lightrays-check sh -lc 'cargo fmt -- --check && cargo test'`: 14 passed (5 baseline + 7 new auth tests + 2 launch-validation tests; was 5 before the 2026-05-15 pass).
- `docker run --rm -v /root/pyrate.media/lightrays:/work -w /work lightrays-check sh -lc 'cargo check'`: passed clean (no warnings introduced by the extraction).
- `docker build -f docker/Dockerfile --target builder -t lightrays-check .`: passed after adding `.dockerignore`; build context reduced from about 1.1 GB to a few KB of changed transfer.
- `docker compose run --rm -v /root/pyrate.media/backend/tests:/app/tests:rw,z backend-python uv run pytest tests/test_lightrays_service.py tests/api/test_lightrays_api.py -q`: 25 passed.
- `docker compose run --rm -v /root/pyrate.media/backend/tests:/app/tests:rw,z backend-python uv run pytest tests/test_services_business.py::TestSystemSettingsStorageAndLightrays::test_update_lightrays_settings -q`: 1 passed.
- `docker compose run --rm -v /root/pyrate.media/backend/tests:/app/tests:rw,z backend-python uv run ruff check src/pyrate/services/lightrays.py src/pyrate/api/v1/lightrays.py src/pyrate/services/system_settings.py tests/test_lightrays_service.py tests/api/test_lightrays_api.py`: passed.
- `docker run --rm -v /root/pyrate.media/frontend:/app -w /app node:22-alpine sh -lc 'yarn lint && yarn build'`: passed; only existing bundle/Browserslist warnings.
- `docker compose config --quiet` in `/root/pyrate.media`: passed.
- Deployment Compose syntax was checked by piping the compose file without `env_file` and exporting required env values: passed. A direct run requires the expected `deployment/docker/.env` file.

## Pyrate Integration Impact

This section compares the findings against the Pyrate integration as it existed at the reviewed revision. It focuses on changes that were needed outside this repository, especially in the backend launch proxy, frontend WebRTC client, Docker Compose deployment, and Helm chart.

### P0 - Host Control Through Launch API

**Integration impact:** Breaking contract change if Lightrays stops accepting free-form Docker launch fields.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/services/lightrays.py:21-36` defines `GOW_BASE_CREATE_JSON` with privileged container settings.
- `backend/src/pyrate/services/lightrays.py:129-158` sends `image`, `container_name`, `env`, `devices`, `mounts`, `base_create_json`, `app_id`, and optionally `render_node`.
- `frontend/src/composables/useLightraysStreaming.js:53-73` still has an admin/test launch path that can send raw Docker fields directly to Lightrays.
- `backend/src/pyrate/services/system_settings.py:690-724` exposes `lightrays.default_image`, which assumes Pyrate can choose arbitrary images.

**Required Pyrate changes:**

- Replace the backend launch payload with a constrained contract such as `app_id`, `profile_id` or `runtime_profile`, `title`, `width`, `height`, `fps`, and `bitrate_kbps`.
- Remove `GOW_BASE_CREATE_JSON` from Pyrate or replace it with a small profile name such as `gow-steam` that Lightrays resolves server-side.
- Stop generating `container_name` in `backend/src/pyrate/services/lightrays.py:102-107`; Lightrays should generate reserved-prefix names.
- Remove or repurpose the `lightrays.default_image` setting. If Pyrate still needs configurable game images, store only allowlisted profile ids, not arbitrary Docker image strings.
- Keep `app_id=f"{user_guid}-{media_guid}"` only as an application state key if Lightrays continues to accept external state ids. If not, split this into explicit `owner_sub`, `media_id`, and `state_key` fields.
- Remove raw Docker launch controls from the frontend test launcher or move it behind an admin-only catalog/profile selector.
- Update `backend/tests/test_lightrays_service.py` to assert the new compact payload and to verify privileged fields are no longer emitted.

### P0 - Auth Is Token-Valid, Not User/Session-Authorized

**Integration impact:** Direct behavior change. If Lightrays binds sessions to the launch token subject, Pyrate's current launch flow would produce owner mismatches.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/services/lightrays.py:60-66` sends backend-to-Lightrays API requests with a service token using `sub=pyrate-backend`.
- `backend/src/pyrate/api/v1/lightrays.py:140-147` returns a browser-facing token using `sub=<current_user.guid>`.
- `backend/src/pyrate/api/v1/lightrays.py:151-193` proxies stop and stats without checking that the Redis session belongs to the current user before calling Lightrays.

**Required Pyrate changes:**

- Define a claim contract between Pyrate and Lightrays. Either launch sessions with a user-subject token, or use a service token with explicit `owner_sub` and `scope` claims that Lightrays understands.
- If Lightrays requires owner-subject tokens for launch, change `_auth_headers()` or `launch_session()` so the backend sends `sub=<current_user.guid>` for launch, while preserving a separate service/admin token for maintenance operations.
- If stop/stats remain backend-proxied, add ownership checks in `backend/src/pyrate/api/v1/lightrays.py` using `pyrate:lightrays:session:{session_id}` before calling `stop_session()` or `get_stats()`.
- Add tests where user A cannot stop or inspect user B's Lightrays session.
- Add an admin/service scope path for legitimate backend cleanup jobs, because owner-only enforcement would otherwise block server-side reapers.

### P0 - WebSocket Token In URL Can Leak

**Integration impact:** Direct frontend and API response change.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/api/v1/lightrays.py:41-45` exposes `lightrays_token` in the launch response.
- `frontend/src/composables/useGameLaunch.js:27-29` stores that token.
- `frontend/src/components/GameStreamView.vue:128-131` passes it to the streaming composable.
- `frontend/src/composables/useLightraysStreaming.js:97-100` sends the token as `?token=...` on the WebSocket URL.

**Required Pyrate changes:**

- Replace `lightrays_token` with a short-lived one-time `ws_ticket`, or with a value intended for `Sec-WebSocket-Protocol`.
- Change `connectWebSocket()` to avoid query tokens, for example `new WebSocket(url, ["lightrays", ticket])` if Lightrays implements protocol-based auth.
- Ensure frontend nginx, Vite dev proxy, Docker ingress, and Helm ingress preserve `Sec-WebSocket-Protocol` and `Upgrade` headers.
- If Lightrays exposes a ticket exchange endpoint, call it from Pyrate backend after launch and return only the ticket to the browser.
- Remove token-bearing WebSocket URLs from logs and browser-visible diagnostics.

### P1 - Launch Input Validation Is Too Loose

**Integration impact:** Mostly compatible if Pyrate pre-validates before Lightrays rejects. Without backend validation, users will see generic 502 launch failures.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/api/v1/lightrays.py:34-39` accepts unbounded `width`, `height`, `fps`, and `bitrate_kbps`.
- `frontend/src/composables/useGameLaunch.js:12-24` derives launch dimensions from viewport and device pixel ratio without an explicit maximum.
- `backend/src/pyrate/services/lightrays.py:85-86` forwards user gaming preferences for `keyboard_layout` and `mouse_speed`.

**Required Pyrate changes:**

- Add Pydantic bounds to `LaunchRequest`, matching the Lightrays limits. Suggested initial limits: width `64..7680`, height `64..4320`, fps `15..120`, bitrate `500..50000`.
- Clamp or validate frontend launch dimensions before `POST /api/lightrays/launch/{media_id}`.
- Validate user gaming preferences before forwarding them. Restrict keyboard layouts to known XKB layout ids and mouse speed to a documented range.
- Convert Lightrays 400/422 responses into user-facing validation errors instead of always returning 502.
- Add API tests for invalid launch dimensions and invalid gaming preferences.

### P1 - API Contract And README Drift

**Integration impact:** Direct route/proxy decision needed. Pyrate currently does not use the `ws_url` returned by Lightrays.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/api/v1/lightrays.py:41-45` returns only `session_id`, `lightrays_token`, and `ice_servers`; it drops Lightrays' `ws_url`.
- `frontend/src/composables/useLightraysStreaming.js:97-100` hardcodes `/api/lightrays-ws/{session_id}` on the current browser host.
- `docker-compose.yml:179-180` publishes Lightrays API and streaming ports separately.
- `deployment/docker/docker-compose.yml:133-156` uses host networking and sets `LIGHTRAYS_API_PORT=${LIGHTRAYS_PORT:-8009}`.
- `deployment/helm/pyrate/values.yaml:341-357` defines a separate ingress path for Lightrays, but the frontend does not consume that path dynamically.

**Required Pyrate changes:**

- Decide the browser-facing WebSocket contract in one place. Prefer returning a ready-to-use `websocket_url` from Pyrate's launch endpoint.
- Either proxy `/api/lightrays-ws/:session_id` through Pyrate deployment consistently, or return a Lightrays-specific path such as `/lightrays/api/lightrays-ws/:session_id`.
- Update `LaunchResponse`, `useGameLaunch()`, `GameStreamView.vue`, and `useLightraysStreaming.js` to consume `websocket_url` instead of constructing the path internally.
- Add Vite dev proxy and production nginx/ingress rules for the chosen WebSocket path.
- Add backend API tests that assert the launch response contains the expected browser WebSocket URL for local Docker and Helm-style deployments.

### P1 - PulseAudio Sink Lifecycle Leaks

**Integration impact:** Lightrays-internal cleanup, but Pyrate's session bookkeeping should be aligned.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/services/lightrays.py:198-259` tracks active sessions in Redis with a six-hour TTL.
- `frontend/src/components/GameStreamView.vue:172-175` closes the WebSocket on disconnect but does not call Pyrate's `/api/lightrays/stop`.
- `lightrays/src/server.rs:970-972` currently stops the Lightrays session when the WebSocket closes, so Pyrate Redis can remain stale until TTL.

**Required Pyrate changes:**

- When the user intentionally disconnects, call Pyrate's `/api/lightrays/stop` before or after closing the WebSocket.
- Add a backend reconciliation path that removes Redis session records when Lightrays reports 404 for stats or when a container death event is observed.
- If Lightrays adds reconnect grace periods, distinguish "temporary websocket disconnect" from "user requested stop" in the frontend.
- Align Redis TTL with `LIGHTRAYS_SESSION_TIMEOUT_SECS` or refresh it through explicit heartbeats.

### P1 - Sensitive Values Are Logged

**Integration impact:** Mostly compatible, but deployment logging should change with the auth work.

**Pre-implementation Pyrate dependency:**

- `backend/src/pyrate/services/lightrays.py:160` logs title, image, and resolution.
- `.env` and deployment values carry TURN credentials that Lightrays can currently log through the GStreamer TURN URL.
- Query-string WebSocket tokens can appear in frontend, proxy, or ingress access logs.

**Required Pyrate changes:**

- Avoid logging raw launch payloads once tickets, profile ids, or runtime profiles are added.
- If WebSocket query tokens remain temporarily, disable query-string logging or redact `/api/lightrays-ws` access logs in nginx/ingress.
- Mark `LIGHTRAYS_TURN_PASSWORD` and related values as secret-only in Helm and deployment docs.

### P1 - Large Modules Obscure Ownership Boundaries

**Integration impact:** No required Pyrate contract change, but tests should guard the integration while Lightrays is refactored.

**Required Pyrate changes:**

- Add contract tests around the exact launch payload Pyrate sends.
- Add a mocked Lightrays API test for launch, stop, stats, and WebSocket URL response shape.
- Keep Pyrate changes small while Lightrays modules are split, because the integration surface should be the HTTP/WebSocket contract rather than internal Rust modules.

### P1 - Runtime Security Defaults Are Broad

**Integration impact:** Deployment changes required if Lightrays runtime profiles become stricter.

**Pre-implementation Pyrate dependency:**

- `docker-compose.yml:150-180` runs Lightrays privileged with Docker socket and `/dev/dri`.
- `deployment/docker/docker-compose.yml:129-156` runs Lightrays privileged with host networking and Docker socket.
- `deployment/helm/pyrate/templates/lightrays.yaml:52-130` supports privileged mode, host Docker socket, hostPath runtime/state dirs, and optional GPU hostPath.

**Required Pyrate changes:**

- Split local/dev and production Lightrays deployment profiles.
- Add explicit Helm values for allowed runtime profiles, image allowlists, metrics bind/exposure, and whether Docker socket access is enabled.
- Document the required host paths and privileges as part of the Pyrate deployment guide, not only the Lightrays README.
- If Lightrays moves to a restricted Docker policy, make Pyrate's Compose/Helm defaults match that policy so launches do not fail at runtime.

### P1 - Observability Is Too Thin For Stream Debugging

**Integration impact:** Optional but useful for support/debugging.

**Required Pyrate changes:**

- Expose a backend admin endpoint that combines Pyrate Redis session metadata with Lightrays session/container health.
- Add frontend/admin diagnostics for launch stage, ICE state, container death, and reconnect reason once Lightrays exports them.
- If Lightrays metrics bind to localhost by default, add deployment-specific metrics scraping configuration instead of exposing the metrics port publicly.

### P2 - Session Timeout Is Age-Based, Not Idle-Based

**Integration impact:** Direct session accounting issue.

**Pre-implementation Pyrate dependency:**

- Lightrays defaults `LIGHTRAYS_SESSION_TIMEOUT_SECS` to one hour.
- Pyrate considers Redis Lightrays sessions stale only after `LIGHTRAYS_SESSION_MAX_SECONDS = 6 * 60 * 60` in `backend/src/pyrate/services/lightrays.py:15-19`.

**Required Pyrate changes:**

- Align Pyrate's active-session TTL with the Lightrays timeout, or make it configurable from the same environment value.
- If Lightrays switches to idle timeout, refresh Pyrate Redis session metadata on stream activity or periodic frontend heartbeat.
- Surface timeout reason to the frontend so a user sees "session timed out" rather than a generic stream error.

### P2 - WebSocket Close Immediately Tears Down Sessions

**Integration impact:** Frontend behavior change if reconnect grace is added.

**Pre-implementation Pyrate dependency:**

- `frontend/src/composables/useLightraysStreaming.js:112-114` treats WebSocket close as idle/disconnected unless already in error.
- `frontend/src/components/GameStreamView.vue:123-126` stops the local stream on component unmount.
- Lightrays currently tears down the server-side session on WebSocket close.

**Required Pyrate changes:**

- If Lightrays adds reconnect grace, keep `session_id` and ticket state alive across reloads or short navigation interruptions.
- Add an explicit "terminate stream" path that calls Pyrate `/api/lightrays/stop`; do not rely on WebSocket close for intentional cleanup.
- Update reconnect UI states so transient WebSocket disconnects do not immediately send the user back to the media page.

### P2 - Unused Request Fields And Configuration Drift

**Integration impact:** Direct cleanup in the admin/test launch path.

**Pre-implementation Pyrate dependency:**

- `frontend/src/composables/useLightraysStreaming.js:70-72` sends `render_node`, `video_source`, and `audio_source` from `appConfig`.

**Required Pyrate changes:**

- Remove `video_source` and `audio_source` from Pyrate frontend payloads unless Lightrays implements them.
- Restrict or remove `render_node` from frontend-originated config; if still needed, expose it as a server-side deployment setting or allowlisted admin profile.

### P2 - Docker Image And CI Reproducibility

**Integration impact:** CI/deployment coordination.

**Required Pyrate changes:**

- Add a Pyrate integration test job that starts or mocks Lightrays and verifies backend launch payload compatibility.
- Update deployment build pipelines so Lightrays image checks run before publishing Pyrate stacks that depend on a changed contract.
- Keep backend tests runnable in Docker, because the local host may not have the Python/Rust toolchains installed.

### P2 - Pure Logic Is Not Testable Enough

**Integration impact:** No runtime contract change, but Pyrate should own its side of the contract.

**Required Pyrate changes:**

- Add unit tests for `create_lightrays_token()`, launch payload generation, owner/session Redis bookkeeping, and invalid user access to stop/stats.
- Add frontend tests for WebSocket URL/ticket construction once the token transport changes.
- Add deployment smoke tests for the selected WebSocket route in local Compose and Helm-style ingress.

## P0 - Host Control Through Launch API

**Finding:** `POST /api/launch` accepts host-sensitive Docker parameters directly from the client: `image`, `container_name`, `env`, `devices`, `mounts`, and `base_create_json` in `src/server.rs:424-431`. These values flow into `ContainerConfig` at `src/server.rs:601-609`, then into Docker host config in `src/docker.rs:177-181` and `src/docker.rs:215-239`. The request can also choose `container_name`; `start_container` stops/removes any existing container with the same name before creation (`src/docker.rs:174-175`, `src/docker.rs:199-211`).

**Risk:** Any caller with a valid token can potentially stop arbitrary host containers by naming them, mount arbitrary host paths, add device access, grant capabilities, change security options, or pull arbitrary images. Because the service runs with Docker socket access and often host networking, this is effectively host-level control.

**Goal:** Move from client-controlled Docker config to a server-side launch policy.

**Suggested work:**

- Replace free-form Docker fields with an allowlisted app catalog keyed by app id.
- Generate container names server-side with a reserved prefix and reject caller-supplied names outside that namespace.
- Validate `image` against an allowlist or immutable digest list.
- Replace `base_create_json` with a small typed enum of allowed runtime profiles.
- Restrict mounts and devices to configured prefixes and known device names.
- Add tests for rejected container names like `pyratemedia-db-1`, host mounts such as `/:/host`, and capability escalation.

## P0 - Auth Is Token-Valid, Not User/Session-Authorized

**Finding:** JWT validation only requires a valid `exp` claim (`src/server.rs:61-84`). The optional `sub` claim is not used for session ownership. Stop, stats, and WebSocket handlers accept any valid token for any `session_id` (`src/server.rs:733-743`, `src/server.rs:747-801`, `src/server.rs:808-823`).

**Risk:** A token minted for one user can stop, inspect, or attach to another user's active session if the session id is known or leaked. Session ids are 64-bit random strings (`src/server.rs:520-521`), which helps against guessing, but does not create an authorization boundary.

**Goal:** Bind sessions to authenticated principals and enforce ownership.

**Suggested work:**

- Parse and require `sub`, `aud`, and optionally `iss` depending on the issuer contract.
- Store `owner_sub` or user id on `Session`.
- Enforce owner or admin permissions in `/api/stop`, `/api/stats/:session_id`, and WebSocket upgrade.
- Return 404 or 403 consistently without revealing whether another user's session exists.
- Prefer short-lived, one-time WebSocket session tokens over long-lived bearer tokens in query strings.

## P0 - WebSocket Token In URL Can Leak

**Finding:** WebSocket auth explicitly accepts `?token=` (`src/server.rs:120-147`), and the README documents a WebSocket flow where clients connect directly to a session URL. Query parameters commonly appear in access logs, browser history, reverse proxy logs, and monitoring tooling.

**Risk:** A leaked query token may authorize control of the stream until expiry. This is especially sensitive because input events can drive the remote desktop.

**Goal:** Remove URL-borne bearer credentials.

**Suggested work:**

- Prefer `Authorization: Bearer` for WebSocket clients where supported.
- For browsers/proxies where headers are difficult, use `Sec-WebSocket-Protocol` or exchange the API bearer token for a short-lived one-time WebSocket ticket.
- Redact tokens in logs at proxy and service boundaries.
- Add an expiry and single-use store for WebSocket tickets.

## P1 - Launch Input Validation Is Too Loose

**Finding:** `handle_launch` accepts raw `width`, `height`, `fps`, `bitrate_kbps`, `render_node`, `title`, and `app_id` with defaults but no bounds (`src/server.rs:479-488`). Resize validation exists later (`src/stream.rs:998-1004`), but launch does not reuse it. `render_node` is inserted into a GStreamer pipeline string without escaping (`src/stream.rs:270-278`).

**Risk:** Invalid dimensions and frame rates can cause high resource usage or pipeline failures. A malicious or malformed `render_node` string may break pipeline parsing or inject unexpected properties/elements depending on GStreamer parse behavior.

**Goal:** Introduce a typed, validated request layer.

**Suggested work:**

- Add request validation for width/height/fps/bitrate with explicit min/max values.
- Validate `render_node` against an allowlist such as `/dev/dri/renderD*` or force server-side render-node selection.
- Validate `title` and `app_id` length and allowed characters.
- Reject bad requests with 400/422 before starting compositor, PulseAudio, or Docker work.
- Use shared validation for launch and resize paths.

## P1 - API Contract And README Drift

**Finding:** The launch response returns `"ws_url": "/ws/{session_id}"` (`src/server.rs:719-724`), and README documents `WebSocket /ws/:session_id` (`README.md:69`, `README.md:83`). The actual routers expose `/api/lightrays-ws/:session_id` on both API and streaming routers (`src/server.rs:197`, `src/server.rs:206`). Config names also drift: README lists `LIGHTRAYS_HTTP_PORT` (`README.md:30`), while code uses `LIGHTRAYS_API_PORT` and `LIGHTRAYS_STREAMING_PORT` (`src/config.rs:61-68`). Docker socket defaults also differ between code and docs/entrypoint: `src/docker.rs:57-59` defaults to `/run/docker.sock`, while README and entrypoint use `/var/run/docker.sock`.

**Risk:** New clients will connect to the wrong WebSocket path or set ignored environment variables. This creates avoidable integration failures.

**Goal:** Make route and config contracts single-source and tested.

**Suggested work:**

- Either register `/ws/:session_id` as an alias or change `ws_url` to `/api/lightrays-ws/{session_id}`.
- Update README and sample compose to the same env variable names used in `ServerConfig`.
- Add a small route/contract test around `handle_launch` response shape.
- Generate README config tables from a documented config schema where practical.

## P1 - PulseAudio Sink Lifecycle Leaks

**Finding:** Lightrays creates a per-session PulseAudio sink with `pactl load-module module-null-sink` (`src/docker.rs:70-115`) but does not store the returned module id and never unloads the module. `stop_session` stops GStreamer and Docker only (`src/server.rs:333-350`). Launch failure after sink creation only calls `stream.stop()` (`src/server.rs:576-642`).

**Risk:** Repeated failed or completed sessions leave PulseAudio modules behind. Over time this can pollute audio state and make routing/debugging harder. Setting the default sink per session also has global side effects.

**Goal:** Make session resources RAII-style and fully reversible.

**Suggested work:**

- Capture `pactl load-module` output module id.
- Store the module id in `Session`, not only the sink name.
- Unload the module in `stop_session`, `stop_all_sessions`, and all launch failure paths.
- Avoid changing the global default sink; route per-container via `PULSE_SINK`.
- Add a failure-path test with a mocked PulseAudio runner.

## P1 - Sensitive Values Are Logged

**Finding:** The GStreamer TURN URL is built as `turn://user:pass@host` (`src/server.rs:859-870`) and then logged by `configure_ice` (`src/stream.rs:640-643`). Docker container logs are dumped wholesale on early exit (`src/server.rs:686-692`, `src/docker.rs:339-364`), which may include user environment values supplied via launch.

**Risk:** TURN passwords, bearer tokens from proxies, game credentials, or other secrets can land in persistent logs.

**Goal:** Add centralized log redaction.

**Suggested work:**

- Redact TURN credentials before logging ICE config.
- Redact known env keys such as `PASSWORD`, `TOKEN`, `SECRET`, `KEY`, and `CREDENTIAL`.
- Avoid logging full arbitrary container logs at warning level in production; gate full log tails behind debug or a feature flag.
- Add tests for redaction helpers.

## P1 - Large Modules Obscure Ownership Boundaries

**Finding:** `src/server.rs` is 1022 lines and `src/stream.rs` is 1124 lines. `server.rs` mixes routing, auth, config-dependent CORS, session lifecycle, launch orchestration, metrics, and WebSocket signaling. `stream.rs` mixes encoder selection, pipeline string generation, compositor lifecycle, WebRTC callbacks, data channel handling, resize handling, input bridge, and teardown.

**Risk:** Changes in one workflow can unintentionally affect another. This also raises the cost of testing because most logic is hidden behind concrete process/GStreamer/Docker effects.

**Goal:** Split by behavior and dependency boundary.

**Suggested module split:**

- `auth.rs`: JWT verification, principal extraction, WS ticket support.
- `routes.rs`: Axum route assembly and HTTP handlers.
- `session_store.rs`: session map, ownership checks, timeout/idle reaper.
- `launch.rs`: launch validation and orchestration.
- `webrtc.rs`: signaling and WebRTC message handling.
- `pipeline/encoder.rs`: encoder selection and pipeline fragments.
- `pipeline/compositor.rs`: compositor startup and socket handling.
- `pipeline/bridge.rs`: appsrc/appsink bridge loop.
- `pulse.rs`: PulseAudio sink/module lifecycle.

## P1 - Locking And `unwrap()` In Streaming Path Need Hardening

**Finding:** `StreamSession` uses `std::sync::Mutex` and many `lock().unwrap()` calls in GStreamer callbacks and public methods (`src/stream.rs:265`, `src/stream.rs:376`, `src/stream.rs:615`, `src/stream.rs:677`, `src/stream.rs:781`, `src/stream.rs:874`, `src/stream.rs:896`, `src/stream.rs:913`, `src/stream.rs:921`, `src/stream.rs:937`, `src/stream.rs:981`, `src/stream.rs:1035`, `src/stream.rs:1070`, `src/stream.rs:1101`, `src/stream.rs:1122`). Some lock scopes include blocking GStreamer setup or teardown work, especially `start_compositor`, `start_webrtc`, and `stop_webrtc`.

**Risk:** A panic while holding the mutex poisons the session and later `unwrap()` calls can panic. Long blocking work under the same lock can delay callbacks, input handling, resize, and teardown. In the worst case, callback re-entry can deadlock or stall a stream.

**Goal:** Make the streaming state machine resilient under callback failure and resize/teardown races.

**Suggested work:**

- Replace `std::sync::Mutex` with a poison-free mutex such as `parking_lot::Mutex`, or handle `PoisonError` explicitly.
- Keep lock scopes to state reads/writes; do GStreamer `set_state`, bus waits, promise work, and thread joins outside the lock.
- Add a `StreamState` enum and reject illegal transitions instead of relying on `Option` state.
- Convert callback `unwrap()` on signal values to checked extraction with warnings.
- Add stress tests or a small harness for concurrent resize, stop, and input calls.

## P1 - Runtime Security Defaults Are Broad

**Finding:** The compose example uses host networking, Docker socket access, `/dev/input`, `/dev/dri`, `/etc/lightrays`, and `SYS_ADMIN`/`NET_ADMIN` (`docker/docker-compose.yml:22-63`). The entrypoint enables PulseAudio anonymous TCP for private RFC1918 networks (`docker/entrypoint.sh:81-84`) and chmods PulseAudio runtime paths/socket to `777` (`docker/entrypoint.sh:79`, `docker/entrypoint.sh:111`).

**Risk:** These choices may be required for game streaming, but they should be treated as privileged mode. Broad defaults increase blast radius if the Lightrays process or an app container is compromised.

**Goal:** Document and minimize privilege per deployment mode.

**Suggested work:**

- Create separate `dev`, `local-trusted`, and `production` compose profiles.
- Remove or narrow PulseAudio TCP auth where possible; prefer UNIX sockets with group permissions.
- Avoid `chmod 777` by aligning UID/GID and group ownership.
- Document why each capability/mount/device is required.
- Add a hardened production deployment example with explicit reverse proxy assumptions.

## P1 - Observability Is Too Thin For Stream Debugging

**Finding:** Metrics cover counts for sessions, containers, WebRTC connections, and launch errors (`src/metrics.rs:13-110`). They do not expose launch duration, compositor startup time, ICE state transitions, bridge frame rate, frames dropped, resize failures, active container states, or PulseAudio failures. Metrics are exposed on a public `0.0.0.0` listener (`src/server.rs:213-220`) with no auth (`src/server.rs:210-211`, `src/server.rs:353-366`).

**Risk:** Stream failures require log spelunking. Public metrics can disclose runtime information if the port is exposed.

**Goal:** Make stream health measurable and restrict metrics exposure.

**Suggested work:**

- Add histograms for launch duration by stage: compositor, PulseAudio, Docker, WebRTC.
- Add gauges/counters for bridge FPS, pushed frames, push errors, resize attempts/failures.
- Add container uptime and last exit-code metrics per internal app type, avoiding high-cardinality session ids.
- Add bind address config for each listener; default metrics to localhost or require explicit exposure.
- Optionally protect metrics with a separate token or network policy.

## P2 - Session Timeout Is Age-Based, Not Idle-Based

**Finding:** `session_timeout_reaper` stops sessions solely by `created_at.elapsed() > timeout` (`src/server.rs:389-410`). It does not account for active WebSocket/WebRTC traffic or user input.

**Risk:** Long but active sessions can be killed at a fixed wall-clock age, while idle sessions under the timeout stay alive.

**Goal:** Reap idle sessions, not merely old sessions.

**Suggested work:**

- Track `last_activity_at` on WebSocket messages, ICE state changes, and data-channel input.
- Reap sessions when idle duration exceeds the configured timeout.
- Expose the timeout reason in logs and metrics.

## P2 - WebSocket Close Immediately Tears Down Sessions

**Finding:** `handle_websocket` calls `stop_session` whenever the WebSocket loop exits (`src/server.rs:970-973`).

**Risk:** A page reload, transient proxy disconnect, or browser network hiccup destroys the whole desktop session immediately. That may be surprising for users and causes unnecessary container churn.

**Goal:** Add a short reconnect grace period.

**Suggested work:**

- Mark session as disconnected and schedule delayed cleanup.
- Cancel cleanup if the same user reconnects within a short grace window.
- Keep explicit `/api/stop` as immediate cleanup.
- Track reconnect counts and timeout reasons.

## P2 - Unused Request Fields And Configuration Drift

**Finding:** `LaunchRequest` includes `video_source` and `audio_source` (`src/server.rs:440-442`), but current launch logic does not use them. `StreamSession` hardcodes compositor-to-WebRTC source behavior and only derives audio from PulseAudio sink or test tone (`src/server.rs:851-856`, `src/stream.rs:422-432`).

**Risk:** API consumers may believe these fields work. Dead fields also make validation and documentation harder.

**Goal:** Remove or implement unused fields.

**Suggested work:**

- Remove `video_source` and `audio_source` from the public request until supported.
- Or implement an explicit enum for source mode: compositor, videotestsrc, external pipeline, PulseAudio, audiotestsrc.
- Add API documentation examples for each supported mode.

## P2 - Docker Image And CI Reproducibility

**Finding:** CI only builds and pushes the container image (`.gitlab-ci.yml:1-28`). It does not run `cargo fmt`, `cargo clippy`, unit tests, dependency audit, or a smoke test. Local verification in this environment could not run because `cargo` is not installed. The Docker build installs Rust through a shell pipe and clones `gst-wayland-display` from GitHub at a short revision (`docker/Dockerfile:31-40`).

**Risk:** Formatting, lint regressions, unused code, and security advisories are only caught late or not at all. The upstream dependency build is partially pinned but still harder to reproduce and audit.

**Goal:** Add fast checks before image publish.

**Suggested work:**

- Add CI stages for `cargo fmt --check`, `cargo clippy -- -D warnings`, `cargo test`, and `cargo audit` or `cargo deny`.
- Add unit tests for pure functions: config validation, CORS parsing, Docker config parsing, title sanitization, input mapping, launch validation.
- Pin upstream `gst-wayland-display` with a full commit SHA and document patch refresh steps.
- Consider caching dependencies or using a Rust builder image pinned by digest.

## P2 - Pure Logic Is Not Testable Enough

**Finding:** There are no `#[test]`, `tokio::test`, or `mod tests` blocks in `src/`. Several pure helpers could be tested now: `build_ice_servers`, `build_cors_layer`, `sanitize_title`, `parse_host_config_overrides`, `parse_device_mapping`, `js_code_to_linux`, `browser_button_to_linux`, and config port validation.

**Risk:** Future cleanup in large modules will be risky without behavioral guardrails.

**Goal:** Establish a low-friction unit-test layer before refactors.

**Suggested work:**

- Move pure helpers into small modules with `pub(crate)` functions and local tests.
- Add validation tests for security-sensitive rejects.
- Add integration tests for launch response contract with a fake Docker runner.
- Use traits for Docker/PulseAudio/GStreamer boundaries so handlers can be tested without the real host environment.

## Suggested Implementation Order

1. **Contract fix:** Align `ws_url`, registered routes, README env names, and Docker socket defaults. In Pyrate, return a browser-ready `websocket_url` from `/api/lightrays/launch/{media_id}` and update the frontend to consume it instead of hardcoding `/api/lightrays-ws`.
2. **Security gate:** Replace free-form Docker launch fields with a policy/allowlist layer. In Pyrate, remove `image`, `container_name`, `devices`, `mounts`, and `base_create_json` from the emitted launch payload and switch to profile/catalog ids.
3. **Ownership:** Parse JWT principal and enforce session ownership for stop/stats/WebSocket. In Pyrate, define the token claim contract, launch with the correct user owner, and check Redis ownership before stop/stats.
4. **WebSocket auth:** Remove URL query bearer tokens. In Pyrate, replace `lightrays_token` with a short-lived ticket or WebSocket subprotocol value and update proxies/ingress to preserve the required headers.
5. **Validation:** Add typed launch validation and render-node allowlist before any resource allocation. In Pyrate, add Pydantic constraints and frontend clamping so bad input fails before hitting Lightrays.
6. **Lifecycle:** Track and unload PulseAudio modules; add failure-path cleanup guards. In Pyrate, explicitly call `/api/lightrays/stop` for intentional disconnects and add Redis reconciliation for sessions that Lightrays cleans up itself.
7. **Redaction:** Sanitize TURN URLs, env values, and container log output. In Pyrate, avoid query token logging and keep TURN credentials secret-only in deployment config.
8. **Tests/CI:** Add unit tests for pure logic and CI checks before image build/push. In Pyrate, add backend payload/ownership tests, frontend WebSocket URL/ticket tests, and Docker-run integration tests.
9. **Refactor:** Split `server.rs` and `stream.rs` along the module boundaries above while keeping the HTTP/WebSocket contract stable for Pyrate.
10. **Observability:** Add stream-health metrics and bind/auth hardening for metrics. In Pyrate, combine Redis session state with Lightrays health in admin/debug views.
11. **Session resilience:** Add idle-based timeout and reconnect grace. In Pyrate, align Redis TTL with Lightrays timeout and keep session/ticket state through short reconnect windows.

## Verification Notes

- `git status -sb` was clean before creating this report.
- `cargo check` was attempted but could not run in this environment because `cargo` is not installed.
- No automated Rust tests were found in the repository.
