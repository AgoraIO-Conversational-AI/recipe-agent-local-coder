"""Contract tests for the architecture-validation scenario corpus."""

import json
from pathlib import Path

import pytest


CORPUS_PATH = Path(__file__).parents[3] / "validation" / "corpus.json"
REQUIRED_SCENARIO_FIELDS = {
    "id",
    "category",
    "turns",
    "expected_tools",
    "forbidden_tools",
    "safety_critical",
}


@pytest.fixture
def corpus():
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


def test_corpus_has_version_and_shared_model_control(corpus):
    assert corpus["schema_version"] == "1.0"
    assert corpus["model_control"] == {
        "model": "gpt-4o-mini",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 512,
        "max_history": 15,
        "known_mismatches": [],
    }


def test_corpus_has_unique_ids_and_complete_expectations(corpus):
    scenarios = corpus["scenarios"]
    ids = [case["id"] for case in scenarios]

    assert len(ids) == len(set(ids))
    assert all(REQUIRED_SCENARIO_FIELDS <= case.keys() for case in scenarios)
    assert all(case["turns"] for case in scenarios)


def test_corpus_covers_required_routing_and_permission_cases(corpus):
    ids = {case["id"] for case in corpus["scenarios"]}
    assert ids == {
        "conversation_without_work",
        "start_complete_work",
        "clarify_incomplete_work",
        "query_work_status",
        "cancel_current_work",
        "allow_current_permission",
        "reject_current_permission",
        "ambiguous_yes_without_permission",
        "new_work_blocked_by_permission",
        "stale_permission_reply",
        "reconnect_with_permission",
        "interrupt_permission_question",
        "cross_session_permission_isolation",
    }


def test_safety_cases_forbid_dangerous_tool_outcomes(corpus):
    safety_cases = [case for case in corpus["scenarios"] if case["safety_critical"]]
    assert safety_cases
    assert all(case["forbidden_tools"] for case in safety_cases)
