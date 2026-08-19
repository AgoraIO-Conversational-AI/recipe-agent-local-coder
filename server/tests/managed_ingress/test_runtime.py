"""Managed ingress lifecycle, Workspace generation, and shutdown drain."""

import asyncio
from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from managed_ingress.capabilities import CapabilityRegistry
from managed_ingress.http_policy import IngressHostPolicy
from managed_ingress.ngrok import TunnelStatus
from managed_ingress.runtime import (
    IngressHandlerTracker,
    ManagedIngressCoordinator,
    ManagedIngressError,
)


class FakeListener:
    def __init__(self, events):
        self.local_url = "http://127.0.0.1:8001"
        self.events = events

    async def start(self):
        self.events.append("listener.started")

    async def close(self):
        self.events.append("listener.closed")


class FakeTunnel:
    def __init__(self, events):
        self.events = events
        self.current = TunnelStatus(
            "ready", public_base_url="https://voice.example.ngrok.app"
        )

    async def start(self, local_url):
        self.events.append(f"tunnel.started:{local_url}")
        return self.current

    async def status(self):
        return self.current

    async def close(self):
        self.events.append("tunnel.closed")


@dataclass
class FakeReadiness:
    workspace_id: str = "scope-a"
    state: str = "ready"

    def status(self):
        workspace = (
            SimpleNamespace(id=self.workspace_id)
            if self.workspace_id
            else None
        )
        return SimpleNamespace(
            state=self.state,
            workspace=SimpleNamespace(state="ready", workspace=workspace),
        )


@pytest.fixture
def coordinator_context():
    events = []
    registry = CapabilityRegistry(
        token_factory=lambda: "test-bearer",
        id_factory=lambda: "lease-a",
    )
    tunnel = FakeTunnel(events)
    listener = FakeListener(events)
    readiness = FakeReadiness()
    tracker = IngressHandlerTracker()
    coordinator = ManagedIngressCoordinator(
        readiness=readiness,
        listener=listener,
        tunnel=tunnel,
        registry=registry,
        host_policy=IngressHostPolicy(),
        handler_tracker=tracker,
        health_interval=0.001,
    )
    return SimpleNamespace(
        events=events,
        registry=registry,
        tunnel=tunnel,
        listener=listener,
        readiness=readiness,
        tracker=tracker,
        coordinator=coordinator,
    )


@pytest.mark.anyio
async def test_prepare_starts_listener_and_tunnel_only_after_acp_is_ready(
    coordinator_context,
):
    context = coordinator_context
    await context.coordinator.start()
    context.readiness.state = "starting"

    with pytest.raises(ManagedIngressError, match="runtime_unavailable"):
        await context.coordinator.prepare_agent()
    assert context.events == ["listener.started"]

    context.readiness.state = "ready"
    lease = await context.coordinator.prepare_agent()
    assert lease.endpoint == "https://voice.example.ngrok.app/mcp/"
    assert lease.authorization == "Bearer test-bearer"
    assert "test-bearer" not in repr(lease)
    assert context.events == [
        "listener.started",
        "tunnel.started:http://127.0.0.1:8001",
    ]
    await context.coordinator.activate_agent(lease.lease_id, "agent-a")
    assert context.coordinator.current_workspace_identity() == ("scope-a", 1)


@pytest.mark.anyio
async def test_activation_binds_exact_agent_and_url_change_requires_replacement(
    coordinator_context,
):
    context = coordinator_context
    await context.coordinator.start()
    lease = await context.coordinator.prepare_agent()
    binding = await context.coordinator.activate_agent(lease.lease_id, "agent-a")
    assert binding.agora_agent_id == "agent-a"

    context.tunnel.current = TunnelStatus(
        "ready", public_base_url="https://replacement.example.ngrok.app"
    )
    for _ in range(100):
        if context.registry.resolve("test-bearer") is None:
            break
        await asyncio.sleep(0.002)

    assert context.registry.resolve("test-bearer") is None
    assert context.coordinator.current_workspace_identity() is None
    with pytest.raises(
        ManagedIngressError, match="managed_agent_restart_required"
    ):
        await context.coordinator.prepare_agent()

    await context.coordinator.revoke_agent(lease.lease_id)


@pytest.mark.anyio
async def test_tunnel_loss_blocks_new_calls_without_cancelling_local_work(
    coordinator_context,
):
    context = coordinator_context
    await context.coordinator.start()
    lease = await context.coordinator.prepare_agent()
    await context.coordinator.activate_agent(lease.lease_id, "agent-a")
    context.tunnel.current = TunnelStatus(
        "failed", error="ngrok_tunnel_unavailable"
    )

    for _ in range(100):
        if context.coordinator.current_workspace_identity() is None:
            break
        await asyncio.sleep(0.002)

    assert context.coordinator.current_workspace_identity() is None
    assert context.registry.resolve("test-bearer") is not None


@pytest.mark.anyio
async def test_quiesce_revokes_then_drains_before_transport_close(
    coordinator_context,
):
    context = coordinator_context
    await context.coordinator.start()
    lease = await context.coordinator.prepare_agent()
    await context.coordinator.activate_agent(lease.lease_id, "agent-a")
    assert context.tracker.try_enter() is True

    quiescing = asyncio.create_task(context.coordinator.quiesce(timeout=0.2))
    await asyncio.sleep(0)
    assert context.registry.resolve("test-bearer") is None
    assert quiescing.done() is False
    context.tracker.leave()
    await quiescing
    await context.coordinator.close()

    assert context.events[-2:] == ["tunnel.closed", "listener.closed"]
    assert context.tracker.try_enter() is False


@pytest.mark.anyio
async def test_drain_deadline_cancels_held_handler_and_closes_entry(
    coordinator_context,
):
    context = coordinator_context
    await context.coordinator.start()
    entered = asyncio.Event()

    async def held_handler():
        assert context.tracker.try_enter() is True
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            context.tracker.leave()

    handler = asyncio.create_task(held_handler())
    await entered.wait()
    drained = await context.coordinator.quiesce(timeout=0.001)

    assert drained is False
    assert context.tracker.try_enter() is False
    with pytest.raises(asyncio.CancelledError):
        await handler
