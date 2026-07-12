"""Kubernetes computing provider plugin."""

import logging
import uuid
from typing import Any

from kubernetes_asyncio import client, config
from kubernetes_asyncio.client import ApiException

from pyrate.computing.base import ComputingBase, TaskResult, TaskStatus
from pyrate.utils.host_path import sanitize_bind_host_path as _sanitize_host_path

logger = logging.getLogger(__name__)


class KubernetesComputingProvider(ComputingBase):
    """
    Kubernetes computing provider for running compute tasks as Kubernetes Jobs.

    Uses kubernetes_asyncio library for async API operations.
    Creates Jobs with single-pod templates for each task.
    """

    def __init__(self, manifest=None, plugin_config=None):
        self.config = plugin_config or {}
        self.manifest = manifest
        self.api_client: client.ApiClient | None = None
        self.batch_v1: client.BatchV1Api | None = None
        self.core_v1: client.CoreV1Api | None = None
        self.namespace: str = plugin_config.get("namespace", "default")
        self.job_ttl: int = plugin_config.get("job_ttl_seconds", 3600)  # 1 hour default

    async def setup(self):
        """Initialize Kubernetes client."""
        try:
            # Try in-cluster config first
            try:
                config.load_incluster_config()
                logger.info("Loaded in-cluster Kubernetes configuration")
            except config.ConfigException:
                # Fall back to kubeconfig
                await config.load_kube_config()
                logger.info("Loaded Kubernetes configuration from kubeconfig")

            self.api_client = client.ApiClient()
            self.batch_v1 = client.BatchV1Api(self.api_client)
            self.core_v1 = client.CoreV1Api(self.api_client)

            # Test connection
            await self.batch_v1.get_api_resources()
            logger.info("Kubernetes computing provider initialized (namespace: %s)", self.namespace)

        except Exception as e:
            logger.error("Failed to initialize Kubernetes client: %s", e)
            raise

    async def close(self):
        """Close Kubernetes client."""
        if self.api_client:
            await self.api_client.close()
            logger.info("Kubernetes computing provider closed")

    def get_name(self) -> str:
        """Get plugin name."""
        return self.manifest.name

    def get_config_schema(self) -> dict[str, Any]:
        """Get configuration schema for Kubernetes provider."""
        return {
            "namespace": {
                "type": "string",
                "label": "Namespace",
                "hint": "Kubernetes namespace for jobs (default: default)",
                "required": False,
                "default": "default",
                "placeholder": "default",
            },
            "job_ttl_seconds": {
                "type": "number",
                "label": "Job TTL (seconds)",
                "hint": "Time to keep completed/failed jobs (default: 3600)",
                "required": False,
                "default": 3600,
                "placeholder": "3600",
                "min": 0,
            },
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
        Start a new Kubernetes Job for the task.

        Args:
            image: Container image to use
            command: Command to execute (overrides ENTRYPOINT)
            args: Arguments for the command
            env: Environment variables
            volumes: Volume mounts {pvc_name: mount_path} or {host_path: mount_path}
            cpu_limit: CPU limit (e.g., "1000m" or "1")
            memory_limit: Memory limit (e.g., "2Gi")
            gpu_limit: Number of GPUs (requires node with GPU)
            timeout_seconds: Job timeout (activeDeadlineSeconds)
            labels: Job labels
            devices: Device mounts (not directly supported in Kubernetes, requires hostPath volumes)
            **kwargs: Additional Kubernetes-specific options (e.g., node_selector, tolerations)

        Returns:
            Task ID (UUID)
        """
        if not self.batch_v1:
            raise RuntimeError("Kubernetes client not initialized")

        task_id = str(uuid.uuid4())
        job_name = f"pyrate-task-{task_id[:8]}"

        # Build labels
        job_labels = {
            "app": "pyrate",
            "component": "computing",
            "pyrate.task_id": task_id,
        }
        if labels:
            job_labels.update(labels)

        # Build environment variables
        env_vars = []
        if env:
            for key, value in env.items():
                env_vars.append(client.V1EnvVar(name=key, value=value))

        # Build resource requirements
        resources = client.V1ResourceRequirements()

        if cpu_limit or memory_limit or gpu_limit:
            limits = {}
            requests = {}

            if cpu_limit:
                limits["cpu"] = cpu_limit
                requests["cpu"] = cpu_limit

            if memory_limit:
                limits["memory"] = memory_limit
                requests["memory"] = memory_limit

            if gpu_limit and gpu_limit > 0:
                limits["nvidia.com/gpu"] = str(gpu_limit)
                requests["nvidia.com/gpu"] = str(gpu_limit)

            resources.limits = limits
            resources.requests = requests

        # Build volume mounts
        volume_mounts = []
        pod_volumes = []

        if volumes:
            for idx, (source, mount_path) in enumerate(volumes.items()):
                volume_name = f"vol-{idx}"

                # Check if source is a PVC or host path
                if source.startswith("/"):
                    # Host path volume — canonicalise + reject traversal so a
                    # caller that ever lets user input into ``volumes`` can't
                    # mount arbitrary host dirs.
                    safe_source = _sanitize_host_path(source)
                    pod_volumes.append(
                        client.V1Volume(
                            name=volume_name,
                            host_path=client.V1HostPathVolumeSource(
                                path=safe_source, type="Directory"
                            ),
                        )
                    )
                else:
                    # PVC volume
                    pod_volumes.append(
                        client.V1Volume(
                            name=volume_name,
                            persistent_volume_claim=client.V1PersistentVolumeClaimVolumeSource(
                                claim_name=source
                            ),
                        )
                    )

                volume_mounts.append(
                    client.V1VolumeMount(name=volume_name, mount_path=mount_path)
                )

        # Build container spec
        container = client.V1Container(
            name="task",
            image=image,
            command=command,
            args=args,
            env=env_vars,
            resources=resources,
            volume_mounts=volume_mounts if volume_mounts else None,
        )

        # Build pod spec
        pod_spec = client.V1PodSpec(
            containers=[container],
            restart_policy="Never",
            volumes=pod_volumes if pod_volumes else None,
        )

        # Add node selector if specified
        if "node_selector" in kwargs:
            pod_spec.node_selector = kwargs["node_selector"]

        # Add tolerations if specified
        if "tolerations" in kwargs:
            pod_spec.tolerations = kwargs["tolerations"]

        # Build pod template
        pod_template = client.V1PodTemplateSpec(
            metadata=client.V1ObjectMeta(labels=job_labels),
            spec=pod_spec,
        )

        # Build job spec
        job_spec = client.V1JobSpec(
            template=pod_template,
            backoff_limit=0,  # Don't retry failed jobs
            ttl_seconds_after_finished=self.job_ttl,  # Auto-cleanup
        )

        # Add timeout if specified
        if timeout_seconds:
            job_spec.active_deadline_seconds = timeout_seconds

        # Build job
        job = client.V1Job(
            api_version="batch/v1",
            kind="Job",
            metadata=client.V1ObjectMeta(name=job_name, labels=job_labels),
            spec=job_spec,
        )

        # Create job
        try:
            await self.batch_v1.create_namespaced_job(
                namespace=self.namespace, body=job
            )
            logger.info("Started Kubernetes task %s (job %s)", task_id, job_name)
            return task_id

        except ApiException as e:
            logger.error("Failed to start Kubernetes task: %s", e)
            raise

    async def get_task_status(self, task_id: str) -> str:
        """
        Get current status of a task.

        Returns: "pending", "running", "completed", "failed", "cancelled"
        """
        if not self.batch_v1:
            raise RuntimeError("Kubernetes client not initialized")

        job_name = f"pyrate-task-{task_id[:8]}"

        try:
            job = await self.batch_v1.read_namespaced_job(
                name=job_name, namespace=self.namespace
            )

            status = job.status

            # Check conditions
            if status.failed and status.failed > 0:
                return "failed"

            if status.succeeded and status.succeeded > 0:
                return "completed"

            if status.active and status.active > 0:
                return "running"

            # Job exists but no pods started yet
            return "pending"

        except ApiException as e:
            if e.status == 404:
                return "failed"
            logger.error("Failed to get status for task %s: %s", task_id, e)
            raise

    async def get_task_logs(self, task_id: str, follow: bool = False) -> str:
        """Get logs from a task's pod."""
        if not self.core_v1:
            raise RuntimeError("Kubernetes client not initialized")

        # Find pod for this task
        label_selector = f"pyrate.task_id={task_id}"

        try:
            pods = await self.core_v1.list_namespaced_pod(
                namespace=self.namespace,
                label_selector=label_selector,
            )

            if not pods.items:
                raise ValueError(f"No pod found for task {task_id}")

            pod_name = pods.items[0].metadata.name

            # Get logs
            logs = await self.core_v1.read_namespaced_pod_log(
                name=pod_name,
                namespace=self.namespace,
                follow=follow,
            )

            return logs

        except ApiException as e:
            logger.error("Failed to get logs for task %s: %s", task_id, e)
            raise

    async def stop_task(self, task_id: str, force: bool = False) -> None:
        """Stop a running task by deleting the job."""
        if not self.batch_v1:
            raise RuntimeError("Kubernetes client not initialized")

        job_name = f"pyrate-task-{task_id[:8]}"

        try:
            # Delete job (this will stop all pods)
            delete_options = client.V1DeleteOptions(
                propagation_policy="Background" if not force else "Foreground"
            )

            await self.batch_v1.delete_namespaced_job(
                name=job_name,
                namespace=self.namespace,
                body=delete_options,
            )

            logger.info("Stopped Kubernetes task %s", task_id)

        except ApiException as e:
            if e.status != 404:
                logger.error("Failed to stop task %s: %s", task_id, e)
                raise

    async def delete_task(self, task_id: str) -> None:
        """Delete a task and clean up resources."""
        # Stop task will also delete it
        await self.stop_task(task_id, force=True)

    async def list_tasks(
        self, labels: dict[str, str] | None = None
    ) -> list[dict[str, Any]]:
        """
        List tasks, optionally filtered by labels.

        Returns:
            List of task dictionaries with task_id, status, job_name
        """
        if not self.batch_v1:
            raise RuntimeError("Kubernetes client not initialized")

        # Build label selector
        label_selector = "app=pyrate,component=computing"
        if labels:
            for key, value in labels.items():
                label_selector += f",{key}={value}"

        try:
            jobs = await self.batch_v1.list_namespaced_job(
                namespace=self.namespace,
                label_selector=label_selector,
            )

            tasks = []
            for job in jobs.items:
                job_labels = job.metadata.labels
                task_id = job_labels.get("pyrate.task_id")

                if task_id:
                    status_obj = job.status

                    if status_obj.failed and status_obj.failed > 0:
                        status = "failed"
                    elif status_obj.succeeded and status_obj.succeeded > 0:
                        status = "completed"
                    elif status_obj.active and status_obj.active > 0:
                        status = "running"
                    else:
                        status = "pending"

                    tasks.append(
                        {
                            "task_id": task_id,
                            "job_name": job.metadata.name,
                            "status": status,
                            "labels": job_labels,
                            "active_pods": status_obj.active or 0,
                            "succeeded_pods": status_obj.succeeded or 0,
                            "failed_pods": status_obj.failed or 0,
                        }
                    )

            return tasks

        except ApiException as e:
            logger.error("Failed to list tasks: %s", e)
            raise

    async def get_task_result(self, task_id: str) -> TaskResult:
        """Get the complete result of a Kubernetes task."""
        if not self.batch_v1 or not self.core_v1:
            raise RuntimeError("Kubernetes client not initialized")

        job_name = f"pyrate-task-{task_id[:8]}"

        try:
            job = await self.batch_v1.read_namespaced_job(
                name=job_name, namespace=self.namespace
            )
            status_obj = job.status

            if status_obj.failed and status_obj.failed > 0:
                status = TaskStatus.FAILED
            elif status_obj.succeeded and status_obj.succeeded > 0:
                status = TaskStatus.COMPLETED
            elif status_obj.active and status_obj.active > 0:
                status = TaskStatus.RUNNING
            else:
                status = TaskStatus.PENDING

            # Get logs from the pod
            stdout = None
            try:
                pods = await self.core_v1.list_namespaced_pod(
                    namespace=self.namespace,
                    label_selector=f"job-name={job_name}",
                )
                if pods.items:
                    pod = pods.items[0]
                    logs = await self.core_v1.read_namespaced_pod_log(
                        name=pod.metadata.name, namespace=self.namespace
                    )
                    stdout = logs
            except ApiException:
                pass

            return TaskResult(
                task_id=task_id,
                status=status,
                stdout=stdout,
            )
        except ApiException as e:
            logger.error("Failed to get result for task %s: %s", task_id, e)
            raise

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up completed Kubernetes jobs older than max_age_hours."""
        if not self.batch_v1:
            raise RuntimeError("Kubernetes client not initialized")

        from datetime import datetime, timedelta, timezone

        cutoff = datetime.now(timezone.utc) - timedelta(hours=max_age_hours)
        cleaned = 0

        try:
            jobs = await self.batch_v1.list_namespaced_job(
                namespace=self.namespace,
                label_selector="app=pyrate,component=computing",
            )
            for job in jobs.items:
                completion_time = job.status.completion_time
                if completion_time and completion_time < cutoff:
                    await self.batch_v1.delete_namespaced_job(
                        name=job.metadata.name,
                        namespace=self.namespace,
                        propagation_policy="Background",
                    )
                    cleaned += 1
        except ApiException as e:
            logger.error("Failed to cleanup tasks: %s", e)
            raise

        logger.info("Cleaned up %s completed Kubernetes tasks", cleaned)
        return cleaned
