"""Docker computing provider: the configured runtime socket is honoured.

``docker_host`` is advertised in the provider's config schema, so a user can
point it at Podman's socket (``unix:///run/podman/podman.sock``) or a remote
daemon. The value used to be dropped: the client was constructed with no URL,
so it always fell back to environment/auto-discovery, which probes only the
Docker socket paths. On a Podman host the provider therefore failed to connect
no matter what was configured.

These lock the three cases that matter: configured host wins, an empty value
still auto-discovers (so the default deployment is unchanged), and a Podman
URL is passed through verbatim.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import aiodocker
import pytest

from streamarr.computing.docker import DockerComputingProvider


def _provider(config=None):
    return DockerComputingProvider(config=config)


@pytest.mark.asyncio
async def test_configured_host_is_passed_to_the_client():
    provider = _provider({"docker_host": "unix:///run/podman/podman.sock"})
    fake = MagicMock()
    fake.version = AsyncMock(return_value={"Version": "5.0"})
    with patch("streamarr.computing.docker.aiodocker.Docker", return_value=fake) as ctor:
        await provider.setup()

    # The whole point of the fix: the configured value reaches the client.
    assert ctor.call_args.kwargs["url"] == "unix:///run/podman/podman.sock"
    assert provider.client is fake


@pytest.mark.asyncio
async def test_empty_host_falls_back_to_auto_discovery():
    # An empty string must behave like an unset value, otherwise the default
    # Compose deployment (which sets no docker_host) would try to connect to
    # the empty URL instead of probing the known socket paths.
    provider = _provider({"docker_host": ""})
    fake = MagicMock()
    fake.version = AsyncMock(return_value={"Version": "24.0"})
    with patch("streamarr.computing.docker.aiodocker.Docker", return_value=fake) as ctor:
        await provider.setup()

    assert ctor.call_args.kwargs["url"] is None


@pytest.mark.asyncio
async def test_whitespace_host_falls_back_to_auto_discovery():
    provider = _provider({"docker_host": "   "})
    fake = MagicMock()
    fake.version = AsyncMock(return_value={})
    with patch("streamarr.computing.docker.aiodocker.Docker", return_value=fake) as ctor:
        await provider.setup()

    assert ctor.call_args.kwargs["url"] is None


@pytest.mark.asyncio
async def test_missing_config_key_falls_back_to_auto_discovery():
    provider = _provider({})
    fake = MagicMock()
    fake.version = AsyncMock(return_value={})
    with patch("streamarr.computing.docker.aiodocker.Docker", return_value=fake) as ctor:
        await provider.setup()

    assert ctor.call_args.kwargs["url"] is None


@pytest.mark.asyncio
async def test_setup_failure_propagates():
    # A wrong socket must surface, not be swallowed into a provider that looks
    # initialised but has no client.
    provider = _provider({"docker_host": "unix:///does/not/exist.sock"})
    with patch(
        "streamarr.computing.docker.aiodocker.Docker",
        side_effect=RuntimeError("cannot connect"),
    ):
        with pytest.raises(RuntimeError):
            await provider.setup()


def test_schema_documents_the_podman_socket():
    schema = _provider().get_config_schema()
    hint = schema["docker_host"]["hint"]
    # The hint is what a user sees when configuring this; it must name both
    # runtimes now that both are supported.
    assert "podman.sock" in hint
    assert "docker.sock" in hint
    assert schema["docker_host"]["required"] is False


# ---------------------------------------------------------------------------
# Task lookup across process boundaries
# ---------------------------------------------------------------------------
#
# The provider tracks started containers in an in-memory map, and every task
# run builds a fresh provider. A container created by another process (the API
# starting a transcode, or an earlier worker sweep) was therefore "not found"
# and stop/delete silently did nothing - which is how containers left in
# `created` state survived the orphan sweep forever, retried every minute.


def _fake_container(*, running, status=None, container_id="abc123"):
    container = MagicMock()
    container.id = container_id
    container.show = AsyncMock(
        return_value={"State": {"Running": running, "Status": status or "", "ExitCode": 0}}
    )
    container.kill = AsyncMock()
    container.stop = AsyncMock()
    container.delete = AsyncMock()
    return container


def _provider_with_containers(containers):
    provider = _provider()
    provider.client = MagicMock()
    provider.client.containers.list = AsyncMock(return_value=containers)
    provider.client.containers.get = AsyncMock(
        side_effect=aiodocker.exceptions.DockerError(404, {"message": "No such container"})
    )
    return provider


@pytest.mark.asyncio
async def test_stop_task_finds_a_container_started_by_another_process():
    container = _fake_container(running=True, container_id="def456")
    provider = _provider_with_containers([container])

    await provider.stop_task("task-from-earlier-run", force=True)

    provider.client.containers.list.assert_awaited_once()
    # Lookup went through the label every container is started with.
    filters = provider.client.containers.list.await_args.kwargs["filters"]
    assert filters["label"] == ["streamarr.task_id=task-from-earlier-run"]
    container.kill.assert_awaited_once()
    # The hit is remembered, so the next call is a map lookup again.
    assert provider._containers["task-from-earlier-run"] == "def456"


@pytest.mark.asyncio
async def test_stop_task_ignores_a_container_that_never_started():
    # `created` containers cannot be killed or stopped; raising there was what
    # made the orphan sweep retry the same container every minute forever.
    container = _fake_container(running=False, status="created")
    provider = _provider_with_containers([container])

    await provider.stop_task("task-id", force=True)

    container.kill.assert_not_awaited()
    container.stop.assert_not_awaited()


@pytest.mark.asyncio
async def test_delete_task_removes_a_container_found_by_label():
    container = _fake_container(running=False, status="created")
    provider = _provider_with_containers([container])

    await provider.delete_task("task-id")

    container.delete.assert_awaited_once()
    assert "task-id" not in provider._containers


@pytest.mark.asyncio
async def test_delete_task_treats_a_missing_container_as_done():
    provider = _provider_with_containers([])

    # No exception: the caller wanted it gone, and it is gone.
    await provider.delete_task("task-id")

    assert "task-id" not in provider._containers


@pytest.mark.asyncio
async def test_stop_task_reports_a_missing_container_without_raising():
    provider = _provider_with_containers([])

    await provider.stop_task("task-id")
