"""Append-only, recursively redacted local validation evidence."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


_SENSITIVE_FRAGMENTS = (
    "authorization",
    "api_key",
    "certificate",
    "secret",
    "token",
    "cookie",
)


def _sensitive(key: str) -> bool:
    normalized = key.lower()
    return any(fragment in normalized for fragment in _SENSITIVE_FRAGMENTS)


def redact(value: Any, key: str = "") -> Any:
    if key and _sensitive(key):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {
            str(child_key): redact(child_value, str(child_key))
            for child_key, child_value in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, tuple):
        return [redact(item) for item in value]
    return value


class EvidenceRecorder:
    def __init__(self, path: Path) -> None:
        self.path = path

    def append(self, record: dict[str, Any]) -> None:
        if not record.get("trial_id"):
            raise ValueError("trial_id is required")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        safe = redact(
            {
                **record,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
        )
        with self.path.open("a", encoding="utf-8") as evidence:
            evidence.write(
                json.dumps(safe, ensure_ascii=False, separators=(",", ":"))
                + "\n"
            )

    def completed_trial_ids(self) -> set[str]:
        if not self.path.exists():
            return set()
        completed = set()
        for line in self.path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            trial_id = json.loads(line).get("trial_id")
            if trial_id:
                completed.add(trial_id)
        return completed
