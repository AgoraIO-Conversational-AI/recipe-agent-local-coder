"""Immutable boundary types used by the architecture validation."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Optional


VoiceLlmPath = Literal["managed", "custom"]
PermissionDecision = Literal["allow", "reject"]


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
    observed_at: datetime
