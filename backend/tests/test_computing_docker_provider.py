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
