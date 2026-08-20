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
    assert llm["system_messages"] == [
        {
            "role": "system",
            "content": (
                "You are a voice interface to one local coding Agent. Speak "
                "briefly and keep ordinary conversation responsive.\n\n"
                "One Project Folder is already selected. Registered tools are "
                "capabilities you can use. If answering or acting depends on "
                "the selected Workspace or local environment, call start_work "
                "with the user's objective in natural language. Do not ask the "
                "user for a command or say you cannot access the Project Folder "
                "unless the tool reports that it is unavailable. Ask one "
                "question only when the requested outcome cannot be determined "
                "from the conversation.\n\n"
                "Treat every tool result as authoritative. Use get_work_status "
                "before answering about existing Work. Use cancel_work only "
                "after an explicit request to cancel Work; barge-in, silence, "
                "or a request to stop speaking never cancels Work. Use "
                "respond_permission only for an explicit allow or reject of the "
                "current Pending Permission. Unrelated agreement is never "
                "permission, and while permission is pending do not start new "
                "Work.\n"
            ),
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


def test_work_result_speaks_only_through_the_exact_active_work_session(
    fake_env, monkeypatch
):
    import agent

    events = []
    bridge = FakeBridge(events)

    class FakeSession:
        def __init__(self):
            self.say_calls = []

        async def start(self):
            return "agent-a"

        async def say(self, text, priority=None, interruptable=None):
            self.say_calls.append((text, priority, interruptable))

        async def stop(self):
            events.append("session.stop")

    session = FakeSession()
    monkeypatch.setattr(
        AgoraAgent, "create_async_session", lambda self, **_kwargs: session
    )
    instance = agent.Agent(work_bridge=bridge)
    asyncio.run(instance.start(channel_name="ch", agent_uid=111, user_uid=222))

    assert instance.has_work_session("agent-a") is True
    assert instance.has_work_session("agent-b") is False
    assert asyncio.run(instance.say_work_result("agent-a", "Tests passed")) is True
    assert asyncio.run(instance.say_work_result("agent-b", "Wrong session")) is False
    assert session.say_calls == [("Tests passed", "APPEND", True)]

    asyncio.run(instance.stop("agent-a"))

    assert instance.has_work_session("agent-a") is False
    assert asyncio.run(instance.say_work_result("agent-a", "Too late")) is False
    assert session.say_calls == [("Tests passed", "APPEND", True)]


def test_baseline_session_is_not_eligible_for_work_delivery(fake_env, monkeypatch):
    import agent

    class FakeSession:
        async def start(self):
            return "agent-baseline"

        async def say(self, *_args, **_kwargs):
            raise AssertionError("baseline session must not receive Work delivery")

        async def stop(self):
            pass

    monkeypatch.setattr(
        AgoraAgent, "create_async_session", lambda self, **_kwargs: FakeSession()
    )
    instance = agent.Agent()
    asyncio.run(instance.start(channel_name="ch", agent_uid=111, user_uid=222))

    assert instance.has_work_session("agent-baseline") is False
    assert (
        asyncio.run(instance.say_work_result("agent-baseline", "Do not speak"))
        is False
    )


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
