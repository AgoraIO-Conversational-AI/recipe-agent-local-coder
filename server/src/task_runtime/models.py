"""Backend-neutral Work, permission, activity, and result types."""

from dataclasses import dataclass
from typing import Literal


WorkState = Literal[
    "queued",
    "starting",
    "running",
    "awaiting_permission",
    "cancelling",
    "completed",
    "cancelled",
    "failed",
]
DeliveryState = Literal[
    "not_ready",
    "pending_delivery",
    "sending",
    "accepted",
    "delivery_unknown",
]
PermissionDecision = Literal["allow", "reject"]
PermissionKind = Literal[
    "allow_once",
    "allow_always",
    "reject_once",
    "reject_always",
]

TERMINAL_STATES: frozenset[WorkState] = frozenset(
    {"completed", "cancelled", "failed"}
)
NONTERMINAL_STATES: frozenset[WorkState] = frozenset(
    {
        "queued",
        "starting",
        "running",
        "awaiting_permission",
        "cancelling",
    }
)
_TRANSITIONS: dict[WorkState, frozenset[WorkState]] = {
    "queued": frozenset({"starting", "cancelled"}),
    "starting": frozenset({"running", "failed"}),
    "running": frozenset(
        {"awaiting_permission", "cancelling", "completed", "failed"}
    ),
    "awaiting_permission": frozenset({"running", "cancelling"}),
    "cancelling": frozenset({"cancelled", "failed"}),
    "completed": frozenset(),
    "cancelled": frozenset(),
    "failed": frozenset(),
}


def ensure_transition(current: WorkState, target: WorkState) -> None:
    """Reject state changes outside the reviewed public Work lifecycle."""
    if target not in _TRANSITIONS[current]:
        raise ValueError(f"Illegal Work transition: {current} -> {target}")


def _normalized_bounded(value: str, *, name: str, max_bytes: int) -> str:
    normalized = value.strip()
    if "\x00" in normalized:
        raise ValueError(f"{name} cannot contain NUL characters")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} cannot exceed {max_bytes} bytes")
    return normalized


@dataclass(frozen=True)
class PermissionOption:
    option_id: str
    name: str
    kind: PermissionKind


@dataclass(frozen=True)
class PendingPermission:
    work_id: str
    authorization_id: str
    operation: str
    options: tuple[PermissionOption, ...]


@dataclass(frozen=True)
class SafeActivity:
    event_id: int | None
    work_id: str
    workspace_id: str
    kind: str
    label: str
    created_at: str


@dataclass(frozen=True)
class FinalPresentation:
    speech: str
    inline: str | None = None

    def __post_init__(self) -> None:
        speech = _normalized_bounded(
            self.speech,
            name="speech",
            max_bytes=16 * 1024,
        )
        if not speech:
            raise ValueError("speech is required")
        inline = (
            _normalized_bounded(
                self.inline,
                name="inline",
                max_bytes=256 * 1024,
            )
            if self.inline is not None
            else None
        )
        object.__setattr__(self, "speech", speech)
        object.__setattr__(self, "inline", inline)


@dataclass(frozen=True)
class WorkReceipt:
    work_id: str
    workspace_id: str
    idempotency_key: str
    objective: str
    state: WorkState
    created_at: str
    updated_at: str
    final_presentation: FinalPresentation | None = None
    error: str | None = None
    delivery_agent_id: str | None = None
    delivery_state: DeliveryState = "not_ready"
