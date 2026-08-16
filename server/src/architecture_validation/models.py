"""Immutable boundary types used by the architecture validation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


PermissionDecision = Literal["allow", "reject"]
SyntheticWorkState = Literal["accepted", "cancelled"]


@dataclass(frozen=True)
class PendingPermission:
    session_id: str
    authorization_id: str
    version: int
    operation: str
    question: str
    created_at: datetime


@dataclass(frozen=True)
class PermissionResolution:
    code: str
    authorization_id: Optional[str] = None
    version: Optional[int] = None
    decision: Optional[PermissionDecision] = None


@dataclass(frozen=True)
class ToolObservation:
    scenario_id: str
    session_id: str
    name: str
    arguments: dict[str, object]
    result: dict[str, object]
    observed_at: datetime


@dataclass(frozen=True)
class RuntimeSessionBinding:
    session_id: str
    scenario_id: str
    mcp_bearer: str
    expires_at: datetime

    @classmethod
    def for_test(
        cls, *, session_id: str, scenario_id: str
    ) -> "RuntimeSessionBinding":
        """Build a deterministic binding for unit tests only."""
        from datetime import timedelta, timezone

        return cls(
            session_id=session_id,
            scenario_id=scenario_id,
            mcp_bearer=f"test-mcp-{session_id}",
            expires_at=datetime.now(timezone.utc) + timedelta(minutes=5),
        )


@dataclass(frozen=True)
class SyntheticWork:
    work_id: str
    session_id: str
    objective: str
    idempotency_key: str
    state: SyntheticWorkState
    created_at: datetime
