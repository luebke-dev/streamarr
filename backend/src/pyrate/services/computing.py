"""Computing service for executing compute-intensive tasks."""

import json
import logging
import os
from functools import lru_cache
from typing import Any

from sqlmodel.ext.asyncio.session import AsyncSession

from pyrate.computing.base import ComputingBase
from pyrate.computing.docker import DockerComputingProvider
from pyrate.computing.kubernetes import KubernetesComputingProvider
from pyrate.utils.environment import get_computing_provider_domain

logger = logging.getLogger(__name__)
DEFAULT_FFMPEG_IMAGE = "lscr.io/linuxserver/ffmpeg:latest"


@lru_cache(maxsize=1)
def _kubernetes_scheduling_kwargs() -> dict[str, Any]:
    """Read pod-scheduling overrides for spawned compute Jobs from the env.

    The Helm chart exposes ``COMPUTING_NODE_SELECTOR_JSON`` and
    ``COMPUTING_TOLERATIONS_JSON`` so an operator can pin per-task FFmpeg /
    chromaprint Job pods to a transcode pool without touching the worker
    Deployment. Only the Kubernetes provider acts on these kwargs; the
    Docker provider's ``start_task`` accepts ``**kwargs`` and silently
    ignores unknown keys, so it's safe to apply them uniformly.

    Returns an empty dict when neither variable is set or the JSON is
    malformed (in that case a warning is logged once).
    """
    out: dict[str, Any] = {}

    raw_ns = os.environ.get("COMPUTING_NODE_SELECTOR_JSON", "").strip()
    if raw_ns:
        try:
            ns = json.loads(raw_ns)
        except json.JSONDecodeError as e:
            logger.warning("Invalid COMPUTING_NODE_SELECTOR_JSON (%s): %r", e, raw_ns)
        else:
            if isinstance(ns, dict) and ns:
                out["node_selector"] = ns
            else:
                logger.warning(
                    "COMPUTING_NODE_SELECTOR_JSON must be a non-empty JSON object, got: %r",
                    raw_ns,
                )

    raw_tol = os.environ.get("COMPUTING_TOLERATIONS_JSON", "").strip()
    if raw_tol:
        try:
            tol = json.loads(raw_tol)
        except json.JSONDecodeError as e:
            logger.warning("Invalid COMPUTING_TOLERATIONS_JSON (%s): %r", e, raw_tol)
        else:
            if isinstance(tol, list) and tol:
                out["tolerations"] = tol
            else:
                logger.warning(
                    "COMPUTING_TOLERATIONS_JSON must be a non-empty JSON list, got: %r",
                    raw_tol,
                )

    if out:
        logger.info("Computing scheduling overrides from env: keys=%s", sorted(out))
    return out


# ---------------------------------------------------------------------------
# Volume mount helpers — single source of truth for sibling-container binds
# ---------------------------------------------------------------------------

# Default UID/GID used when the FFmpeg sibling container needs to write to
# bind-mounted directories owned by the backend process. Falls back to root
# only when explicitly opted-in via FFMPEG_RUN_AS_ROOT=true.
def _ffmpeg_runtime_user() -> dict[str, str]:
    if os.environ.get("FFMPEG_RUN_AS_ROOT", "false").lower() == "true":
        return {"PUID": "0", "PGID": "0"}
    puid = os.environ.get("FFMPEG_PUID") or str(os.getuid()) if hasattr(os, "getuid") else "1001"
    pgid = os.environ.get("FFMPEG_PGID") or str(os.getgid()) if hasattr(os, "getgid") else "1001"
    return {"PUID": puid, "PGID": pgid}


def _running_in_kubernetes() -> bool:
    """True when the process can see the projected service-account token.

    Mirrors ``utils.environment.get_computing_provider_domain`` so the
    bind/mount strategy follows the same detection as the provider switch.
    """
    return os.path.isdir("/var/run/secrets/kubernetes.io/serviceaccount")


def _data_root() -> str:
    """Return the host-side path to the project's ``data/`` directory.

    When running inside the backend container we honour ``PROJECT_ROOT`` (set
    by docker-compose) so that the *host* paths are passed to the Docker
    daemon — sibling containers wouldn't be able to bind paths that only
    exist inside the backend container otherwise.
    """
    if os.path.exists("/.dockerenv"):
        project_root = os.environ.get("PROJECT_ROOT", "/root/pyrate.media").rstrip("/")
        return f"{project_root}/data"
    return os.path.abspath("./data")


# PVC names used by the chart's persistence templates (`<release>-<key>`).
# In k8s the values are PVC names instead of host paths; the
# KubernetesComputingProvider already understands non-`/`-prefixed values
# as PVC references, so spawned Job pods mount the same RWX volumes the
# backend/worker already see at the in-pod paths below.
_PVC_LIBRARY = lambda: os.environ.get("PYRATE_PVC_LIBRARY", "pyrate-library")  # noqa: E731
_PVC_DOWNLOADS = lambda: os.environ.get("PYRATE_PVC_DOWNLOADS", "pyrate-downloads")  # noqa: E731
_PVC_CACHE = lambda: os.environ.get("PYRATE_PVC_CACHE", "pyrate-cache")  # noqa: E731
_PVC_TEMP = lambda: os.environ.get("PYRATE_PVC_TEMP", "pyrate-temp")  # noqa: E731


