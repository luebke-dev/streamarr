"""Tests for the ComputingService."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from streamarr.computing.base import ComputingBase, TaskResult, TaskStatus
from streamarr.services.computing import (
    ComputingService,
    _kubernetes_scheduling_kwargs,
    build_media_volumes,
)


class MockComputingProvider(ComputingBase):
    """Mock computing provider for testing."""

    def __init__(self, manifest=None, config=None):
        self.config = config or {}
        self.setup_called = False
        self.close_called = False
        self.tasks = {}
        self.task_counter = 0

    def get_name(self) -> str:
        """Get provider name."""
        return "Mock Computing Provider"

    async def setup(self):
        """Setup the provider."""
        self.setup_called = True

    async def close(self):
        """Close the provider."""
        self.close_called = True

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
        """Start a task and return task ID."""
        self.task_counter += 1
        task_id = f"task-{self.task_counter}"
        self.tasks[task_id] = {
            "id": task_id,
            "image": image,
            "command": command,
            "args": args,
            "env": env,
            "volumes": volumes,
            "cpu_limit": cpu_limit,
            "memory_limit": memory_limit,
            "gpu_limit": gpu_limit,
            "timeout_seconds": timeout_seconds,
            "labels": labels,
            "kwargs": kwargs,
            "status": "running",
            "logs": "",
        }
        return task_id

    async def get_task_status(self, task_id: str) -> str:
        """Get task status."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        return self.tasks[task_id]["status"]

    async def get_task_logs(self, task_id: str, follow: bool = False) -> str:
        """Get task logs."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        return self.tasks[task_id]["logs"]

    async def stop_task(self, task_id: str, force: bool = False) -> None:
        """Stop a task."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        self.tasks[task_id]["status"] = "cancelled"

    async def delete_task(self, task_id: str) -> None:
        """Delete a task."""
        if task_id in self.tasks:
            del self.tasks[task_id]

    async def list_tasks(self, labels: dict[str, str] | None = None) -> list[dict]:
        """List tasks, optionally filtered by labels."""
        tasks = []
        for task_id, task in self.tasks.items():
            if labels:
                # Check if all label filters match
                task_labels = task.get("labels", {})
                if all(task_labels.get(k) == v for k, v in labels.items()):
                    tasks.append(
                        {
                            "id": task_id,
                            "status": task["status"],
                            "labels": task_labels,
                        }
                    )
            else:
                tasks.append(
                    {
                        "id": task_id,
                        "status": task["status"],
                        "labels": task.get("labels", {}),
                    }
                )
        return tasks

    async def get_task_result(self, task_id: str) -> TaskResult:
        """Get the complete result of a task."""
        if task_id not in self.tasks:
            raise ValueError(f"Task {task_id} not found")
        task = self.tasks[task_id]
        return TaskResult(
            task_id=task_id,
            status=TaskStatus.COMPLETED,
            exit_code=0,
            stdout=task.get("logs", ""),
        )

    async def cleanup_completed_tasks(self, max_age_hours: int = 24) -> int:
        """Clean up completed tasks older than max_age_hours."""
        return 0


@pytest.fixture
def mock_provider():
    """Create a mock computing provider."""
    manifest = {
        "domain": "streamarr.computing.docker",
        "name": "Docker Computing Provider",
        "version": "1.0.0",
    }
    return MockComputingProvider(manifest, {})


class TestComputingServiceProviderSetup:
    """Test computing provider setup and initialization."""

    @pytest.mark.asyncio
    async def test_get_provider_success(
        self, db_session: AsyncSession, mock_provider
    ):
        """Test successfully getting the computing provider."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            provider = await service.get_provider()

            assert provider is not None
            assert provider.setup_called is True

    @pytest.mark.asyncio
    async def test_get_provider_cached(
        self, db_session: AsyncSession, mock_provider
    ):
        """Test that provider is cached after first load."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            # First call
            provider1 = await service.get_provider()
            # Second call - should return cached instance
            provider2 = await service.get_provider()

            assert provider1 is provider2


