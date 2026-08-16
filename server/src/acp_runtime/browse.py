"""One in-memory native Project Folder picker operation."""

import asyncio
import secrets
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Literal

from .picker import DirectoryPicker
from .workspace import WorkspaceStatus


BrowseState = Literal["picking", "ready", "cancelled", "failed"]
_CANCELLED_MESSAGE = "Project Folder selection was cancelled"
_FAILED_MESSAGE = "Could not select the Project Folder"


@dataclass(frozen=True)
class BrowseOperationStatus:
    operation_id: str
    state: BrowseState
    workspace: WorkspaceStatus | None = None
    error: str | None = None


class BrowseAlreadyActive(RuntimeError):
    """Raised when the single local picker is already open."""


class BrowseOperationNotFound(LookupError):
    """Raised for an unknown or obsolete picker operation identifier."""


class BrowseSelectionFailed(RuntimeError):
    """A bounded selection/activation failure safe for the local UI."""


class WorkspaceBrowseCoordinator:
    """Start one native picker without holding its HTTP request open."""

    def __init__(
        self,
        picker: DirectoryPicker,
        select_workspace: Callable[[str], Awaitable[WorkspaceStatus]],
    ) -> None:
        self._picker = picker
        self._select_workspace = select_workspace
        self._status: BrowseOperationStatus | None = None
        self._task: asyncio.Task[None] | None = None

    def start(self) -> BrowseOperationStatus:
        if self._task is not None and not self._task.done():
            raise BrowseAlreadyActive("A Project Folder picker is already open")
        operation_id = secrets.token_urlsafe(18)
        self._status = BrowseOperationStatus(
            operation_id=operation_id,
            state="picking",
        )
        self._task = asyncio.create_task(self._run(operation_id))
        return self._status

    def status(self, operation_id: str) -> BrowseOperationStatus:
        status = self._status
        if status is None or status.operation_id != operation_id:
            raise BrowseOperationNotFound("Project Folder picker operation not found")
        return status

    async def wait(self, operation_id: str) -> BrowseOperationStatus:
        self.status(operation_id)
        task = self._task
        if task is not None:
            await task
        return self.status(operation_id)

    async def _run(self, operation_id: str) -> None:
        try:
            selected = await self._picker.pick()
            if selected is None:
                completed = BrowseOperationStatus(
                    operation_id=operation_id,
                    state="cancelled",
                    error=_CANCELLED_MESSAGE,
                )
            else:
                workspace = await self._select_workspace(selected)
                completed = BrowseOperationStatus(
                    operation_id=operation_id,
                    state="ready",
                    workspace=workspace,
                )
        except BrowseSelectionFailed as exc:
            completed = BrowseOperationStatus(
                operation_id=operation_id,
                state="failed",
                error=str(exc),
            )
        except Exception:
            completed = BrowseOperationStatus(
                operation_id=operation_id,
                state="failed",
                error=_FAILED_MESSAGE,
            )

        if self._status is not None and self._status.operation_id == operation_id:
            self._status = completed
