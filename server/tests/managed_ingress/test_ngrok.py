"""ngrok CLI ownership through fake process and local-API boundaries."""

import asyncio

import pytest

from managed_ingress.ngrok import NgrokCliTunnel, NgrokTunnelError


class FakeResponse:
    def __init__(self, payload, *, error: Exception | None = None):
        self._payload = payload
        self._error = error

    def raise_for_status(self):
        if self._error is not None:
            raise self._error

    def json(self):
        return self._payload


class FakeHttpClient:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.urls = []

    async def get(self, url):
        self.urls.append(url)
        response = self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


class FakeProcess:
    def __init__(self, *, exits=False, ignore_terminate=False):
        self.returncode = 1 if exits else None
        self.ignore_terminate = ignore_terminate
        self.terminated = 0
        self.killed = 0

    def terminate(self):
        self.terminated += 1
        if not self.ignore_terminate:
            self.returncode = 0

    def kill(self):
        self.killed += 1
        self.returncode = -9

    async def wait(self):
        if self.ignore_terminate and self.killed == 0:
            await asyncio.Event().wait()
        return self.returncode


def tunnel_payload(public_url="https://voice.example.ngrok.app", addr="http://127.0.0.1:8001"):
    return {"tunnels": [{"public_url": public_url, "config": {"addr": addr}}]}


@pytest.mark.anyio
async def test_start_selects_clean_https_tunnel_without_a_shell():
    process = FakeProcess()
    commands = []

    async def process_factory(*argv, **kwargs):
        commands.append((argv, kwargs))
        return process

    http = FakeHttpClient(tunnel_payload())
    tunnel = NgrokCliTunnel(
        process_factory=process_factory,
        http_client=http,
        startup_attempts=1,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    status = await tunnel.start("http://127.0.0.1:8001")

    assert status.state == "ready"
    assert status.public_base_url == "https://voice.example.ngrok.app"
    assert commands[0][0] == (
        "ngrok",
        "http",
        "http://127.0.0.1:8001",
        "--log",
        "stdout",
        "--log-format",
        "json",
        "--web-addr",
        "127.0.0.1:4041",
    )
    assert commands[0][1]["start_new_session"] is False
    assert "secret" not in repr(status)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "public_url",
    [
        "http://voice.example.ngrok.app",
        "https://person:password@voice.example.ngrok.app",
        "https://voice.example.ngrok.app/path",
        "https://voice.example.ngrok.app?token=secret",
    ],
)
async def test_start_rejects_unclean_public_urls(public_url):
    async def process_factory(*_argv, **_kwargs):
        return FakeProcess()

    tunnel = NgrokCliTunnel(
        process_factory=process_factory,
        http_client=FakeHttpClient(tunnel_payload(public_url=public_url)),
        startup_attempts=1,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    with pytest.raises(NgrokTunnelError, match="ngrok_tunnel_unavailable"):
        await tunnel.start("http://127.0.0.1:8001")


@pytest.mark.anyio
async def test_process_exit_and_health_loss_return_only_bounded_errors():
    async def process_factory(*_argv, **_kwargs):
        return FakeProcess(exits=True)

    tunnel = NgrokCliTunnel(
        process_factory=process_factory,
        http_client=FakeHttpClient(RuntimeError("authtoken=private-secret")),
        startup_attempts=1,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    with pytest.raises(NgrokTunnelError) as failure:
        await tunnel.start("http://127.0.0.1:8001")
    assert str(failure.value) == "ngrok_tunnel_unavailable"
    assert "private-secret" not in str(failure.value)


@pytest.mark.anyio
async def test_failed_start_can_retry_after_local_auth_is_fixed():
    processes = [FakeProcess(exits=True), FakeProcess()]

    async def process_factory(*_argv, **_kwargs):
        return processes.pop(0)

    tunnel = NgrokCliTunnel(
        process_factory=process_factory,
        http_client=FakeHttpClient(tunnel_payload()),
        startup_attempts=1,
        sleep=lambda _seconds: asyncio.sleep(0),
    )

    with pytest.raises(NgrokTunnelError, match="ngrok_tunnel_unavailable"):
        await tunnel.start("http://127.0.0.1:8001")

    retried = await tunnel.start("http://127.0.0.1:8001")
    assert retried.state == "ready"


@pytest.mark.anyio
async def test_status_detects_url_change_and_close_escalates_once():
    process = FakeProcess(ignore_terminate=True)

    async def process_factory(*_argv, **_kwargs):
        return process

    tunnel = NgrokCliTunnel(
        process_factory=process_factory,
        http_client=FakeHttpClient(
            tunnel_payload(),
            tunnel_payload(public_url="https://replacement.example.ngrok.app"),
        ),
        startup_attempts=1,
        terminate_timeout=0.001,
        sleep=lambda _seconds: asyncio.sleep(0),
    )
    await tunnel.start("http://127.0.0.1:8001")

    changed = await tunnel.status()
    await tunnel.close()
    await tunnel.close()

    assert changed.public_base_url == "https://replacement.example.ngrok.app"
    assert process.terminated == 1
    assert process.killed == 1
