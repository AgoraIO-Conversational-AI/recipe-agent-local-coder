"""Own one ngrok CLI subprocess and discover its clean HTTPS tunnel."""

from __future__ import annotations

import asyncio
import subprocess
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal, Protocol
from urllib.parse import urlparse

import httpx


TunnelState = Literal["starting", "ready", "failed", "stopped"]


@dataclass(frozen=True)
class TunnelStatus:
    state: TunnelState
    public_base_url: str | None = None
    error: str | None = None


class NgrokTunnelError(RuntimeError):
    """One bounded tunnel failure without CLI or credential details."""


class TunnelPort(Protocol):
    async def start(self, local_url: str) -> TunnelStatus: ...

    async def status(self) -> TunnelStatus: ...

    async def close(self) -> None: ...


async def _default_process_factory(*argv, **kwargs):
    return await asyncio.create_subprocess_exec(*argv, **kwargs)


class NgrokCliTunnel:
    """Launch ngrok without a shell and query only its loopback API."""

    def __init__(
        self,
        *,
        command: tuple[str, ...] = ("ngrok",),
        process_factory: Callable[..., Awaitable[object]] | None = None,
        http_client=None,
        startup_attempts: int = 100,
        poll_interval: float = 0.1,
        terminate_timeout: float = 2.0,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    ) -> None:
        self._command = command
        self._process_factory = process_factory or _default_process_factory
        self._http = http_client or httpx.AsyncClient(timeout=1.0, trust_env=False)
        self._owns_http = http_client is None
        self._startup_attempts = startup_attempts
        self._poll_interval = poll_interval
        self._terminate_timeout = terminate_timeout
        self._sleep = sleep
        self._process = None
        self._local_url: str | None = None
        self._status = TunnelStatus("stopped")

    async def start(self, local_url: str) -> TunnelStatus:
        normalized_local = _validate_local_url(local_url)
        if self._process is not None and self._status.state == "ready":
            if self._local_url != normalized_local:
                raise NgrokTunnelError("ngrok_tunnel_unavailable")
            return self._status
        if self._process is not None:
            await self._stop_process()
        argv = (
            *self._command,
            "http",
            normalized_local,
            "--log",
            "stdout",
            "--log-format",
            "json",
        )
        try:
            self._process = await self._process_factory(
                *argv,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=False,
            )
        except Exception as exc:
            raise NgrokTunnelError("ngrok_tunnel_unavailable") from exc
        self._local_url = normalized_local
        self._status = TunnelStatus("starting")
        for _ in range(self._startup_attempts):
            if getattr(self._process, "returncode", None) is not None:
                break
            discovered = await self._discover()
            if discovered is not None:
                self._status = TunnelStatus("ready", public_base_url=discovered)
                return self._status
            await self._sleep(self._poll_interval)
        await self._stop_process()
        self._status = TunnelStatus("failed", error="ngrok_tunnel_unavailable")
        raise NgrokTunnelError("ngrok_tunnel_unavailable")

    async def status(self) -> TunnelStatus:
        process = self._process
        if process is None:
            return self._status
        if getattr(process, "returncode", None) is not None:
            self._status = TunnelStatus("failed", error="ngrok_tunnel_unavailable")
            return self._status
        discovered = await self._discover()
        if discovered is None:
            self._status = TunnelStatus("failed", error="ngrok_tunnel_unavailable")
        else:
            self._status = TunnelStatus("ready", public_base_url=discovered)
        return self._status

    async def close(self) -> None:
        await self._stop_process()
        if self._owns_http:
            await self._http.aclose()
            self._owns_http = False
        self._status = TunnelStatus("stopped")

    async def _stop_process(self) -> None:
        process = self._process
        self._process = None
        self._local_url = None
        if process is not None and getattr(process, "returncode", None) is None:
            process.terminate()
            try:
                await asyncio.wait_for(process.wait(), self._terminate_timeout)
            except TimeoutError:
                process.kill()
                await process.wait()

    async def _discover(self) -> str | None:
        if self._local_url is None:
            return None
        try:
            response = await self._http.get(
                "http://127.0.0.1:4040/api/tunnels"
            )
            response.raise_for_status()
            payload = response.json()
        except Exception:
            return None
        tunnels = payload.get("tunnels", []) if isinstance(payload, dict) else []
        for item in tunnels:
            if not isinstance(item, dict):
                continue
            config = item.get("config")
            address = config.get("addr") if isinstance(config, dict) else None
            if address != self._local_url:
                continue
            public_url = item.get("public_url")
            if isinstance(public_url, str):
                clean = _clean_public_url(public_url)
                if clean is not None:
                    return clean
        return None


def _validate_local_url(value: str) -> str:
    parsed = urlparse(value)
    if (
        parsed.scheme != "http"
        or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}
        or parsed.port is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError("ngrok requires a clean loopback HTTP listener URL")
    return value.rstrip("/")


def _clean_public_url(value: str) -> str | None:
    parsed = urlparse(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        return None
    return f"https://{parsed.netloc}"
