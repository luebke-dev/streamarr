"""Environment detection for computing provider selection."""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


class Environment:
    """Detected environment types."""

    KUBERNETES = "kubernetes"
    DOCKER = "docker"
    UNKNOWN = "unknown"


def detect_environment() -> str:
    """
    Detect the current runtime environment.

    Returns:
        Environment constant (KUBERNETES, DOCKER, or UNKNOWN)
    """
    # Check for Kubernetes service account
    k8s_sa_path = Path("/var/run/secrets/kubernetes.io/serviceaccount")
    if k8s_sa_path.exists() and k8s_sa_path.is_dir():
        logger.info("Detected Kubernetes environment (service account found)")
        return Environment.KUBERNETES

    # Check for Kubernetes environment variables
    if os.getenv("KUBERNETES_SERVICE_HOST") or os.getenv("KUBERNETES_SERVICE_PORT"):
        logger.info("Detected Kubernetes environment (environment variables found)")
        return Environment.KUBERNETES

    # Check for Docker environment
    dockerenv_path = Path("/.dockerenv")
    if dockerenv_path.exists():
        logger.info("Detected Docker environment (/.dockerenv found)")
        return Environment.DOCKER

    # Check if running inside container (cgroup check)
    try:
        with open("/proc/1/cgroup") as f:
            cgroup_content = f.read()
            if "docker" in cgroup_content or "containerd" in cgroup_content:
                logger.info("Detected Docker environment (cgroup check)")
                return Environment.DOCKER
    except (FileNotFoundError, PermissionError):
        pass

    # Check for docker.sock
    docker_sock = Path("/var/run/docker.sock")
    if docker_sock.exists():
        logger.info("Detected Docker environment (docker.sock available)")
        return Environment.DOCKER

    logger.warning("Could not detect environment, defaulting to Docker")
    return Environment.DOCKER


def get_computing_provider_domain() -> str:
    """
    Get the appropriate computing provider domain based on environment.

    Returns:
        Plugin domain string ("kubernetes" or "docker")
    """
    env = detect_environment()

    if env == Environment.KUBERNETES:
        return "kubernetes"
    else:
        # Default to Docker for both DOCKER and UNKNOWN
        return "docker"
