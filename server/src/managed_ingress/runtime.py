"""Coordinate the dedicated MCP listener, ngrok, and per-Agent capability."""

from __future__ import annotations

import asyncio
import os
from typing import Protocol
from urllib.parse import urlparse

import uvicorn

from .capabilities import CapabilityRegistry
from .http_policy import IngressHostPolicy
from .models import CapabilityBinding, VoiceMcpLease
from .ngrok import TunnelPort, TunnelStatus


class ManagedIngressError(RuntimeError):
    """A fixed local lifecycle error with no tunnel or credential details."""


class ReadinessPort(Protocol):
    def status(self): ...


class ListenerPort(Protocol):
    local_url: str

    async def start(self) -> None: ...

    async def close(self) -> None: ...


class IngressHandlerTracker:
    """Close handler entry synchronously, then drain already-entered calls."""

    def __init__(self) -> None:
        self._accepting = True
        self._active = 0
        self._empty = asyncio.Event()
        self._empty.set()

    def try_enter(self) -> bool:
        if not self._accepting:
            return False
        self._active += 1
        self._empty.clear()
        return True

    def leave(self) -> None:
        if self._active <= 0:
            return
        self._active -= 1
        if self._active == 0:
            self._empty.set()

    async def stop_and_drain(self, timeout: float) -> bool:
        self._accepting = False
        if self._active == 0:
            return True
        try:
            await asyncio.wait_for(self._empty.wait(), timeout)
        except TimeoutError:
            return False
        return True


class UvicornListener:
    """Run one signal-free loopback ASGI listener inside the backend process."""

    def __init__(self, app, *, port: int | None = None) -> None:
        self._port = port or int(os.getenv("VOICE_ACP_MCP_PORT", "8001"))
        self.local_url = f"http://127.0.0.1:{self._port}"
        self._server = uvicorn.Server(
            uvicorn.Config(app, host="127.0.0.1", port=self._port, log_level="warning")
        )
        self._server.install_signal_handlers = lambda: None
        self._task: asyncio.Task[None] | None = None

    async def start(self) -> None:
        if self._task is not None:
            return
        self._task = asyncio.create_task(
            self._server.serve(), name="managed-mcp-listener"
        )
        for _ in range(100):
            if self._server.started:
                return
            if self._task.done():
                break
            await asyncio.sleep(0.05)
        await self.close()
        raise ManagedIngressError("mcp_listener_unavailable")

    async def close(self) -> None:
        task = self._task
        self._task = None
        if task is None:
            return
        self._server.should_exit = True
        try:
            await asyncio.wait_for(task, 2.0)
        except TimeoutError:
            self._server.force_exit = True
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass


