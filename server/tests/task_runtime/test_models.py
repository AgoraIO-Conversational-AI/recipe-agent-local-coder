"""Public Work domain model behavior."""

from dataclasses import replace

import pytest

from task_runtime.models import FinalPresentation, WorkReceipt, ensure_transition


@pytest.fixture
def work_receipt() -> WorkReceipt:
    return WorkReceipt(
        work_id="work-a",
        workspace_id="scope-a",
        idempotency_key="turn-a",
        objective="Run the tests",
        state="queued",
        created_at="2026-08-19T00:00:00Z",
        updated_at="2026-08-19T00:00:00Z",
    )


def test_work_state_machine_accepts_only_public_lifecycle_edges():
    allowed = {
        ("queued", "starting"),
        ("queued", "cancelled"),
        ("starting", "running"),
        ("starting", "failed"),
        ("running", "awaiting_permission"),
        ("awaiting_permission", "running"),
        ("running", "cancelling"),
        ("awaiting_permission", "cancelling"),
        ("running", "completed"),
        ("running", "failed"),
        ("cancelling", "cancelled"),
        ("cancelling", "failed"),
    }
    for current, target in allowed:
        ensure_transition(current, target)

    with pytest.raises(ValueError, match="Illegal Work transition"):
        ensure_transition("completed", "running")


def test_final_presentation_requires_bounded_speech_and_safe_optional_inline():
    result = FinalPresentation(speech="  Tests passed.  ", inline="  `pytest` passed  ")

    assert result.speech == "Tests passed."
    assert result.inline == "`pytest` passed"

    with pytest.raises(ValueError, match="speech is required"):
        FinalPresentation(speech="   ")
    with pytest.raises(ValueError, match="NUL"):
        FinalPresentation(speech="unsafe\x00text")
    with pytest.raises(ValueError, match="16384 bytes"):
        FinalPresentation(speech="x" * 16_385)
    with pytest.raises(ValueError, match="262144 bytes"):
        FinalPresentation(speech="ok", inline="x" * 262_145)


def test_terminal_receipt_is_immutable_by_transition_policy(
    work_receipt: WorkReceipt,
):
    completed = replace(work_receipt, state="completed")

    with pytest.raises(ValueError, match="Illegal Work transition"):
        ensure_transition(completed.state, "queued")
