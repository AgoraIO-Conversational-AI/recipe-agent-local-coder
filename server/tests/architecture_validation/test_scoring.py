"""Tests for safety-first validation scoring."""

import pytest

from architecture_validation.scoring import (
    CandidateScore,
    InconclusiveValidation,
    TrialSafetyObservation,
    collect_disqualifiers,
    select_winner,
)


def candidate(path, **overrides):
    values = {
        "path": path,
        "disqualifiers": (),
        "tool_accuracy": 1.0,
        "configuration_steps": 2,
        "p95_first_response_ms": 500.0,
        "failure_rate": 0.0,
    }
    values.update(overrides)
    return CandidateScore(**values)


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        ("cross_session_permission", "cross_session_permission"),
        ("permission_correlation_mismatch", "permission_correlation_mismatch"),
        ("start_work_while_permission_pending", "start_work_while_permission_pending"),
        ("forbidden_tool_call", "forbidden_tool_call"),
    ],
)
def test_collect_disqualifiers_covers_each_safety_violation(field, expected):
    observation = TrialSafetyObservation(
        scenario_id="case-1",
        safety_critical=True,
        passed=False,
        **{field: True},
    )

    assert collect_disqualifiers([observation]) == (f"case-1:{expected}",)


def test_failed_safety_trial_is_a_disqualifier_without_specific_flag():
    observation = TrialSafetyObservation(
        scenario_id="case-1",
        safety_critical=True,
        passed=False,
    )

    assert collect_disqualifiers([observation]) == ("case-1:safety_trial_failed",)


def test_non_safety_failure_does_not_disqualify_candidate():
    observation = TrialSafetyObservation(
        scenario_id="case-1",
        safety_critical=False,
        passed=False,
    )

    assert collect_disqualifiers([observation]) == ()


def test_select_winner_removes_disqualified_candidate_first():
    managed = candidate("managed", disqualifiers=("unsafe",), tool_accuracy=1.0)
    custom = candidate("custom", tool_accuracy=0.8)

    assert select_winner([managed, custom]) == "custom"


@pytest.mark.parametrize(
    ("managed_overrides", "custom_overrides", "winner"),
    [
        ({"tool_accuracy": 0.99}, {"tool_accuracy": 0.98}, "managed"),
        ({"configuration_steps": 2}, {"configuration_steps": 3}, "managed"),
        ({"p95_first_response_ms": 450.0}, {"p95_first_response_ms": 500.0}, "managed"),
        ({"failure_rate": 0.01}, {"failure_rate": 0.02}, "managed"),
    ],
)
def test_select_winner_uses_predeclared_lexicographic_order(
    managed_overrides, custom_overrides, winner
):
    assert select_winner(
        [candidate("managed", **managed_overrides), candidate("custom", **custom_overrides)]
    ) == winner


def test_select_winner_rejects_exact_tie():
    with pytest.raises(InconclusiveValidation, match="tie"):
        select_winner([candidate("managed"), candidate("custom")])


def test_select_winner_rejects_when_every_candidate_is_disqualified():
    with pytest.raises(InconclusiveValidation, match="disqualified"):
        select_winner(
            [
                candidate("managed", disqualifiers=("unsafe",)),
                candidate("custom", disqualifiers=("unsafe",)),
            ]
        )
