"""Docker computing provider plugin."""

import asyncio
import logging
import uuid
from typing import Any

import aiodocker

from pyrate.computing.base import ComputingBase, TaskResult, TaskStatus
from pyrate.utils.host_path import sanitize_bind_host_path as _sanitize_bind_host_path

logger = logging.getLogger(__name__)

# Upper bound so a bogus gpu_limit can't request absurd numbers before
# Docker itself rejects the request.
_MAX_GPU_LIMIT = 16


class DockerComputingProvider(ComputingBase):
    """
    Docker computing provider for running compute tasks in Docker containers.

    Uses aiodocker library for async container management.
    """

    def __init__(self, manifest=None, config=None):
        self.config = config or {}
        self.manifest = manifest
        self.client: aiodocker.Docker | None = None
        self._containers: dict[str, str] = {}  # task_id -> container_id
        self._timeout_tasks: dict[str, asyncio.Task] = {}

    async def setup(self):
        """Initialize Docker client."""
        try:
            self.client = aiodocker.Docker()
            # Test connection
            await self.client.version()
            logger.info("Docker computing provider initialized")
        except Exception as e:
            logger.error("Failed to initialize Docker client: %s", e)
            raise

    async def close(self):
        """Close Docker client.

        Timeout handlers are bound to the provider lifecycle: on close we
        cancel every pending timeout task and force-stop the containers they
        were guarding, otherwise a container outliving the provider would
        never be reaped once its timer can no longer fire. ``self._containers``
        is instance-local, so this only reaps tasks started by this provider.
        """
        for task in list(self._timeout_tasks.values()):
            task.cancel()
        self._timeout_tasks.clear()

        if self.client:
            for task_id in list(self._containers):
                try:
                    await self.stop_task(task_id, force=True)
                except Exception as exc:
                    logger.warning(
                        "Failed to stop container for task %s during close: %s",
                        task_id,
                        exc,
                    )
            await self.client.close()
            logger.info("Docker computing provider closed")

    def get_name(self) -> str:
        """Get plugin name."""
        return self.manifest.name

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for Docker provider."""
        return {
            "docker_host": {
                "type": "string",
                "label": "Docker Host",
                "hint": "Docker daemon socket or URL (e.g., unix:///var/run/docker.sock or tcp://127.0.0.1:2375)",
                "required": False,
                "default": "unix:///var/run/docker.sock",
                "placeholder": "unix:///var/run/docker.sock",
            }
        }

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
        devices: list[dict[str, str]] | None = None,
        **kwargs,
    ) -> str:
        """
        Start a new Docker container for the task.

        Args:
            image: Docker image to use
            command: Command to execute
            args: Arguments for the command
            env: Environment variables
            volumes: Volume mounts {host_path: container_path}
            cpu_limit: CPU limit (e.g., "1000m" = 1 CPU)
            memory_limit: Memory limit (e.g., "2Gi")
            gpu_limit: Number of GPUs
            timeout_seconds: Task timeout
            labels: Container labels
            devices: Device mounts (e.g., for hardware acceleration)
            **kwargs: Additional Docker-specific options

        Returns:
            Task ID (UUID)
        """
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        task_id = str(uuid.uuid4())

        # Build container configuration
        config: dict[str, Any] = {
            "Image": image,
            "Labels": labels or {},
        }

        # Add task_id to labels
        config["Labels"]["pyrate.task_id"] = task_id

        # Entrypoint override (e.g. image ships with ffmpeg entrypoint but we
        # need ffprobe). Accept list via kwargs; falls back to image default.
        entrypoint = kwargs.get("entrypoint")
        if entrypoint:
            config["Entrypoint"] = list(entrypoint)

        # Build command
        if command or args:
            cmd = []
            if command:
                cmd.extend(command)
            if args:
                cmd.extend(args)
            config["Cmd"] = cmd

        # Environment variables
        if env:
            config["Env"] = [f"{k}={v}" for k, v in env.items()]

        # Host configuration (resources and volumes)
        host_config: dict[str, Any] = {}

        # CPU limit: "1000m" = 1 CPU = 1000000000 nanoseconds per 100ms period
        if cpu_limit:
            if cpu_limit.endswith("m"):
                # Millicores (e.g., "1000m" = 1 CPU)
                millicores = int(cpu_limit[:-1])
                # Docker uses NanoCPUs (1 CPU = 1e9)
                host_config["NanoCpus"] = int(millicores * 1_000_000)
            else:
                # Assume whole CPUs
                host_config["NanoCpus"] = int(float(cpu_limit) * 1_000_000_000)

        # Memory limit
        if memory_limit:
            memory_bytes = self._parse_memory(memory_limit)
            host_config["Memory"] = memory_bytes

        # Volume mounts — every host path is resolved + validated so a caller
        # that ever lets user input into `volumes` can't escape via `..` or
        # relative-path tricks.
        if volumes:
            binds = []
            for host, container in volumes.items():
                safe_host = _sanitize_bind_host_path(host)
                if safe_host != host:
                    logger.info(
                        "Normalising volume host path %r → %r", host, safe_host
                    )
                binds.append(f"{safe_host}:{container}:rw")
            host_config["Binds"] = binds

        # Device mounts (for hardware acceleration)
        if devices:
            host_config["Devices"] = devices

        # GPU support (requires nvidia-docker). Clamp to a sane upper bound so
        # a bogus value surfaces as a local error rather than a late docker
        # daemon rejection.
        if gpu_limit and gpu_limit > 0:
            if gpu_limit > _MAX_GPU_LIMIT:
                logger.warning(
                    "gpu_limit=%d exceeds cap %d, clamping", gpu_limit, _MAX_GPU_LIMIT
                )
                gpu_limit = _MAX_GPU_LIMIT
            host_config["DeviceRequests"] = [
                {
                    "Driver": "nvidia",
                    "Count": gpu_limit,
                    "Capabilities": [["gpu"]],
                }
            ]

        config["HostConfig"] = host_config

        # Pull image if not present
        try:
            await self.client.images.inspect(image)
        except aiodocker.exceptions.DockerError:
            logger.info("Pulling Docker image: %s", image)
            await self.client.images.pull(image)

        # Create and start container
        try:
            container = await self.client.containers.create(config=config)
            await container.start()

            container_id = container.id
            self._containers[task_id] = container_id

            logger.info(
                "Started Docker task %s (container %s)", task_id, container_id[:12]
            )

            # Handle timeout if specified — keep a strong reference so the
            # event loop doesn't GC the timer mid-flight and leak a runaway
            # container past its deadline.
            if timeout_seconds:
                t = asyncio.create_task(
                    self._timeout_handler(task_id, timeout_seconds),
                    name=f"docker-timeout-{task_id}",
                )
                self._timeout_tasks[task_id] = t
                t.add_done_callback(
                    lambda _t, tid=task_id: self._timeout_tasks.pop(tid, None)
                )

            return task_id

        except Exception as e:
            logger.error("Failed to start Docker task: %s", e)
            raise

    async def _timeout_handler(self, task_id: str, timeout_seconds: int):
        """Handle task timeout."""
        await asyncio.sleep(timeout_seconds)

        # Check if task is still running
        status = await self.get_task_status(task_id)
        if status == "running":
            logger.warning(
                "Task %s timed out after %ss, stopping...", task_id, timeout_seconds
            )
            await self.stop_task(task_id, force=True)

    def _parse_memory(self, memory_limit: str) -> int:
        """Parse memory limit string to bytes."""
        memory_limit = memory_limit.strip()

        # Parse unit
        if memory_limit.endswith("Ki"):
            return int(memory_limit[:-2]) * 1024
        elif memory_limit.endswith("Mi"):
            return int(memory_limit[:-2]) * 1024 * 1024
        elif memory_limit.endswith("Gi"):
            return int(memory_limit[:-2]) * 1024 * 1024 * 1024
        elif memory_limit.endswith("K"):
            return int(memory_limit[:-1]) * 1000
        elif memory_limit.endswith("M"):
            return int(memory_limit[:-1]) * 1000 * 1000
        elif memory_limit.endswith("G"):
            return int(memory_limit[:-1]) * 1000 * 1000 * 1000
        else:
            # Assume bytes
            return int(memory_limit)

    async def get_task_status(self, task_id: str) -> str:
        """
        Get current status of a task.

        Returns: "pending", "running", "completed", "failed", "cancelled"
        """
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        container_id = self._containers.get(task_id)
        if not container_id:
            return "failed"

        try:
            container = await self.client.containers.get(container_id)
            info = await container.show()

            state = info["State"]

            if state["Running"]:
                return "running"
            elif state["Status"] == "created":
                return "pending"
            elif state["ExitCode"] == 0:
                return "completed"
            else:
                return "failed"

        except aiodocker.exceptions.DockerError:
            return "failed"

    async def get_task_logs(self, task_id: str, follow: bool = False) -> str:
        """Get logs from a task."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        container_id = self._containers.get(task_id)
        if not container_id:
            raise ValueError(f"Task {task_id} not found")

        try:
            container = await self.client.containers.get(container_id)

            if follow:
                # Stream logs
                logs = []
                async for line in container.log(stdout=True, stderr=True, follow=True):
                    logs.append(line)
                return "".join(logs)
            else:
                # Get all logs
                logs = await container.log(stdout=True, stderr=True)
                return "".join(logs)

        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to get logs for task %s: %s", task_id, e)
            raise

    async def stop_task(self, task_id: str, force: bool = False) -> None:
        """Stop a running task."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        container_id = self._containers.get(task_id)
        if not container_id:
            logger.warning("Task %s not found, cannot stop", task_id)
            return

        try:
            container = await self.client.containers.get(container_id)

            if force:
                await container.kill()
                logger.info("Killed Docker task %s", task_id)
            else:
                await container.stop()
                logger.info("Stopped Docker task %s", task_id)

        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to stop task %s: %s", task_id, e)
            raise

    async def delete_task(self, task_id: str) -> None:
        """Delete a task and clean up resources."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        container_id = self._containers.get(task_id)
        if not container_id:
            logger.warning("Task %s not found, cannot delete", task_id)
            return

        try:
            container = await self.client.containers.get(container_id)

            # Stop if running
            info = await container.show()
            if info["State"]["Running"]:
                await container.stop()

            # Remove container
            await container.delete()

            # Remove from tracking
            del self._containers[task_id]

            # Cancel any pending timeout handler — container is gone, no
            # point waking up only to discover that.
            timeout_task = self._timeout_tasks.pop(task_id, None)
            if timeout_task is not None:
                timeout_task.cancel()

            logger.info("Deleted Docker task %s", task_id)

        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to delete task %s: %s", task_id, e)
            raise

    async def list_tasks(
        self, labels: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """
        List tasks, optionally filtered by labels.

        Returns:
            List of task dictionaries with task_id, status, container_id
        """
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        # Build label filter
        filters = {"label": ["pyrate.task_id"]}
        if labels:
            for key, value in labels.items():
                filters["label"].append(f"{key}={value}")

        try:
            containers = await self.client.containers.list(all=True, filters=filters)

            tasks = []
            for container in containers:
                info = await container.show()
                container_labels = info.get("Config", {}).get("Labels", {})
                task_id = container_labels.get("pyrate.task_id")

                if task_id:
                    state = info["State"]
                    if state["Running"]:
                        status = "running"
                    elif state["Status"] == "created":
                        status = "pending"
                    elif state["ExitCode"] == 0:
                        status = "completed"
                    else:
                        status = "failed"

                    tasks.append(
                        {
                            "task_id": task_id,
                            "container_id": container.id,
                            "status": status,
                            "exit_code": state.get("ExitCode"),
                            "labels": container_labels,
                        }
                    )

            return tasks

        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to list tasks: %s", e)
            raise

    async def get_task_result(self, task_id: str) -> TaskResult:
        """Get the complete result of a Docker task."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        container_id = self._containers.get(task_id)
        if not container_id:
            raise ValueError(f"Task {task_id} not found")

        try:
            container = self.client.containers.container(container_id)
            info = await container.show()
            state = info["State"]

            if state["Running"]:
                status = TaskStatus.RUNNING
            elif state["Status"] == "created":
                status = TaskStatus.PENDING
            elif state["ExitCode"] == 0:
                status = TaskStatus.COMPLETED
            else:
                status = TaskStatus.FAILED

            logs = await container.log(stdout=True, stderr=True)
            stdout = "\n".join(logs) if logs else None

            return TaskResult(
                task_id=task_id,
                status=status,
                exit_code=state.get("ExitCode"),
                stdout=stdout,
                error=state.get("Error") or None,
            )
        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to get result for task %s: %s", task_id, e)
            raise

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up completed Docker containers older than max_age_hours."""
        if not self.client:
            raise RuntimeError("Docker client not initialized")

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cleaned = 0

        try:
            containers = await self.client.containers.list(
                all=True, filters={"label": ["pyrate.task_id"]}
            )
            for container in containers:
                info = await container.show()
                state = info["State"]
                if not state["Running"] and state.get("FinishedAt"):
                    finished_str = state["FinishedAt"]
                    # Docker returns ISO format with possible nanosecond precision
                    finished_str = finished_str.split(".")[0] + "+00:00"
                    finished = datetime.fromisoformat(finished_str)
                    if finished < cutoff:
                        task_id = info.get("Config", {}).get("Labels", {}).get(
                            "pyrate.task_id"
                        )
                        await container.delete(force=True)
                        if task_id and task_id in self._containers:
                            del self._containers[task_id]
                        cleaned += 1
        except aiodocker.exceptions.DockerError as e:
            logger.error("Failed to cleanup tasks: %s", e)
            raise

        logger.info("Cleaned up %s completed Docker tasks", cleaned)
        return cleaned


async def async_setup_entry(manifest, config):
    """Setup plugin entry point."""
    plugin = DockerComputingProvider(manifest, config)
    await plugin.setup()
    return plugin
