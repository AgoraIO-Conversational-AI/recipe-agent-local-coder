"""Safe, backend-neutral ACP session boundary types."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AcpSession:
    """One ACP session bound to the resolved Project Folder."""

    primary_directory: str


class AcpAuthenticationRequired(RuntimeError):
    """The ACP client needs the user to complete its local sign-in flow."""


@dataclass(frozen=True)
class AcpSessionEvent:
    """A safe description of an ACP session update, without its content."""

    kind: str
    label: str


AcpPermissionKind = Literal[
    "allow_once",
    "allow_always",
    "reject_once",
    "reject_always",
]


@dataclass(frozen=True)
class AcpPermissionOption:
    """One correlated ACP choice retained only inside the local runtime."""

    option_id: str
    name: str
    kind: AcpPermissionKind


@dataclass(frozen=True)
class AcpPermissionRequest:
    """A bounded, user-presentable ACP permission prompt."""

    authorization_id: str
    operation: str
    options: tuple[AcpPermissionOption, ...]


@dataclass(frozen=True)
class AcpPermissionOutcome:
    """The one ACP option selected by an explicit future user decision."""

    option_id: str | None


AcpStopReason = Literal[
    "end_turn",
    "max_tokens",
    "max_turn_requests",
    "refusal",
    "cancelled",
]


@dataclass(frozen=True)
class AcpPromptResult:
    """Backend-neutral terminal result for one ACP prompt."""

    stop_reason: AcpStopReason
    final_text: str


class AcpPromptObserver(Protocol):
    """Receives safe updates and resolves a current-operation permission."""

    async def on_event(self, event: AcpSessionEvent) -> None:
        """Persist or project one bounded safe activity event."""

    async def request_permission(
        self, request: AcpPermissionRequest
    ) -> AcpPermissionOutcome:
        """Wait for an explicit current-operation permission outcome."""


class AcpClientPort(Protocol):
    """The lifecycle seam used by local runtime coordination."""

    async def open(self, primary_directory: str) -> AcpSession:
        """Open one ACP session in the resolved Project Folder."""

    async def prompt(
        self, objective: str, observer: AcpPromptObserver
    ) -> AcpPromptResult:
        """Execute one objective through the active persistent ACP session."""

    async def cancel(self) -> None:
        """Request cancellation of the active prompt; confirmation remains async."""

    async def close(self) -> None:
        """Close the active ACP session and its child process."""