def build_media_volumes(
    *,
    include_writable_temp: bool = False,
    include_cache: bool = False,
    include_downloads: bool = True,
    include_books: bool = False,
    read_only: bool = True,
) -> dict[str, str]:
    """Build the standard set of bind mounts for ffmpeg/ffprobe.

    Two layouts are produced depending on the runtime:

    * **Docker (compose)** — host bind mounts under ``${PROJECT_ROOT}/data``.
      Each library subdir is a separate mount so individual paths can live
      on different disks if the operator chooses.
    * **Kubernetes** — PVC names, mounted once per volume at the same
      in-pod paths the backend and worker already use. The cluster's RWX
      ``pyrate-library`` PVC carries every library subdirectory under
      ``/library``, so a single mount is enough; the chart's RWX storage
      lets the spawned FFmpeg Job pod attach the same volume from any
      node. Volume names are overridable via ``PYRATE_PVC_*`` envs for
      releases with a non-default name.
    """
    if _running_in_kubernetes():
        volumes: dict[str, str] = {
            _PVC_LIBRARY(): "/library",
        }
        if include_downloads:
            volumes[_PVC_DOWNLOADS()] = "/downloads"
        if include_cache:
            volumes[_PVC_CACHE()] = "/cache"
        if include_writable_temp:
            volumes[_PVC_TEMP()] = "/temp"
        # `include_books` and `read_only` are no-ops here: the books
        # directory is part of the same library PVC, and the Kubernetes
        # provider always mounts read-write (the chart's RWX claim is the
        # authoritative ACL).
        return volumes

    root = _data_root()
    volumes = {
        f"{root}/library/movies": "/library/movies",
        f"{root}/library/shows": "/library/shows",
        f"{root}/library/music": "/library/music",
    }
    if include_books:
        volumes[f"{root}/library/books"] = "/library/books"
    if include_downloads:
        volumes[f"{root}/usenet-remote/downloads"] = "/downloads"
    if include_cache:
        volumes[f"{root}/cache"] = "/cache"
    if include_writable_temp:
        volumes[f"{root}/temp"] = "/temp"
        # Make sure the bind target exists on disk before docker tries to
        # mount it, otherwise the daemon will create a root-owned dir.
        try:
            os.makedirs("/temp" if os.path.exists("/.dockerenv") else f"{root}/temp", exist_ok=True)
        except Exception as exc:  # pragma: no cover - best effort
            logger.warning("Failed to create temp dir: %s", exc)
    return volumes


def detect_hardware_acceleration() -> dict[str, Any]:
    """
    Detect available hardware acceleration devices.

    Uses LinuxServer FFmpeg image which includes Intel QSV hardware acceleration support.
    Hardware acceleration is automatically enabled when Intel GPU devices are detected.

    To disable hardware acceleration, set ENABLE_HARDWARE_ACCEL=false environment variable.

    Returns:
        dict with keys:
            - type: 'qsv', 'vaapi', or None
            - devices: list of device paths to mount
            - encoder_suffix: suffix for encoder name (e.g., '_qsv')
    """
    # Check if hardware acceleration is explicitly disabled
    enable_hw_accel = os.environ.get("ENABLE_HARDWARE_ACCEL", "true").lower() == "true"

    result = {
        "type": None,
        "devices": [],
        "encoder_suffix": "",
    }

    if not enable_hw_accel:
        logger.info(
            "Hardware acceleration explicitly disabled (ENABLE_HARDWARE_ACCEL=false)"
        )
        return result

    # Check for Intel GPU devices
    dri_devices = []
    if os.path.exists("/dev/dri"):
        # Check for renderD128 (primary render node)
        if os.path.exists("/dev/dri/renderD128"):
            dri_devices.append("/dev/dri/renderD128")
        # Check for card0
        if os.path.exists("/dev/dri/card0"):
            dri_devices.append("/dev/dri/card0")

    if dri_devices:
        # Intel devices found - prefer QSV over VAAPI
        result["devices"] = dri_devices
        result["type"] = "qsv"  # Intel QuickSync Video
        result["encoder_suffix"] = "_qsv"
        logger.info("Detected Intel GPU devices for hardware acceleration: %s", dri_devices)
    else:
        logger.info(
            "No hardware acceleration devices detected, will use software encoding"
        )

    return result


