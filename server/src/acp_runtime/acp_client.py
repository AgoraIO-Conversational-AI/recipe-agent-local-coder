"""Safe, backend-neutral ACP session boundary types."""

from dataclasses import dataclass
from typing import Literal, Protocol


@dataclass(frozen=True)
class AcpSession:
    """One ACP session bound to the resolved Project Folder."""

    primary_directory: str


@dataclass(frozen=True)
class AcpSessionEvent:
    """A safe description of an ACP session update, without its content."""

    kind: str


@dataclass(frozen=True)
class AcpPermissionRequest:
    """A bounded, user-presentable ACP permission prompt."""

    operation: str
    options: tuple[str, ...]


class AcpClientPort(Protocol):
    """The lifecycle seam used by local runtime coordination."""

    async def open(self, primary_directory: str) -> AcpSession:
        """Open one ACP session in the resolved Project Folder."""

    async def close(self) -> None:
        """Close the active ACP session and its child process."""
