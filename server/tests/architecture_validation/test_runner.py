"""Tests for automatic live-trial tool assertions."""

from datetime import datetime, timezone

from architecture_validation.models import ToolObservation
from architecture_validation.runner import evaluate_tools


def observation(name, arguments=None):
    return ToolObservation(
        scenario_id="case",
        session_id="session-a",
        name=name,
        arguments=arguments or {},
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
