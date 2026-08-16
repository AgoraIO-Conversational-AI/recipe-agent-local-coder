"""Tests for local validation evidence recording."""

import json

from architecture_validation.recorder import EvidenceRecorder, redact


def test_redact_removes_sensitive_values_recursively():
    value = {
        "authorization": "Bearer abc",
        "nested": {
            "api_key": "key",
            "safe": "keep",
            "items": [{"callback_token": "token"}],
        },
    }

    assert redact(value) == {
        "authorization": "[REDACTED]",
        "nested": {
            "api_key": "[REDACTED]",
            "safe": "keep",
            "items": [{"callback_token": "[REDACTED]"}],
        },
    }


def test_recorder_appends_without_overwriting_and_reports_completed_ids(tmp_path):
    path = tmp_path / "managed.jsonl"
    recorder = EvidenceRecorder(path)
    recorder.append({"trial_id": "a", "passed": True})
    recorder.append({"trial_id": "b", "passed": False})

    records = [json.loads(line) for line in path.read_text().splitlines()]

    assert [record["trial_id"] for record in records] == ["a", "b"]
    assert recorder.completed_trial_ids() == {"a", "b"}
    assert all("recorded_at" in record for record in records)


def test_recorder_never_serializes_secret_field_values(tmp_path):
    path = tmp_path / "managed-extra.jsonl"
    EvidenceRecorder(path).append(
        {"trial_id": "a", "provider_secret": "do-not-write"}
    )

    assert "do-not-write" not in path.read_text()
    assert "[REDACTED]" in path.read_text()