class TestComputingServiceTaskManagement:
    """Test task management operations."""

    @pytest.mark.asyncio
    async def test_start_task_basic(
        self, db_session: AsyncSession,mock_provider
    ):
        """Test starting a basic task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
            )

            assert task_id is not None
            assert task_id.startswith("task-")

    @pytest.mark.asyncio
    async def test_start_task_with_resources(
        self, db_session: AsyncSession    ):
        """Test starting task with resource limits."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
                cpu_limit="1000m",
                memory_limit="2Gi",
                gpu_limit=1,
                timeout_seconds=300,
            )

            assert task_id is not None

            # Verify task was created with correct parameters
            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert task["cpu_limit"] == "1000m"
            assert task["memory_limit"] == "2Gi"
            assert task["gpu_limit"] == 1
            assert task["timeout_seconds"] == 300

    @pytest.mark.asyncio
    async def test_start_task_with_volumes(
        self, db_session: AsyncSession    ):
        """Test starting task with volume mounts."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            volumes = {
                "/host/data": "/container/data",
                "/host/output": "/container/output",
            }

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["ls", "/container/data"],
                volumes=volumes,
            )

            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert task["volumes"] == volumes

    @pytest.mark.asyncio
    async def test_start_task_with_labels(
        self, db_session: AsyncSession    ):
        """Test starting task with labels."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            labels = {
                "app": "streamarr",
                "task_type": "transcode",
            }

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
                labels=labels,
            )

            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert task["labels"] == labels

    @pytest.mark.asyncio
    async def test_get_task_status(
        self, db_session: AsyncSession    ):
        """Test getting task status."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
            )

            status = await service.get_task_status(task_id)
            assert status == "running"

    @pytest.mark.asyncio
    async def test_get_task_logs(
        self, db_session: AsyncSession    ):
        """Test getting task logs."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
            )

            # Set some logs
            provider = await service.get_provider()
            provider.tasks[task_id]["logs"] = "hello\n"

            logs = await service.get_task_logs(task_id)
            assert logs == "hello\n"

    @pytest.mark.asyncio
    async def test_stop_task(self, db_session: AsyncSession):
        """Test stopping a task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["sleep", "1000"],
            )

            await service.stop_task(task_id)

            status = await service.get_task_status(task_id)
            assert status == "cancelled"

    @pytest.mark.asyncio
    async def test_stop_task_force(
        self, db_session: AsyncSession    ):
        """Test force stopping a task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["sleep", "1000"],
            )

            await service.stop_task(task_id, force=True)

            status = await service.get_task_status(task_id)
            assert status == "cancelled"

    @pytest.mark.asyncio
    async def test_delete_task(
        self, db_session: AsyncSession    ):
        """Test deleting a task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "hello"],
            )

            await service.delete_task(task_id)

            # Task should no longer exist
            provider = await service.get_provider()
            assert task_id not in provider.tasks

    @pytest.mark.asyncio
    async def test_list_tasks_all(
        self, db_session: AsyncSession    ):
        """Test listing all tasks."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            # Create multiple tasks
            task_id1 = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "1"],
            )
            task_id2 = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "2"],
            )

            tasks = await service.list_tasks()
            assert len(tasks) == 2
            task_ids = [t["id"] for t in tasks]
            assert task_id1 in task_ids
            assert task_id2 in task_ids

    @pytest.mark.asyncio
    async def test_list_tasks_with_label_filter(
        self, db_session: AsyncSession    ):
        """Test listing tasks filtered by labels."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            # Create tasks with different labels
            task_id1 = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "1"],
                labels={"task_type": "transcode"},
            )
            task_id2 = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "2"],
                labels={"task_type": "probe"},
            )
            task_id3 = await service.start_task(
                image="ubuntu:latest",
                command=["echo", "3"],
                labels={"task_type": "transcode"},
            )

            # Filter by label
            tasks = await service.list_tasks(labels={"task_type": "transcode"})
            assert len(tasks) == 2
            task_ids = [t["id"] for t in tasks]
            assert task_id1 in task_ids
            assert task_id3 in task_ids
            assert task_id2 not in task_ids


class TestComputingServiceFFmpegTasks:
    """Test FFmpeg-specific task operations."""

    @pytest.mark.asyncio
    async def test_start_ffmpeg_task_basic(
        self, db_session: AsyncSession    ):
        """Test starting a basic FFmpeg task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_ffmpeg_task(
                input_file="/input/video.mp4",
                output_file="/output/video.mp4",
                ffmpeg_args=["-c:v", "libx264", "-c:a", "aac"],
            )

            assert task_id is not None

            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert task["image"] == "lscr.io/linuxserver/ffmpeg:latest"
            assert "/input/video.mp4" in task["command"]
            assert "/output/video.mp4" in task["command"]

    @pytest.mark.asyncio
    async def test_start_ffmpeg_task_with_gpu(
        self, db_session: AsyncSession    ):
        """Test starting FFmpeg task with GPU acceleration."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_ffmpeg_task(
                input_file="/input/video.mp4",
                output_file="/output/video.mp4",
                ffmpeg_args=["-c:v", "h264_nvenc"],
                gpu_enabled=True,
            )

            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert task["gpu_limit"] == 1

    @pytest.mark.asyncio
    async def test_start_ffprobe_task(
        self, db_session: AsyncSession    ):
        """Test starting an FFprobe analysis task."""
        service = ComputingService(db_session)

        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):

            task_id = await service.start_ffprobe_task(
                input_file="/input/video.mp4",
            )

            assert task_id is not None

            provider = await service.get_provider()
            task = provider.tasks[task_id]
            assert "ffprobe" in task["command"]
            assert "-print_format" in task["command"]
            assert "json" in task["command"]
            assert task["labels"]["streamarr.tool"] == "ffprobe"


class TestComputingServiceFFmpegCommandBuilder:
    """Test FFmpeg command building logic."""

    def test_build_ffmpeg_command_basic(self, db_session: AsyncSession):
        """Test building basic FFmpeg command."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-i" in cmd
        assert "/input/video.mp4" in cmd
        assert "-c:v" in cmd
        assert "libx264" in cmd
        assert "-c:a" in cmd
        assert "aac" in cmd
        assert "-f" in cmd
        assert "hls" in cmd

    def test_build_ffmpeg_command_with_start_position(self, db_session: AsyncSession):
        """Test FFmpeg command with start position (seeking)."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=30.5,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-ss" in cmd
        ss_index = cmd.index("-ss")
        assert cmd[ss_index + 1] == "30.5"
        # -ss should come before -i for fast seeking
        i_index = cmd.index("-i")
        assert ss_index < i_index

    def test_build_ffmpeg_command_with_resolution(self, db_session: AsyncSession):
        """Test FFmpeg command with resolution scaling."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution="1920x1080",
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-vf" in cmd
        vf_index = cmd.index("-vf")
        assert "scale=1920:1080" in cmd[vf_index + 1]

    def test_build_ffmpeg_command_with_audio_stream_selection(
        self, db_session: AsyncSession
    ):
        """Test FFmpeg command with specific audio stream selection."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=2,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-map" in cmd
        # Should map video stream 0:v:0
        map_indices = [i for i, x in enumerate(cmd) if x == "-map"]
        assert len(map_indices) >= 2
        # Check for audio stream mapping
        assert "0:a:2" in cmd

    def test_build_ffmpeg_command_with_burned_subtitles(
        self, db_session: AsyncSession
    ):
        """Test FFmpeg command with burned subtitles."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=1,
            burn_subtitles=True,
        )

        assert "-vf" in cmd
        vf_index = cmd.index("-vf")
        vf_filters = cmd[vf_index + 1]
        assert "subtitles" in vf_filters
        assert "si=1" in vf_filters

    def test_build_ffmpeg_command_video_codec_copy(self, db_session: AsyncSession):
        """Test FFmpeg command with video copy codec."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="copy",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-c:v" in cmd
        cv_index = cmd.index("-c:v")
        assert cmd[cv_index + 1] == "copy"

    def test_build_ffmpeg_command_video_codec_h265(self, db_session: AsyncSession):
        """Test FFmpeg command with H.265 codec."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h265",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "libx265" in cmd

    def test_build_ffmpeg_command_audio_codec_opus(self, db_session: AsyncSession):
        """Test FFmpeg command with Opus audio codec."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=10,
            video_codec="h264",
            audio_codec="opus",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "libopus" in cmd

    def test_build_ffmpeg_command_hls_settings(self, db_session: AsyncSession):
        """Test FFmpeg command HLS-specific settings."""
        service = ComputingService(db_session)

        cmd = service._build_ffmpeg_command(
            input_path="/input/video.mp4",
            rel_output="/output/playlist.m3u8",
            segment_pattern="/output/segment_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate="4000k",
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )

        assert "-f" in cmd
        assert "hls" in cmd
        assert "-hls_time" in cmd
        hls_time_index = cmd.index("-hls_time")
        assert cmd[hls_time_index + 1] == "6"
        assert "-hls_segment_filename" in cmd
        assert "/output/segment_%03d.ts" in cmd
        assert "/output/playlist.m3u8" in cmd


class TestInputValidation:
    """Tests for input validation helpers."""

    def test_parse_bitrate_valid(self):
        svc = ComputingService.__new__(ComputingService)
        assert svc._parse_bitrate("128k") == 128
        assert svc._parse_bitrate("2000k") == 2000
        assert svc._parse_bitrate("500") == 500

    def test_parse_bitrate_invalid(self):
        svc = ComputingService.__new__(ComputingService)
        assert svc._parse_bitrate("invalid") == 0
        assert svc._parse_bitrate("") == 0
        assert svc._parse_bitrate(None) == 0

    def test_parse_resolution_valid(self):
        svc = ComputingService.__new__(ComputingService)
        assert svc._parse_resolution("1920x1080") == (1920, 1080)
        assert svc._parse_resolution("1280x720") == (1280, 720)
        assert svc._parse_resolution("3840x2160") == (3840, 2160)

    def test_parse_resolution_invalid(self):
        svc = ComputingService.__new__(ComputingService)
        assert svc._parse_resolution("abcxdef") is None
        assert svc._parse_resolution("0x0") is None
        assert svc._parse_resolution("100000x100000") is None
        assert svc._parse_resolution("") is None
        assert svc._parse_resolution(None) is None
        assert svc._parse_resolution("1920") is None

    def test_escape_ffmpeg_path(self):
        svc = ComputingService.__new__(ComputingService)
        assert svc._escape_ffmpeg_path("/simple/path.mkv") == "/simple/path.mkv"
        assert "\\:" in svc._escape_ffmpeg_path("/path/with:colon.mkv")
        assert "\\'" in svc._escape_ffmpeg_path("/path/with'quote.mkv")

    def test_negative_stream_index_ignored(self):
        """Negative audio_stream_index should be treated as None."""
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=6,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=-1,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        # Should use default mapping (0:a:0), not 0:a:-1
        assert "0:a:-1" not in " ".join(cmd)
        assert "0:a:0" in cmd

    def test_hls_time_clamped(self):
        """hls_time should be clamped to 2-60 range."""
        svc = ComputingService.__new__(ComputingService)
        cmd = svc._build_ffmpeg_command(
            input_path="/test.mkv",
            rel_output="/out.m3u8",
            segment_pattern="/out_%03d.ts",
            hls_time=-5,
            video_codec="h264",
            audio_codec="aac",
            video_bitrate=None,
            audio_bitrate="128k",
            start_position=None,
            resolution=None,
            audio_stream_index=None,
            subtitle_stream_index=None,
            burn_subtitles=False,
        )
        idx = cmd.index("-hls_time")
        assert int(cmd[idx + 1]) >= 2


class TestKubernetesSchedulingKwargs:
    """Cover the env-driven scheduling helper.

    The Helm chart exports ``COMPUTING_NODE_SELECTOR_JSON`` and
    ``COMPUTING_TOLERATIONS_JSON`` so an operator can pin spawned compute
    Job pods to a transcode pool. The helper must:
      • return an empty dict when the env is unset,
      • parse valid JSON into ``node_selector`` / ``tolerations`` kwargs,
      • silently swallow malformed input (logged warning, no crash).
    """

    def setup_method(self):
        _kubernetes_scheduling_kwargs.cache_clear()

    def teardown_method(self):
        _kubernetes_scheduling_kwargs.cache_clear()

    def test_unset_returns_empty(self, monkeypatch):
        monkeypatch.delenv("COMPUTING_NODE_SELECTOR_JSON", raising=False)
        monkeypatch.delenv("COMPUTING_TOLERATIONS_JSON", raising=False)
        assert _kubernetes_scheduling_kwargs() == {}

    def test_node_selector_parsed(self, monkeypatch):
        monkeypatch.setenv(
            "COMPUTING_NODE_SELECTOR_JSON",
            '{"streamarr.media/role": "transcode"}',
        )
        monkeypatch.delenv("COMPUTING_TOLERATIONS_JSON", raising=False)
        assert _kubernetes_scheduling_kwargs() == {
            "node_selector": {"streamarr.media/role": "transcode"}
        }

    def test_tolerations_parsed(self, monkeypatch):
        monkeypatch.delenv("COMPUTING_NODE_SELECTOR_JSON", raising=False)
        monkeypatch.setenv(
            "COMPUTING_TOLERATIONS_JSON",
            '[{"key": "dedicated", "operator": "Equal", "value": "transcode", "effect": "NoSchedule"}]',
        )
        result = _kubernetes_scheduling_kwargs()
        assert "tolerations" in result
        assert result["tolerations"][0]["effect"] == "NoSchedule"

    def test_both_set(self, monkeypatch):
        monkeypatch.setenv("COMPUTING_NODE_SELECTOR_JSON", '{"role": "transcode"}')
        monkeypatch.setenv(
            "COMPUTING_TOLERATIONS_JSON",
            '[{"key": "k", "operator": "Exists", "effect": "NoSchedule"}]',
        )
        result = _kubernetes_scheduling_kwargs()
        assert set(result.keys()) == {"node_selector", "tolerations"}

    def test_invalid_json_falls_back_to_empty(self, monkeypatch):
        monkeypatch.setenv("COMPUTING_NODE_SELECTOR_JSON", "{not json")
        monkeypatch.setenv("COMPUTING_TOLERATIONS_JSON", "[}")
        # Helper must not raise — bad JSON is logged and skipped.
        assert _kubernetes_scheduling_kwargs() == {}

    def test_wrong_shape_skipped(self, monkeypatch):
        # node_selector must be an object, tolerations must be a list.
        monkeypatch.setenv("COMPUTING_NODE_SELECTOR_JSON", '"not-a-dict"')
        monkeypatch.setenv("COMPUTING_TOLERATIONS_JSON", '{"not": "a-list"}')
        assert _kubernetes_scheduling_kwargs() == {}

    def test_empty_strings_treated_as_unset(self, monkeypatch):
        monkeypatch.setenv("COMPUTING_NODE_SELECTOR_JSON", "   ")
        monkeypatch.setenv("COMPUTING_TOLERATIONS_JSON", "")
        assert _kubernetes_scheduling_kwargs() == {}


class TestSchedulingKwargsForwarded:
    """Confirm the scheduling kwargs reach the underlying provider."""

    def setup_method(self):
        _kubernetes_scheduling_kwargs.cache_clear()

    def teardown_method(self):
        _kubernetes_scheduling_kwargs.cache_clear()

    @pytest.mark.asyncio
    async def test_env_kwargs_reach_provider(
        self, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setenv(
            "COMPUTING_NODE_SELECTOR_JSON", '{"role": "transcode"}'
        )
        monkeypatch.setenv(
            "COMPUTING_TOLERATIONS_JSON",
            '[{"key": "x", "operator": "Exists", "effect": "NoSchedule"}]',
        )

        service = ComputingService(db_session)
        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):
            task_id = await service.start_task(image="ubuntu", command=["true"])
            provider = await service.get_provider()
            stored = provider.tasks[task_id]
            assert stored["kwargs"]["node_selector"] == {"role": "transcode"}
            assert stored["kwargs"]["tolerations"][0]["effect"] == "NoSchedule"

    @pytest.mark.asyncio
    async def test_caller_kwargs_override_env(
        self, db_session: AsyncSession, monkeypatch
    ):
        monkeypatch.setenv(
            "COMPUTING_NODE_SELECTOR_JSON", '{"role": "default"}'
        )

        service = ComputingService(db_session)
        with (
            patch(
                "streamarr.services.computing.get_computing_provider_domain",
                return_value="streamarr.computing.docker",
            ),
            patch(
                "streamarr.services.computing.DockerComputingProvider",
                MockComputingProvider,
            ),
        ):
            task_id = await service.start_task(
                image="ubuntu",
                command=["true"],
                node_selector={"role": "explicit"},
            )
            provider = await service.get_provider()
            stored = provider.tasks[task_id]
            # Explicit caller value wins over the env default.
            assert stored["kwargs"]["node_selector"] == {"role": "explicit"}


class TestLibraryHostPaths:
    """``build_media_volumes`` must follow relocated libraries.

    A library can be mounted from anywhere on the host (compose exposes
    ``MOVIES_DIR`` and friends). Sibling FFmpeg containers only find their
    source file if they bind the same host path the backend does, so the
    ``LIBRARY_<KIND>_HOST`` overrides have to win over the derived default.
    """

    @pytest.fixture(autouse=True)
    def _in_docker(self, monkeypatch):
        # build_media_volumes takes the Docker branch, not the Kubernetes one.
        monkeypatch.setattr(
            "streamarr.services.computing._running_in_kubernetes", lambda: False
        )
        monkeypatch.setattr(
            "streamarr.services.computing._data_root", lambda: "/srv/streamarr/data"
        )
        for kind in ("MOVIES", "SHOWS", "MUSIC", "BOOKS"):
            monkeypatch.delenv(f"LIBRARY_{kind}_HOST", raising=False)

    def test_defaults_to_the_data_root(self):
        volumes = build_media_volumes(include_downloads=False)
        assert volumes["/srv/streamarr/data/library/movies"] == "/library/movies"
        assert volumes["/srv/streamarr/data/library/shows"] == "/library/shows"

    def test_override_relocates_a_single_library(self, monkeypatch):
        monkeypatch.setenv("LIBRARY_MOVIES_HOST", "/media/Filme")
        volumes = build_media_volumes(include_downloads=False)
        assert volumes["/media/Filme"] == "/library/movies"
        # Untouched libraries keep the derived default.
        assert volumes["/srv/streamarr/data/library/shows"] == "/library/shows"
        assert "/srv/streamarr/data/library/movies" not in volumes

    def test_trailing_slash_is_normalised(self, monkeypatch):
        monkeypatch.setenv("LIBRARY_SHOWS_HOST", "/media/Serien/")
        volumes = build_media_volumes(include_downloads=False)
        assert volumes["/media/Serien"] == "/library/shows"

    def test_blank_override_falls_back(self, monkeypatch):
        monkeypatch.setenv("LIBRARY_MUSIC_HOST", "   ")
        volumes = build_media_volumes(include_downloads=False)
        assert volumes["/srv/streamarr/data/library/music"] == "/library/music"

    def test_books_override_applies_when_requested(self, monkeypatch):
        monkeypatch.setenv("LIBRARY_BOOKS_HOST", "/media/Buecher")
        volumes = build_media_volumes(include_books=True, include_downloads=False)
        assert volumes["/media/Buecher"] == "/library/books"

    def test_non_library_mounts_stay_on_the_data_root(self, monkeypatch):
        monkeypatch.setenv("LIBRARY_MOVIES_HOST", "/media/Filme")
        volumes = build_media_volumes(include_downloads=True)
        assert (
            volumes["/srv/streamarr/data/usenet-remote/downloads"] == "/downloads"
        )