class ManagedIngressCoordinator:
    """Bind one stable Workspace to one active Managed Agent MCP capability."""

    def __init__(
        self,
        *,
        readiness: ReadinessPort,
        listener: ListenerPort,
        tunnel: TunnelPort,
        registry: CapabilityRegistry,
        host_policy: IngressHostPolicy,
        handler_tracker: IngressHandlerTracker,
    ) -> None:
        self._readiness = readiness
        self._listener = listener
        self._tunnel = tunnel
        self._registry = registry
        self._host_policy = host_policy
        self.handler_tracker = handler_tracker
        self._lock = asyncio.Lock()
        self._started = False
        self._quiesced = False
        self._workspace_id: str | None = None
        self._workspace_generation = 0
        self._public_base_url: str | None = None
        self._active_lease_id: str | None = None
        self._restart_required = False
        self._accepting = False

    async def start(self) -> None:
        async with self._lock:
            if self._started:
                return
            await self._listener.start()
            self._started = True

    async def prepare_agent(self) -> VoiceMcpLease:
        async with self._lock:
            if not self._started or self._quiesced:
                raise ManagedIngressError("runtime_unavailable")
            if self._restart_required:
                raise ManagedIngressError("managed_agent_restart_required")
            workspace_id = self._ready_workspace_id()
            self._apply_workspace(workspace_id)
            tunnel_status = await self._ensure_tunnel()
            public_base_url = tunnel_status.public_base_url
            if public_base_url is None:
                raise ManagedIngressError("runtime_unavailable")
            self._apply_public_url(public_base_url)
            if self._restart_required:
                raise ManagedIngressError("managed_agent_restart_required")
            try:
                lease = self._registry.prepare(
                    workspace_id, self._workspace_generation
                )
            except RuntimeError as exc:
                raise ManagedIngressError(str(exc)) from exc
            self._active_lease_id = lease.lease_id
            return VoiceMcpLease(
                endpoint=f"{public_base_url}/mcp/",
                authorization=f"Bearer {lease.bearer}",
                lease_id=lease.lease_id,
            )

    async def activate_agent(
        self, lease_id: str, agora_agent_id: str
    ) -> CapabilityBinding:
        async with self._lock:
            if lease_id != self._active_lease_id or self._restart_required:
                raise ManagedIngressError("capability_not_found")
            binding = self._registry.activate(lease_id, agora_agent_id)
            self._accepting = True
            return binding

    async def revoke_agent(self, lease_id: str) -> None:
        async with self._lock:
            self._registry.revoke(lease_id)
            if lease_id == self._active_lease_id:
                self._active_lease_id = None
                self._restart_required = False
                self._accepting = False

    async def refresh_health(self) -> TunnelStatus:
        async with self._lock:
            status = await self._tunnel.status()
            if status.state != "ready" or status.public_base_url is None:
                self._accepting = False
                return status
            self._apply_public_url(status.public_base_url)
            if not self._restart_required and self._registry.active_binding() is not None:
                self._accepting = True
            return status

    def current_workspace_identity(self) -> tuple[str, int] | None:
        if not self._accepting or self._workspace_id is None:
            return None
        try:
            current = self._ready_workspace_id()
        except ManagedIngressError:
            return None
        if current != self._workspace_id:
            return None
        return self._workspace_id, self._workspace_generation

    async def quiesce(self, timeout: float = 5.0) -> bool:
        async with self._lock:
            if self._quiesced:
                return True
            self._registry.revoke_active()
            self._quiesced = True
        drained = await self.handler_tracker.stop_and_drain(timeout)
        self._accepting = False
        self._host_policy.deactivate()
        return drained

    async def close(self) -> None:
        if not self._quiesced:
            await self.quiesce()
        async with self._lock:
            await self._tunnel.close()
            await self._listener.close()
            self._started = False

    def _ready_workspace_id(self) -> str:
        status = self._readiness.status()
        workspace_status = getattr(status, "workspace", None)
        workspace = getattr(workspace_status, "workspace", None)
        if (
            getattr(status, "state", None) != "ready"
            or getattr(workspace_status, "state", None) != "ready"
            or workspace is None
        ):
            raise ManagedIngressError("runtime_unavailable")
        return str(workspace.id)

    def _apply_workspace(self, workspace_id: str) -> None:
        if self._workspace_id == workspace_id:
            return
        self._workspace_id = workspace_id
        self._workspace_generation += 1
        if self._active_lease_id is not None:
            self._registry.revoke(self._active_lease_id)
            self._restart_required = True
            self._accepting = False

    async def _ensure_tunnel(self) -> TunnelStatus:
        if self._public_base_url is None:
            try:
                return await self._tunnel.start(self._listener.local_url)
            except Exception as exc:
                raise ManagedIngressError("runtime_unavailable") from exc
        status = await self._tunnel.status()
        if status.state == "ready":
            return status
        try:
            return await self._tunnel.start(self._listener.local_url)
        except Exception as exc:
            raise ManagedIngressError("runtime_unavailable") from exc

    def _apply_public_url(self, public_base_url: str) -> None:
        host = urlparse(public_base_url).hostname
        if host is None:
            raise ManagedIngressError("runtime_unavailable")
        if self._public_base_url is not None and self._public_base_url != public_base_url:
            self._workspace_generation += 1
            if self._active_lease_id is not None:
                self._registry.revoke(self._active_lease_id)
                self._restart_required = True
                self._accepting = False
        self._public_base_url = public_base_url
        self._host_policy.activate(host)
