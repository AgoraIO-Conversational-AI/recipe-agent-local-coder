"""Coordinate one local ACP session with the saved Project Folder."""

import asyncio
from dataclasses import dataclass
from typing import Literal

from .acp_client import AcpAuthenticationRequired, AcpClientPort
from .workspace import WorkspaceService, WorkspaceStatus


RuntimeState = Literal[
    "configuration_required",
    "starting",
    "authentication_required",
    "ready",
    "failed",
]


@dataclass(frozen=True)
class LocalRuntimeStatus:
    """Safe, user-presentable readiness state for the local Codex runtime."""

    state: RuntimeState
    workspace: WorkspaceStatus
    error: str | None = None


class LocalRuntimeCoordinator:
    """Keep at most one ACP session aligned with the selected Project Folder."""

    def __init__(self, workspace: WorkspaceService, acp_client: AcpClientPort) -> None:
        self._workspace = workspace
        self._acp_client = acp_client
        self._state: RuntimeState = "configuration_required"
        self._error: str | None = None
        self._active_directory: str | None = None
        self._lifecycle_lock = asyncio.Lock()

    def status(self) -> LocalRuntimeStatus:
        """Report readiness without spawning, authenticating, or changing selection."""
        workspace = self._workspace.status()
        if workspace.state != "ready" or workspace.workspace is None:
            return LocalRuntimeStatus(
                state="configuration_required",
                workspace=workspace,
                error=(
                    "Select an existing Project Folder before starting the local Codex runtime."
                    if workspace.state == "invalid"
                    else None
                ),
            )
        if self._state == "ready" and self._active_directory != workspace.workspace.primary_directory:
            return LocalRuntimeStatus(state="starting", workspace=workspace)
        return LocalRuntimeStatus(
            state=self._state,
            workspace=workspace,
            error=self._error,
        )

    async def start(self) -> LocalRuntimeStatus:
        """Open ACP only after a valid Project Folder has been saved."""
        async with self._lifecycle_lock:
            return await self._start()

    async def _start(self) -> LocalRuntimeStatus:
        workspace = self._workspace.status()
        if workspace.state != "ready" or workspace.workspace is None:
            self._state = "configuration_required"
            self._error = None
            return self.status()
        if (
            self._state == "ready"
            and self._active_directory == workspace.workspace.primary_directory
        ):
            return self.status()
        return await self._activate_workspace()

    async def activate_workspace(self) -> LocalRuntimeStatus:
        """Replace the active ACP session with one for the saved Project Folder."""
        async with self._lifecycle_lock:
            return await self._activate_workspace()

    async def _activate_workspace(self) -> LocalRuntimeStatus:
        workspace = self._workspace.status()
        if workspace.state != "ready" or workspace.workspace is None:
            self._state = "configuration_required"
            self._error = None
            return self.status()

        primary_directory = workspace.workspace.primary_directory
        if self._state == "ready" and self._active_directory == primary_directory:
            return self.status()

        if self._active_directory is not None:
            await self._acp_client.close()
            self._active_directory = None

        self._state = "starting"
        self._error = None
        try:
            await self._acp_client.open(primary_directory)
        except Exception as exc:
            self._state, self._error = _runtime_failure(exc)
            return self.status()

        self._active_directory = primary_directory
        self._state = "ready"
        return self.status()

    async def close(self) -> None:
        """Release the one active ACP session during replacement or shutdown."""
        async with self._lifecycle_lock:
            await self._close()

    async def _close(self) -> None:
        if self._active_directory is not None:
            await self._acp_client.close()
            self._active_directory = None
        workspace = self._workspace.status()
        self._state = "starting" if workspace.state == "ready" else "configuration_required"
        self._error = None


def _runtime_failure(exc: Exception) -> tuple[RuntimeState, str]:
    detail = str(exc).strip() or type(exc).__name__
    if isinstance(exc, AcpAuthenticationRequired):
        return (
            "authentication_required",
            "Sign in to ChatGPT, then retry the local Codex runtime.",
        )
    return "failed", f"Could not start the local Codex runtime: {detail}"
