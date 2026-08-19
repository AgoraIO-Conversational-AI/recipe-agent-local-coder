"""Managed Agent MCP injection and per-Agent capability lifecycle."""

import asyncio

import pytest
from agora_agent.agentkit import Agent as AgoraAgent

from managed_ingress.models import VoiceMcpLease


class FakeBridge:
    def __init__(self, events):
        self.events = events
        self.lease = VoiceMcpLease(
            endpoint="https://voice.example.ngrok.app/mcp/",
            authorization="Bearer test-secret",
            lease_id="lease-a",
        )

    async def prepare_agent(self):
        self.events.append("bridge.prepare")
        return self.lease

    async def activate_agent(self, lease_id, agent_id):
        self.events.append(f"bridge.activate:{lease_id}:{agent_id}")

    async def revoke_agent(self, lease_id):
        self.events.append(f"bridge.revoke:{lease_id}")


def test_work_mode_builds_managed_llm_with_exact_mcp_contract(
    fake_env, monkeypatch
):
    import agent

    events = []
    bridge = FakeBridge(events)
    captured = {}

    class FakeSession:
        async def start(self):
            events.append("session.start")
            return "agent-a"

        async def stop(self):
            events.append("session.stop")

    def create_session(self, **_kwargs):
        captured["llm"] = self.llm
        return FakeSession()

    monkeypatch.setattr(AgoraAgent, "create_async_session", create_session)
    instance = agent.Agent(work_bridge=bridge)

    result = asyncio.run(
        instance.start(channel_name="ch", agent_uid=111, user_uid=222)
    )

    assert result["agent_id"] == "agent-a"
    llm = captured["llm"]
    assert llm["params"]["model"] == "gpt-4o-mini"
    assert llm["mcp_servers"] == [
        {
            "name": "acplocal",
            "endpoint": "https://voice.example.ngrok.app/mcp/",
            "transport": "streamable_http",
            "headers": {"Authorization": "Bearer test-secret"},
            "allowed_tools": [
                "start_work",
                "get_work_status",
                "cancel_work",
                "respond_permission",
            ],
            "timeout_ms": 5000,
        }
    ]
    assert events == [
        "bridge.prepare",
        "session.start",
        "bridge.activate:lease-a:agent-a",
    ]


def test_stop_revokes_capability_before_stopping_session(fake_env, monkeypatch):
    import agent

    events = []
    bridge = FakeBridge(events)

    class FakeSession:
        async def start(self):
            events.append("session.start")
            return "agent-a"

        async def stop(self):
            events.append("session.stop")

    monkeypatch.setattr(
        AgoraAgent, "create_async_session", lambda self, **_kwargs: FakeSession()
    )
    instance = agent.Agent(work_bridge=bridge)
    asyncio.run(instance.start(channel_name="ch", agent_uid=111, user_uid=222))

    asyncio.run(instance.stop("agent-a"))

    assert events[-2:] == ["bridge.revoke:lease-a", "session.stop"]


def test_start_failure_revokes_pending_capability(fake_env, monkeypatch):
    import agent

    events = []
    bridge = FakeBridge(events)

    class FailingSession:
        async def start(self):
            raise RuntimeError("managed failure with secret")

    monkeypatch.setattr(
        AgoraAgent, "create_async_session", lambda self, **_kwargs: FailingSession()
    )
    instance = agent.Agent(work_bridge=bridge)

    with pytest.raises(RuntimeError, match="managed failure"):
        asyncio.run(
            instance.start(channel_name="ch", agent_uid=111, user_uid=222)
        )

    assert events == ["bridge.prepare", "bridge.revoke:lease-a"]


def test_session_construction_failure_revokes_pending_capability(
    fake_env, monkeypatch
):
    import agent

    events = []
    bridge = FakeBridge(events)

    def fail_session_construction(self, **_kwargs):
        raise RuntimeError("session construction failed with secret")

    monkeypatch.setattr(
        AgoraAgent, "create_async_session", fail_session_construction
    )
    instance = agent.Agent(work_bridge=bridge)

    with pytest.raises(RuntimeError, match="session construction failed"):
        asyncio.run(
            instance.start(channel_name="ch", agent_uid=111, user_uid=222)
        )

    assert events == ["bridge.prepare", "bridge.revoke:lease-a"]


def test_evidence_and_production_work_modes_are_mutually_exclusive(fake_env):
    import agent
    from architecture_validation.config import ValidationConfig

    config = ValidationConfig.from_mapping(
        {
            "VALIDATION_MODEL": "gpt-4o-mini",
            "PUBLIC_VALIDATION_BASE_URL": "https://example.ngrok.app",
        }
    )

    with pytest.raises(ValueError, match="mutually exclusive"):
        agent.Agent(evidence_config=config, work_bridge=FakeBridge([]))
