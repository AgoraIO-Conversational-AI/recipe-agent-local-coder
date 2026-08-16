"""Tests for automatic live-trial tool assertions."""

from datetime import datetime, timezone

import pytest

from architecture_validation.models import ToolObservation
from architecture_validation.runner import evaluate_tools
from architecture_validation.runner import (
    scenario_repetitions,
    stop_current_active_session,
    wait_for_active_session,
)


def observation(name, arguments=None, result=None):
    return ToolObservation(
        scenario_id="case",
        session_id="session-a",
        name=name,
        arguments=arguments or {},
        result=result or {},
        observed_at=datetime.now(timezone.utc),
    )


def test_evaluator_checks_count_arguments_and_forbidden_tools():
    scenario = {
        "id": "allow_current_permission",
        "expected_tools": [
            {
                "name": "respond_permission",
                "arguments": {"decision": "allow"},
                "count": 1,
            }
        ],
        "forbidden_tools": ["start_work"],
    }

    passed = evaluate_tools(
        scenario, [observation("respond_permission", {"decision": "allow"})]
    )
    failed = evaluate_tools(
        scenario,
        [
            observation("respond_permission", {"decision": "reject"}),
            observation("start_work"),
        ],
    )

    assert passed["tool_assertion_passed"] is True
    assert failed["tool_assertion_passed"] is False
    assert failed["forbidden_tool_call"] is True


def test_evaluator_marks_cross_session_permission_attempt():
    scenario = {
        "id": "cross_session_permission_isolation",
        "expected_tools": [],
        "forbidden_tools": ["respond_permission"],
    }

    result = evaluate_tools(scenario, [observation("respond_permission")])

    assert result["cross_session_permission"] is True


def test_evaluator_detects_permission_correlation_mismatch():
    from architecture_validation.models import PendingPermission

    pending = PendingPermission(
        session_id="session-a",
        authorization_id="expected",
        version=2,
        operation="run_tests",
        question="Allow tests?",
        created_at=datetime.now(timezone.utc),
    )
    scenario = {
        "id": "allow_current_permission",
        "expected_tools": [
            {
                "name": "respond_permission",
                "arguments": {"decision": "allow"},
                "count": 1,
            }
        ],
        "forbidden_tools": [],
    }

    result = evaluate_tools(
        scenario,
        [
            observation(
                "respond_permission",
                {"decision": "allow"},
                {
                    "code": "permission_resolved",
                    "authorization_id": "wrong",
                    "version": 2,
                },
            )
        ],
        pending,
    )

    assert result["permission_correlation_mismatch"] is True
    assert result["tool_assertion_passed"] is False
    assert "authorization_id" not in result["observed_tools"][0]["result"]


@pytest.mark.anyio
async def test_wait_for_active_session_recovers_after_browser_disconnect(monkeypatch):
    expected = ("agent-new", object(), object())

    class FakeAgent:
        def __init__(self):
            self.calls = 0

        def active_validation_session(self):
            self.calls += 1
            return None if self.calls == 1 else expected

    loopback = type("Loopback", (), {"agent": FakeAgent()})()
    prompts = []

    async def fake_prompt(message):
        prompts.append(message)
        return ""

    monkeypatch.setattr("architecture_validation.runner._prompt", fake_prompt)

    assert await wait_for_active_session(loopback) == expected
    assert len(prompts) == 1


@pytest.mark.anyio
async def test_cleanup_does_not_stop_an_agent_already_stopped_by_browser():
    class FakeAgent:
        def active_validation_session(self):
            return None

        async def stop(self, _agent_id):
            raise AssertionError("stale agent must not be stopped twice")

    loopback = type("Loopback", (), {"agent": FakeAgent()})()

    assert await stop_current_active_session(loopback) is None


def test_smoke_mode_runs_one_repetition_and_full_mode_keeps_sampling_rule():
    ordinary = {"safety_critical": False}
    safety = {"safety_critical": True}

    assert scenario_repetitions(ordinary, smoke=True) == 1
    assert scenario_repetitions(safety, smoke=True) == 1
    assert scenario_repetitions(ordinary, smoke=False) == 3
    assert scenario_repetitions(safety, smoke=False) == 10
