# Transcoding

Transcoding converts media on the fly into a stream the client can actually play, delivered as HLS. streamarr.media never runs FFmpeg inside the backend — every transcode, probe, and trickplay job runs in its own **disposable container**.

The runtime is auto-detected and shown as a chip next to the page title under **Admin → Transcoding**:

=== "Docker (single host)"

    FFmpeg runs as a *sibling* container via the host Docker socket. Because mounts are resolved by the host Docker daemon, the `PROJECT_ROOT` variable in your `.env` must be the **absolute host path** of the installation — a container path will break the volume mounts.

=== "Kubernetes"

    FFmpeg runs as short-lived **Jobs** using a dedicated ServiceAccount (created by the Helm chart's RBAC). The chart's `transcoding.*` values control the Job namespace, TTL, node selector, tolerations, and an optional GPU request (`transcoding.gpuLimit`). See the [Deployment Overview](../deployment/overview.md).

!!! tip "The bundled FFmpeg image"
    The **FFmpeg Docker Image** setting accepts any image with `ffmpeg`/`ffprobe` on its PATH (default: `lscr.io/linuxserver/ffmpeg:latest`). streamarr.media also ships its own image based on **jellyfin-ffmpeg** (`deployment/docker/ffmpeg/Containerfile`) with VA-API, Vulkan, and OpenCL libraries plus chromaprint for audio fingerprinting.

## Direct play vs. transcoding

Transcoding is a fallback, not the default. When a user presses play:

1. The client reports its capabilities — the web player detects supported codecs itself, cast targets and registered devices use a **playback profile**.
2. The server compares them with the source file. If codecs, container, resolution, and bitrate all fit, the file is **direct-played** untouched.
3. Otherwise an FFmpeg container is started and the player receives an HLS stream. Seeking starts a fresh transcode from the new position.

Built-in playback profiles exist for `browser`, `chromecast`, and `dlna_generic`; custom profiles (codecs, containers, max resolution/bitrate, direct-play flags) can be managed via `GET`/`PUT /api/play/profiles`. Users can see whether they are transcoding — and why — in the player's **Stream Info** dialog (see [Streaming & Playback](../user-guide/streaming.md)).

## Settings

Navigate to **Admin → Transcoding**.

| Section | Setting | Notes |
|---------|---------|-------|
| General | **Enable transcoding** | Master switch. When off, only directly compatible files can be played. |
| General | **FFmpeg Docker Image** | Image used for transcode, probe, and trickplay containers. |
| General | **Temporary Directory** | Where HLS segments and trickplay sprites are written. Needs disk space. |
| Video | **Allowed Video Codecs** | H.264, H.265/HEVC, AV1, VP9. The actual codec is negotiated with the client; H.264 is the compatibility baseline. |
| Video | **Maximum Resolution** | 480p up to 2160p (4K). |
| Video | **Default Video Bitrate** | Fixed bitrate; leave empty for CRF mode. |
| Video | **CRF Value** | 0–51, default 23. Recommended 18–28. Ignored when a bitrate is set. |
| Audio | **Allowed Audio Codecs** | AAC, Opus, MP3. |
| Audio | **Default Audio Bitrate** | 128k is fine for most content, 256k+ for music. |
| Performance | **Enable hardware acceleration** | See below. |
| Performance | **Threads** | 0 = FFmpeg decides. |
| Performance | **Prefer compatible codecs for downloads** | Makes automatic release selection favor codecs your users can direct-play. |
| Performance | **HLS Segment Duration** | 2–15 s, default 6. Shorter = faster seeking, more overhead. |

Per-user and per-group limits — **Max Concurrent Streams**, **Max Concurrent Transcodings** (0 = no transcoding allowed), and video/audio quality caps — are set on groups, see [Users & Groups](user-management.md). A server-wide concurrent-transcode cap also exists (`transcoding.max_concurrent_transcodes`, 0 = unlimited, settings API only); when it is reached, players show "Server transcoding capacity reached".

## Hardware acceleration

When enabled, the backend looks for GPU render nodes (`/dev/dri/renderD128`, `/dev/dri/card0`) and passes them into each FFmpeg container, using Intel QuickSync (QSV) encoders when found. You can pin a specific device path in the **Hardware Device** field.

!!! warning "The GPU must be visible to the backend"
    On Docker, `/dev/dri` has to be passed through to the backend/worker containers for detection to work, and `ENABLE_HARDWARE_ACCEL` must not be `false` in the environment. On Kubernetes, request GPUs for transcode Jobs via `transcoding.gpuLimit` and a matching device plugin.

## Trickplay

Timeline scrubbing thumbnails are generated automatically alongside every video transcode session: a second FFmpeg container extracts one frame every 10 seconds and tiles them into 10×10 WebP sprite sheets in the temp directory. The player picks them up as soon as the first sheet is ready — no library-scan job is required.

## Monitoring sessions and logs

- **Admin → Active Sessions** lists running transcoding sessions (user, content, codecs, duration, progress, status) plus device sessions, with per-session **View Details** and **Terminate**, plus **Terminate All** and a **Cleanup** action for orphaned temp files and stale sessions.
- **Admin → Logs** streams the live FFmpeg container log of any transcoding session, with selectable line count and auto-refresh.
- Scheduled cleanup ("Clean Orphaned Temp Files", "Clean Stale Transcoding Sessions") runs from **Admin → Tasks** — see [Maintenance & Backups](maintenance.md). Stream counts and transcode storage appear on the [Dashboard](dashboard.md) and in [Monitoring](monitoring.md).

!!! tip
    Start in CRF mode and only pin a bitrate if you must cap bandwidth. If streams buffer, lower the maximum resolution or raise the CRF value — and watch the temp directory, active streams can consume several GB.
