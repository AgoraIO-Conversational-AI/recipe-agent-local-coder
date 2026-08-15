"""Tests for deterministic offline report generation."""

from architecture_validation.report import build_report, render_markdown


def trial(path, trial_id, **overrides):
    value = {
        "path": path,
        "trial_id": trial_id,
        "scenario_id": "start_complete_work",
        "safety_critical": False,
        "passed": True,
        "tool_assertion_passed": True,
        "first_response_ms": 500.0,
        "configuration_steps": 2 if path == "managed" else 3,
        "invalidated": False,
        "cross_session_permission": False,
        "permission_correlation_mismatch": False,
        "start_work_while_permission_pending": False,
        "forbidden_tool_call": False,
    }
    value.update(overrides)
    return value


def test_report_selects_unique_safe_winner_by_predeclared_order():
    records = [
        trial("managed", "m1", first_response_ms=600),
        trial("managed", "m2", first_response_ms=700),
        trial("custom", "c1", first_response_ms=400),
        trial("custom", "c2", first_response_ms=500),
    ]

    report = build_report(records, {"start_complete_work": 2})

    assert report["winner"] == "managed"
    assert report["candidates"]["managed"]["tool_accuracy"] == 1.0
    assert report["candidates"]["managed"]["p95_first_response_ms"] == 700


def test_report_disqualifies_any_safety_failure():
    records = [
        trial(
            "managed",
            "m1",
            scenario_id="cross_session_permission_isolation",
            safety_critical=True,
            passed=False,
            cross_session_permission=True,
        ),
        trial("managed", "m2"),
        trial("custom", "c1", first_response_ms=900),
        trial(
            "custom",
            "c2",
            scenario_id="cross_session_permission_isolation",
            safety_critical=True,
        ),
    ]

    report = build_report(
        records,
        {
            "cross_session_permission_isolation": 1,
            "start_complete_work": 1,
        },
    )

    assert report["winner"] == "custom"
    assert report["candidates"]["managed"]["disqualifiers"]


def test_invalidated_trials_remain_counted_but_not_scored():
    records = [
        trial("managed", "m-invalid", invalidated=True, passed=False),
        trial("managed", "m1"),
        trial("custom", "c1"),
    ]

    report = build_report(records, {"start_complete_work": 1})

    assert report["candidates"]["managed"]["recorded_trials"] == 2
    assert report["candidates"]["managed"]["scored_trials"] == 1


def test_markdown_contains_evidence_summary():
    report = build_report(
        [trial("managed", "m1"), trial("custom", "c1", first_response_ms=800)],
        {"start_complete_work": 1},
    )

    markdown = render_markdown(report)

    assert "# Voice LLM Architecture Validation" in markdown
    assert "Winner: `managed`" in markdown
    assert "Tool accuracy" in markdown


def test_report_is_inconclusive_until_every_required_sample_exists():
    report = build_report(
        [trial("managed", "m1"), trial("custom", "c1")],
        {"start_complete_work": 3},
    )

    assert report["winner"] is None
    assert "managed:start_complete_work has 1/3" in report["inconclusive_reason"]
