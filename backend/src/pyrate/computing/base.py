"""Base classes for computing providers (Docker, Kubernetes)."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class TaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class TaskResult:
    task_id: str
    status: TaskStatus
    exit_code: int | None = None
    stdout: str | None = None
    stderr: str | None = None
    error: str | None = None
    metadata: dict[str, Any] | None = None


@dataclass
class TaskConfig:
    image: str
    command: list[str] | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    cpu_limit: str | None = None
    memory_limit: str | None = None
    gpu_limit: int | None = None
    volumes: dict[str, str] | None = None
    working_dir: str | None = None
    timeout_seconds: int | None = None
    restart_policy: str = "Never"
    labels: dict[str, str] | None = None
    annotations: dict[str, str] | None = None
    devices: list[dict[str, str]] | None = None


class ComputingBase(ABC):
    """Abstract base class for computing providers."""

    @abstractmethod
    async def start_task(self, image: str, command: list[str] | None = None, args: list[str] | None = None, env: dict[str, str] | None = None, volumes: dict[str, str] | None = None, cpu_limit: str | None = None, memory_limit: str | None = None, gpu_limit: int | None = None, timeout_seconds: int | None = None, labels: dict[str, str] | None = None, devices: list[dict[str, str]] | None = None, **kwargs) -> str:
        pass

    @abstractmethod
    async def get_task_status(self, task_id: str) -> str:
        pass

    @abstractmethod
    async def get_task_logs(self, task_id: str, follow: bool = False) -> str:
        pass

    @abstractmethod
    async def stop_task(self, task_id: str, force: bool = False) -> None:
        pass

    @abstractmethod
    async def delete_task(self, task_id: str) -> None:
        pass

    @abstractmethod
    async def get_task_result(self, task_id: str) -> TaskResult:
        pass

    @abstractmethod
    async def list_tasks(self, labels: dict[str, str] | None = None) -> list[dict[str, Any]]:
        pass

    @abstractmethod
    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        pass

    async def close(self) -> None:
        pass