class ComputingService:
    """
    Service for managing compute tasks using the configured computing provider.

    Automatically selects the appropriate provider (Docker or Kubernetes) based on
    environment detection or user configuration.

    Can be used as an async context manager to ensure proper cleanup:
        async with ComputingService(db) as service:
            await service.start_transcoding(...)
    """

    def __init__(self, db: AsyncSession):
        self.db = db
        self._provider: ComputingBase | None = None
        self._provider_domain: str | None = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit - ensures provider cleanup."""
        await self.close()
        return False

    async def close(self):
        """Close the computing provider and release resources."""
        if self._provider:
            try:
                await self._provider.close()
                logger.info("Closed computing provider: %s", self._provider_domain)
            except Exception as e:
                logger.error("Error closing computing provider: %s", e)
            finally:
                self._provider = None
                self._provider_domain = None

    async def get_provider(self) -> ComputingBase:
        """
        Get the active computing provider.

        Returns:
            ComputingBase instance

        Raises:
            RuntimeError: If no computing provider is configured or enabled
        """
        if self._provider:
            return self._provider

        provider_domain = get_computing_provider_domain()

        try:
            if provider_domain == "kubernetes":
                self._provider = KubernetesComputingProvider(manifest=None, plugin_config={})
            else:
                self._provider = DockerComputingProvider(manifest=None, config={})

            await self._provider.setup()

            self._provider_domain = provider_domain
            logger.info("Loaded computing provider: %s", provider_domain)
            return self._provider
        except Exception as e:
            logger.error("Failed to load computing provider '%s': %s", provider_domain, e)
            raise RuntimeError(f"Failed to load computing provider: {e}")

    async def start_task(
        self,
        image: str,
        command: list[str] | None = None,
        args: list[str] | None = None,
        env: dict[str, str] | None = None,
        volumes: dict[str, str] | None = None,
        cpu_limit: str | None = None,
        memory_limit: str | None = None,
        gpu_limit: int | None = None,
        timeout_seconds: int | None = None,
        labels: dict[str, str] | None = None,
        **kwargs,
    ) -> str:
        """
        Start a new computing task.

        Args:
            image: Container image to use
            command: Command to execute
            args: Arguments for the command
            env: Environment variables
            volumes: Volume mounts
            cpu_limit: CPU limit (e.g., "1000m" or "1")
            memory_limit: Memory limit (e.g., "2Gi")
            gpu_limit: Number of GPUs
            timeout_seconds: Task timeout
            labels: Task labels for identification
            **kwargs: Provider-specific options

        Returns:
            Task ID
        """
        provider = await self.get_provider()

        # Caller-supplied kwargs win over env defaults so a specific task
        # can opt out of (or override) the global pool pinning.
        merged_kwargs = {**_kubernetes_scheduling_kwargs(), **kwargs}

        return await provider.start_task(
            image=image,
            command=command,
            args=args,
            env=env,
            volumes=volumes,
            cpu_limit=cpu_limit,
            memory_limit=memory_limit,
            gpu_limit=gpu_limit,
            timeout_seconds=timeout_seconds,
            labels=labels,
            **merged_kwargs,
        )

    async def start_ffmpeg_task(
        self,
        input_file: str,
        output_file: str,
        ffmpeg_args: list[str] | None = None,
        gpu_enabled: bool = False,
        timeout_seconds: int | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Start a one-shot FFmpeg task through the configured compute provider."""
        task_labels = {
            "pyrate.task_type": "transcode",
            "pyrate.tool": "ffmpeg",
            **(labels or {}),
        }

        return await self.start_task(
            image=DEFAULT_FFMPEG_IMAGE,
            command=[
                "ffmpeg",
                "-i",
                input_file,
                *(ffmpeg_args or []),
                output_file,
            ],
            env=_ffmpeg_runtime_user(),
            volumes=build_media_volumes(
                include_writable_temp=True,
                include_cache=True,
                include_downloads=True,
                read_only=False,
            ),
            gpu_limit=1 if gpu_enabled else None,
            timeout_seconds=timeout_seconds,
            labels=task_labels,
        )

    async def start_ffprobe_task(
        self,
        input_file: str,
        timeout_seconds: int | None = None,
        labels: dict[str, str] | None = None,
    ) -> str:
        """Start a one-shot FFprobe task through the configured compute provider."""
        task_labels = {
            "pyrate.task_type": "probe",
            "pyrate.tool": "ffprobe",
            **(labels or {}),
        }

        return await self.start_task(
            image=DEFAULT_FFMPEG_IMAGE,
            command=[
                "ffprobe",
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                input_file,
            ],
            env=_ffmpeg_runtime_user(),
            volumes=build_media_volumes(
                include_writable_temp=False,
                include_cache=False,
                include_downloads=True,
                include_books=True,
                read_only=True,
            ),
            timeout_seconds=timeout_seconds,
            labels=task_labels,
        )

    async def get_task_status(self, task_id: str) -> str:
        """
        Get current status of a task.

        Args:
            task_id: Task identifier

        Returns:
            Status string: "pending", "running", "completed", "failed", "cancelled"
        """
        provider = await self.get_provider()
        return await provider.get_task_status(task_id)

    async def get_task_logs(self, task_id: str, follow: bool = False) -> str:
        """
        Get logs from a task.

        Args:
            task_id: Task identifier
            follow: Stream logs if True

        Returns:
            Task logs as string
        """
        provider = await self.get_provider()
        return await provider.get_task_logs(task_id, follow=follow)

    async def stop_task(self, task_id: str, force: bool = False) -> None:
        """
        Stop a running task.

        Args:
            task_id: Task identifier
            force: Force kill if True
        """
        provider = await self.get_provider()
        await provider.stop_task(task_id, force=force)

    async def delete_task(self, task_id: str) -> None:
        """
        Delete a task and clean up resources.

        Args:
            task_id: Task identifier
        """
        provider = await self.get_provider()
        await provider.delete_task(task_id)

    async def list_tasks(
        self, labels: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """
        List tasks, optionally filtered by labels.

        Args:
            labels: Label filters

        Returns:
            List of tasks with their status
        """
        provider = await self.get_provider()
        return await provider.list_tasks(labels=labels)

    async def get_tasks_by_label(self, key: str, value: str) -> list[dict[str, Any]]:
        """
        Get all tasks with a specific label key-value pair.

        Args:
            key: Label key (e.g., "transcode.session_id")
            value: Label value (e.g., "session-uuid")

        Returns:
            List of task dictionaries matching the label
        """
        labels = {key: value}
        tasks = await self.list_tasks(labels=labels)
        return tasks

    async def terminate_task(self, task_id: str) -> bool:
        """
        Terminate a running task and clean up resources.

        Args:
            task_id: ID of the task to terminate

        Returns:
            True if task was successfully terminated
        """
        try:
            await self.stop_task(task_id, force=True)
            await self.delete_task(task_id)
            return True
        except Exception as e:
            logger.warning("Failed to terminate task %s: %s", task_id, e)
            return False

    async def probe_media_file(
        self,
        file_path: str,
        timeout_seconds: int = 120,
    ) -> dict[str, Any] | None:
        """
        Run ffprobe against ``file_path`` via the configured compute provider.

        This is the single entry point used by movie/show scanners and the
        playback pipeline. Returns the *raw* ffprobe JSON dict (with ``format``
        and ``streams`` keys) or ``None`` on failure. Callers are responsible
        for any further structuring (see
        :func:`pyrate.libraries.base.structure_probe_data`).

        Args:
            file_path: Absolute path inside the sibling container (must live
                under one of the mounts produced by :func:`build_media_volumes`).
            timeout_seconds: Hard wall-clock timeout for the probe task.

        Returns:
            Parsed ffprobe JSON dict or ``None`` if the probe failed/timed out.
        """
        import asyncio
        import json as _json

        from pyrate.services.system_settings import SystemSettingsService

        try:
            settings_service = SystemSettingsService(self.db)
            transcoding_settings = await settings_service.get_transcoding_settings()
            ffmpeg_image = transcoding_settings.get(
                "ffmpeg_image", "lscr.io/linuxserver/ffmpeg:latest"
            )

            command = [
                "-v",
                "error",
                "-print_format",
                "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]

            volumes = build_media_volumes(
                include_writable_temp=False,
                include_cache=False,
                include_downloads=True,
                include_books=True,
                read_only=True,
            )
            env = _ffmpeg_runtime_user()

            task_id = await self.start_task(
                image=ffmpeg_image,
                command=command,
                env=env,
                volumes=volumes,
                cpu_limit="500m",
                memory_limit="512Mi",
                timeout_seconds=timeout_seconds,
                labels={
                    "pyrate.task_type": "probe",
                    "pyrate.tool": "ffprobe",
                },
                entrypoint=["ffprobe"],
            )

            logger.info("Started probe task %s for %s", task_id, file_path)

            wait_interval = 2
            elapsed = 0
            while elapsed < timeout_seconds:
                status = await self.get_task_status(task_id)

                if status == "completed":
                    stdout_output = await self.get_task_logs(task_id)
                    await self.delete_task(task_id)
                    if not stdout_output.strip():
                        logger.error(
                            "ffprobe returned empty output for %s", file_path
                        )
                        return None
                    try:
                        return _json.loads(stdout_output)
                    except _json.JSONDecodeError as e:
                        logger.error(
                            "Failed to parse ffprobe output for %s: %s",
                            file_path,
                            e,
                        )
                        return None

                if status == "failed":
                    error_logs = await self.get_task_logs(task_id)
                    logger.error(
                        "ffprobe task failed for %s: %s", file_path, error_logs
                    )
                    await self.delete_task(task_id)
                    return None

                if status not in ("pending", "running"):
                    logger.warning(
                        "Unknown probe task status %s for %s", status, file_path
                    )
                await asyncio.sleep(wait_interval)
                elapsed += wait_interval

            logger.error("ffprobe task timed out for %s", file_path)
            await self.terminate_task(task_id)
            return None

        except Exception as e:
            logger.error("Error probing %s: %s", file_path, e)
            return None

    async def start_transcoding(
        self,
        input_path: str,
        rel_output: str,
        segment_pattern: str,
        hls_time: int,
        session_id: str,
        video_codec: str,
        audio_codec: str,
        video_bitrate: str | None,
        audio_bitrate: str,
        start_position: float | None,
        resolution: str | None,
        audio_stream_index: int | None,
        subtitle_stream_index: int | None,
        burn_subtitles: bool,
        user_guid: str | None,
        user_name: str | None,
        content_type: str,
        content_id: str | None,
        content_title: str | None,
        library_path: str,
        audio_only: bool = False,
    ) -> str:
        """
        Start an HLS transcoding task.

        Args:
            input_path: Path to input media file
            rel_output: Relative path for output HLS playlist
            segment_pattern: Pattern for HLS segment filenames
            hls_time: Duration of each HLS segment
            session_id: Unique session identifier
            video_codec: Video codec (h264, h265, av1, vp9, copy)
            audio_codec: Audio codec (aac, opus, mp3, copy)
            video_bitrate: Video bitrate (e.g., "4000k")
            audio_bitrate: Audio bitrate (e.g., "128k")
            start_position: Start position in seconds
            resolution: Target resolution (e.g., "1920x1080")
            audio_stream_index: Index of audio stream to use
            subtitle_stream_index: Index of subtitle stream
            burn_subtitles: Whether to burn subtitles into video
            user_guid: User GUID for session tracking
            user_name: User name for session tracking
            content_type: Type of content (movie, episode)
            content_id: ID of content being transcoded
            content_title: Title of content being transcoded
            library_path: Base path for library

        Returns:
            Task ID of the transcoding task
        """
        import os
        import uuid

        from pyrate.schemas.transcoding import TranscodingSessionCreate
        from pyrate.services.system_settings import SystemSettingsService
        from pyrate.services.transcoding_session import get_transcoding_session_service

        logger.info("Starting transcoding for session %s", session_id)

        # Load transcoding settings from database
        settings_service = SystemSettingsService(self.db)
        transcoding_settings = await settings_service.get_transcoding_settings()
        logger.info("Transcoding settings from DB: %s", transcoding_settings)

        # Use ffmpeg_image from settings (admin-configurable)
        ffmpeg_image = transcoding_settings.get(
            "ffmpeg_image", "lscr.io/linuxserver/ffmpeg:latest"
        )

        # Detect hardware acceleration (only if enabled in settings)
        hw_accel_enabled = transcoding_settings.get("hardware_acceleration", False)
        if hw_accel_enabled:
            hw_accel = detect_hardware_acceleration()
            # Override device if configured in settings
            hw_device = transcoding_settings.get("hardware_acceleration_device")
            if hw_device and hw_accel.get("type"):
                hw_accel["devices"] = [hw_device]
        else:
            hw_accel = {"type": None, "devices": [], "encoder_suffix": ""}
        logger.info("Hardware acceleration: %s", hw_accel)

        # Apply thread count from settings
        thread_count = transcoding_settings.get("thread_count", 0)
        # Admin-defined default CRF; ``_build_ffmpeg_command`` falls back to
        # per-codec defaults when this is None.
        default_crf = transcoding_settings.get("default_crf")

        # Override hls_time with setting if not explicitly provided
        effective_hls_time = transcoding_settings.get("hls_segment_duration", hls_time)

        # Build FFmpeg command
        cmd = self._build_ffmpeg_command(
            input_path=input_path,
            rel_output=rel_output,
            segment_pattern=segment_pattern,
            hls_time=effective_hls_time,
            video_codec=video_codec,
            audio_codec=audio_codec,
            video_bitrate=video_bitrate,
            audio_bitrate=audio_bitrate,
            start_position=start_position,
            resolution=resolution,
            audio_stream_index=audio_stream_index,
            subtitle_stream_index=subtitle_stream_index,
            burn_subtitles=burn_subtitles,
            hw_accel=hw_accel,
            thread_count=thread_count,
            audio_only=audio_only,
            default_crf=default_crf,
        )

        # Log the complete FFmpeg command for debugging
        logger.info("=" * 80)
        logger.info("FFMPEG COMMAND:")
        logger.info("ffmpeg %s", ' '.join(cmd))
        logger.info("=" * 80)

        # Start the transcoding task through the provider
        provider = await self.get_provider()

        # Prepare volumes via the shared helper so the backend container,
        # the ffmpeg sibling and any other user of build_media_volumes() all
        # agree on the host-side layout.
        volumes = build_media_volumes(
            include_writable_temp=True,
            include_cache=True,
            include_downloads=True,
            read_only=False,
        )

        # Tighten temp directory perms so only the backend's UID can write
        # there (the ffmpeg sibling runs with the same UID via PUID/PGID).
        temp_dir = "/temp" if os.path.exists("/.dockerenv") else f"{_data_root()}/temp"
        try:
            os.chmod(temp_dir, 0o700)
        except Exception as e:
            logger.warning("Failed to set permissions on %s: %s", temp_dir, e)

        # Run the sibling container as the same UID/GID as the backend so the
        # generated HLS segments and trickplay assets are owned by the
        # backend user, not root. Opt back into root via FFMPEG_RUN_AS_ROOT.
        env = _ffmpeg_runtime_user()

        # Prepare devices for hardware acceleration
        devices = None
        if hw_accel:
            devices = []
            for device_path in hw_accel.get("devices", []):
                devices.append(
                    {
                        "PathOnHost": device_path,
                        "PathInContainer": device_path,
                        "CgroupPermissions": "rwm",
                    }
                )
            logger.info(
                "Hardware acceleration enabled: %s, devices: %s",
                hw_accel['type'], hw_accel.get('devices', []),
            )
        else:
            logger.info("Hardware acceleration not available, using software encoding")

        task_id = await provider.start_task(
            image=ffmpeg_image,
            command=cmd,
            env=env,
            volumes=volumes,
            devices=devices,
            labels={
                "transcode.session_id": session_id,
                "transcode.type": "hls",
                "content_id": str(content_id) if content_id else "",
                "user_guid": str(user_guid) if user_guid else "",
            },
            **_kubernetes_scheduling_kwargs(),
        )

        logger.info("Started transcoding task with ID: %s", task_id)

        # Store session in Redis
        try:
            session_service = get_transcoding_session_service()
            session_data = TranscodingSessionCreate(
                session_id=session_id,
                user_guid=user_guid,
                user_name=user_name,
                content_type=content_type,
                content_id=content_id or uuid.uuid4(),
                content_title=content_title,
                container_id=task_id,  # Store task ID as container_id
                video_codec=video_codec,
                audio_codec=audio_codec,
                video_bitrate=video_bitrate,
                audio_bitrate=audio_bitrate,
                resolution=resolution,
                start_position=start_position,
                input_path=str(input_path),
            )
            await session_service.create_session(session_data)
            logger.info("Created transcoding session in Redis: %s", session_id)
        except Exception as e:
            logger.error("Failed to store transcoding session in Redis: %s", e)
            # Don't fail the transcode if Redis storage fails

        return task_id

    async def start_trickplay_generation(
        self,
        input_path: str,
        session_id: str,
        library_path: str,
    ) -> str:
        """
        Start a trickplay sprite sheet generation container.

        Runs FFmpeg to extract thumbnails every 10 seconds and tile them into
        sprite sheets (10x10 = 100 thumbnails per sheet, WebP format).

        Args:
            input_path: Path to the source video file
            session_id: Session ID to associate sprites with
            library_path: Base path for library volumes

        Returns:
            Task ID of the sprite generation container
        """
        import os

        from pyrate.services.system_settings import SystemSettingsService

        logger.info("Starting trickplay generation for session %s", session_id)

        settings_service = SystemSettingsService(self.db)
        transcoding_settings = await settings_service.get_transcoding_settings()
        ffmpeg_image = transcoding_settings.get(
            "ffmpeg_image", "lscr.io/linuxserver/ffmpeg:latest"
        )

        # Build FFmpeg command for sprite generation
        output_dir = f"/temp/{session_id}_trickplay"
        cmd = [
            "-i", input_path,
            "-vf", "fps=1/10,scale=320:-1,tile=10x10",
            "-c:v", "libwebp",
            "-quality", "75",
            "-an",
            f"{output_dir}/sprite_%03d.webp",
        ]

        logger.info("Trickplay FFmpeg command: ffmpeg %s", " ".join(cmd))

        provider = await self.get_provider()

        # Same volume setup as transcoding (cache not needed for sprites).
        volumes = build_media_volumes(
            include_writable_temp=True,
            include_cache=False,
            include_downloads=True,
            read_only=False,
        )

        # Ensure trickplay output directory exists
        in_docker = os.path.exists("/.dockerenv")
        if in_docker:
            host_trickplay_dir = f"/temp/{session_id}_trickplay"
        else:
            host_trickplay_dir = f"{_data_root()}/temp/{session_id}_trickplay"
        try:
            os.makedirs(host_trickplay_dir, exist_ok=True)
            os.chmod(host_trickplay_dir, 0o700)
        except Exception as e:
            logger.warning("Failed to create trickplay dir %s: %s", host_trickplay_dir, e)

        env = _ffmpeg_runtime_user()

        task_id = await provider.start_task(
            image=ffmpeg_image,
            command=cmd,
            env=env,
            volumes=volumes,
            devices=None,
            labels={
                "trickplay.session_id": session_id,
                "trickplay.type": "sprite",
            },
            **_kubernetes_scheduling_kwargs(),
        )

        logger.info("Started trickplay generation task: %s for session %s", task_id, session_id)
        return task_id

    @staticmethod
    def _parse_bitrate(bitrate: str) -> int:
        """Parse a bitrate string like '128k' or '2000k' to integer kbps. Returns 0 on failure."""
        if not bitrate:
            return 0
        cleaned = bitrate.lower().rstrip("k")
        try:
            return int(cleaned)
        except ValueError:
            logger.warning("Invalid bitrate format: %s", bitrate)
            return 0

    @staticmethod
    def _parse_resolution(resolution: str) -> tuple[int, int] | None:
        """Parse a resolution string like '1920x1080'. Returns (width, height) or None."""
        if not resolution or "x" not in resolution:
            return None
        try:
            width, height = resolution.split("x", 1)
            w, h = int(width), int(height)
            if w < 128 or h < 128 or w > 7680 or h > 4320:
                logger.warning("Resolution out of bounds: %sx%s", w, h)
                return None
            return w, h
        except ValueError:
            logger.warning("Invalid resolution format: %s", resolution)
            return None

    @staticmethod
    def _escape_ffmpeg_path(path: str) -> str:
        """Escape a file path for use in FFmpeg filter expressions."""
        # FFmpeg filter syntax requires escaping \ : ' [ ]
        return path.replace("\\", "\\\\").replace("'", "'\\''").replace(":", "\\:")

    def _build_ffmpeg_command(
        self,
        input_path: str,
        rel_output: str,
        segment_pattern: str,
        hls_time: int,
        video_codec: str,
        audio_codec: str,
        video_bitrate: str | None,
        audio_bitrate: str,
        start_position: float | None,
        resolution: str | None,
        audio_stream_index: int | None,
        subtitle_stream_index: int | None,
        burn_subtitles: bool,
        hw_accel: dict[str, Any] | None = None,
        thread_count: int = 0,
        audio_only: bool = False,
        default_crf: int | None = None,
    ) -> list[str]:
        """Build FFmpeg command for transcoding."""
        # Validate parameters
        if audio_stream_index is not None and audio_stream_index < 0:
            logger.warning("Invalid audio_stream_index %s, using default", audio_stream_index)
            audio_stream_index = None
        if subtitle_stream_index is not None and subtitle_stream_index < 0:
            logger.warning("Invalid subtitle_stream_index %s, ignoring", subtitle_stream_index)
            subtitle_stream_index = None
            burn_subtitles = False
        hls_time = max(2, min(60, hls_time))

        cmd = []

        # Thread count (0 = auto/let FFmpeg decide)
        if thread_count > 0:
            cmd.extend(["-threads", str(thread_count)])

        # Hardware acceleration type — defined unconditionally so later
        # branches (vp9/av1/copy) that reference ``hw_type`` don't NameError
        # when hw_accel is None or has no "type" entry.
        hw_type = hw_accel.get("type") if hw_accel else None

        # Add hardware acceleration if available (only for video)
        if not audio_only and hw_accel and hw_type:
            if hw_type == "qsv":
                # Intel QuickSync - use only QSV for ENCODING, not decoding
                # QSV hardware decoding has issues with 10-bit HDR content (Main 10, bt2020)
                # causing "Error synchronizing the operation" errors
                # Software decoding is more reliable for all content types
                cmd.extend(
                    ["-init_hw_device", "qsv=qsv:hw", "-filter_hw_device", "qsv"]
                )
                # NO hardware decoding - use software decoder for reliability
                # The hwupload filter will transfer frames to QSV for hardware encoding
                logger.info(
                    "Using Intel QuickSync Video (QSV) for encoding only (software decode for HDR compatibility)"
                )
            elif hw_type == "vaapi":
                # VA-API for Intel
                cmd.extend(
                    ["-hwaccel", "vaapi", "-hwaccel_device", "/dev/dri/renderD128"]
                )
                logger.info("Using VA-API hardware acceleration")

        # Add start position (seek) if specified - must be before -i for fast seeking
        if start_position is not None and start_position > 0:
            cmd.extend(["-ss", str(start_position)])

        # Input file
        cmd.extend(["-i", str(input_path)])

        # Audio-only: skip video stream mapping and encoding entirely
        if audio_only:
            if audio_stream_index is not None:
                cmd.extend(["-map", f"0:a:{audio_stream_index}"])
            else:
                cmd.extend(["-map", "0:a:0"])
            # No video output
            cmd.extend(["-vn"])
        else:
            # Stream mapping - select specific audio stream if specified
            cmd.extend(["-map", "0:v:0"])  # First video stream

            if audio_stream_index is not None:
                # Map specific audio stream by index within audio streams
                cmd.extend(["-map", f"0:a:{audio_stream_index}"])
            else:
                # Map first audio stream by default
                cmd.extend(["-map", "0:a:0"])

        # Subtitle burning requires video re-encoding — override copy if needed
        if burn_subtitles and subtitle_stream_index is not None and video_codec == "copy":
            video_codec = "h264"
            logger.info(
                "Switching video codec from copy to h264 because subtitle burning requires re-encoding"
            )

        # Video codec settings (skip for audio-only)
        if audio_only:
            pass  # No video codec needed
        elif video_codec == "copy":
            cmd.extend(["-c:v", "copy"])
            # For HEVC/H.265, we need to tag the stream as hvc1 for HLS compatibility
            # This is required for most browsers to play HEVC in HLS
            cmd.extend(["-tag:v", "hvc1"])
        elif video_codec == "h265" or video_codec == "hevc":
            # Use hardware encoder if available
            if hw_accel and hw_accel.get("encoder_suffix"):
                encoder = f"hevc{hw_accel['encoder_suffix']}"  # hevc_qsv
                cmd.extend(["-c:v", encoder])
                if hw_type == "qsv":
                    cmd.extend(["-preset", "medium", "-global_quality", "25"])
                logger.info("Using hardware H.265 encoder: %s", encoder)
            else:
                cmd.extend(["-c:v", "libx265", "-preset", "fast"])

            # Tag HEVC as hvc1 for HLS compatibility (required for browsers)
            cmd.extend(["-tag:v", "hvc1"])

            if video_bitrate and not (hw_accel and hw_accel.get("encoder_suffix")):
                cmd.extend(["-b:v", video_bitrate])
            elif not hw_accel:
                # H.265 needs lower CRF to match H.264 quality (see ffmpeg docs).
                cmd.extend(["-crf", str(default_crf if default_crf is not None else 28)])
        elif video_codec == "vp9":
            cmd.extend(
                ["-c:v", "libvpx-vp9", "-deadline", "realtime", "-cpu-used", "4"]
            )
            if video_bitrate:
                cmd.extend(["-b:v", video_bitrate])
            else:
                cmd.extend(["-crf", str(default_crf if default_crf is not None else 31), "-b:v", "0"])
        elif video_codec == "av1":
            # Use hardware encoder if available
            if hw_accel and hw_accel.get("encoder_suffix"):
                encoder = f"av1{hw_accel['encoder_suffix']}"  # av1_qsv
                cmd.extend(["-c:v", encoder])
                if hw_type == "qsv":
                    cmd.extend(["-preset", "medium", "-global_quality", "25"])
                logger.info("Using hardware AV1 encoder: %s", encoder)
            else:
                cmd.extend(
                    [
                        "-c:v",
                        "libsvtav1",
                        "-preset",
                        "8",
                        "-svtav1-params",
                        "fast-decode=1",
                    ]
                )
            if video_bitrate and not (hw_accel and hw_accel.get("encoder_suffix")):
                cmd.extend(["-b:v", video_bitrate])
            elif not hw_accel:
                cmd.extend(["-crf", str(default_crf if default_crf is not None else 30)])
        else:  # Default to h264
            # Use hardware encoder if available
            if hw_accel and hw_accel.get("encoder_suffix"):
                encoder = f"h264{hw_accel['encoder_suffix']}"  # h264_qsv
                cmd.extend(["-c:v", encoder])
                if hw_type == "qsv":
                    cmd.extend(["-preset", "medium", "-global_quality", "23"])
                logger.info("Using hardware H.264 encoder: %s", encoder)
            else:
                cmd.extend(["-c:v", "libx264", "-preset", "fast"])

            if video_bitrate and not (hw_accel and hw_accel.get("encoder_suffix")):
                cmd.extend(
                    [
                        "-b:v",
                        video_bitrate,
                        "-maxrate",
                        video_bitrate,
                        "-bufsize",
                        f"{self._parse_bitrate(video_bitrate) * 2}k",
                    ]
                )
            elif not hw_accel:
                cmd.extend(["-crf", str(default_crf if default_crf is not None else 23)])

        # Build video filter chain (skip for audio-only)
        vf_filters = []

        if audio_only:
            pass  # No video filters needed
        elif hw_accel and hw_accel.get("type") == "qsv" and video_codec != "copy":
            # Handle scaling if resolution is specified (software scaling before upload)
            if resolution:
                parsed = self._parse_resolution(resolution)
                if parsed:
                    w, h = parsed
                    vf_filters.append(
                        f"scale={w}:{h}:force_original_aspect_ratio=decrease"
                    )
                    vf_filters.append(f"pad={w}:{h}:(ow-iw)/2:(oh-ih)/2")
                    resolution = None  # Don't add another scale filter
                    logger.info("Added scaling to %sx%s", w, h)

            # Convert pixel format to nv12 (required for QSV encoder)
            # This handles 10-bit HDR content (yuv420p10le -> nv12) with proper tone mapping
            vf_filters.append("format=nv12")
            logger.info("Added format=nv12 filter for QSV compatibility")

            # Upload to QSV for hardware encoding
            vf_filters.append("hwupload=extra_hw_frames=64")
            logger.info("Added hwupload filter for QSV encoding")

        # Resolution scaling if specified (for non-QSV or if QSV scaling wasn't added)
        if resolution:
            parsed = self._parse_resolution(resolution)
            if parsed:
                w, h = parsed
                vf_filters.append(
                    f"scale={w}:{h}:force_original_aspect_ratio=decrease,pad={w}:{h}:(ow-iw)/2:(oh-ih)/2"
                )

        # Burn subtitles if specified
        if burn_subtitles and subtitle_stream_index is not None:
            # For QSV with subtitles, we need to insert the subtitle filter before hwupload
            if hw_accel and hw_accel.get("type") == "qsv":
                # Find and remove hwupload if present, we'll add it back after subtitles
                has_hwupload = any("hwupload" in f for f in vf_filters)
                if has_hwupload:
                    vf_filters = [f for f in vf_filters if "hwupload" not in f]

                # Add subtitle filter (works on CPU after hwdownload + format=nv12)
                vf_filters.append(
                    f"subtitles='{self._escape_ffmpeg_path(input_path)}':si={subtitle_stream_index}"
                )

                # Re-add hwupload at the end
                if has_hwupload:
                    vf_filters.append("hwupload=extra_hw_frames=64")

                logger.info("Burning subtitle stream %s with QSV", subtitle_stream_index)
            else:
                # Use the subtitles filter for text-based subtitles or overlay for bitmap
                # We use the si (stream index) option to select the correct subtitle stream
                vf_filters.append(
                    f"subtitles='{self._escape_ffmpeg_path(input_path)}':si={subtitle_stream_index}"
                )
                logger.info("Burning subtitle stream %s into video", subtitle_stream_index)

        # Apply video filters if any
        if vf_filters:
            cmd.extend(["-vf", ",".join(vf_filters)])

        # Audio codec settings
        if audio_codec == "copy":
            cmd.extend(["-c:a", "copy"])
        elif audio_codec == "opus":
            cmd.extend(["-c:a", "libopus", "-b:a", audio_bitrate])
        elif audio_codec == "mp3":
            cmd.extend(["-c:a", "libmp3lame", "-b:a", audio_bitrate])
        else:  # Default to aac
            cmd.extend(["-c:a", "aac", "-b:a", audio_bitrate])

        # Always set to stereo for compatibility
        cmd.extend(["-ac", "2"])

        # HLS output settings
        cmd.extend(
            [
                "-f",
                "hls",
                "-hls_time",
                str(hls_time),
                "-hls_playlist_type",
                "event",
                "-hls_flags",
                "independent_segments+append_list",
                "-hls_segment_filename",
                segment_pattern,
                rel_output,
            ]
        )

        return cmd
