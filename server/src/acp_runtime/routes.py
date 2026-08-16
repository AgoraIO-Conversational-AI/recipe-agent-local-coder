"""Loopback-only Project Folder configuration routes."""

from dataclasses import asdict
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .browse import (
    BrowseAlreadyActive,
    BrowseOperationNotFound,
    BrowseOperationStatus,
    BrowseSelectionFailed,
    WorkspaceBrowseCoordinator,
)
from .loopback import require_loopback
from .picker import DirectoryPicker
from .readiness import LocalRuntimeCoordinator
from .workspace import WorkspaceService, WorkspaceStatus


class SelectWorkspaceRequest(BaseModel):
    path: str


@dataclass(frozen=True)
class WorkspaceChange:
    """One explicit Workspace mutation a future Work/permission gate may block."""

    operation: Literal["replace", "clear"]
    path: str | None = None


class WorkspaceSwitchGuard(Protocol):
    """Optional future Work/permission gate before a Workspace mutation."""

    def check(self, previous: WorkspaceStatus, change: WorkspaceChange) -> str | None:
        """Return a stable conflict message, or None when a switch is allowed."""


class AllowWorkspaceSwitch:
    """Default guard for the current runtime, which has no Work state yet."""

    def check(self, previous: WorkspaceStatus, change: WorkspaceChange) -> str | None:
        del previous, change
        return None


def _envelope(status: WorkspaceStatus | BrowseOperationStatus) -> dict[str, object]:
    return {
        "code": 0,
        "msg": "success",
        "data": asdict(status),
    }


def build_workspace_router(
    *,
    service: WorkspaceService,
    picker: DirectoryPicker,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard | None = None,
) -> APIRouter:
    router = APIRouter(prefix="/local/workspace", include_in_schema=False)
    resolved_guard = switch_guard or AllowWorkspaceSwitch()

    async def select_for_browse(path: str) -> WorkspaceStatus:
        try:
            return await _select_and_activate_status(
                service, runtime, resolved_guard, path
            )
        except HTTPException as exc:
            raise BrowseSelectionFailed(
                "Could not select the Project Folder"
            ) from exc

    browse_coordinator = WorkspaceBrowseCoordinator(picker, select_for_browse)

    @router.get("")
    async def get_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(service.status())

    @router.post("/browse", status_code=202)
    async def browse_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        try:
            return _envelope(browse_coordinator.start())
        except BrowseAlreadyActive as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @router.get("/browse/{operation_id}")
    async def get_browse_operation(
        operation_id: str, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        try:
            return _envelope(browse_coordinator.status(operation_id))
        except BrowseOperationNotFound as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.put("")
    async def select_workspace(
        payload: SelectWorkspaceRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        return _envelope(
            await _select_and_activate_status(
                service, runtime, resolved_guard, payload.path
            )
        )

    @router.delete("")
    async def clear_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        previous = service.status()
        conflict = resolved_guard.check(previous, WorkspaceChange(operation="clear"))
        if conflict is not None:
            raise HTTPException(status_code=409, detail=conflict)
        await runtime.close()
        return _envelope(service.clear())

    return router


def build_runtime_router(*, runtime: LocalRuntimeCoordinator) -> APIRouter:
    """Expose local readiness without exposing ACP process details."""
    router = APIRouter(prefix="/local/runtime", include_in_schema=False)

    @router.get("")
    async def get_runtime(request: Request) -> dict[str, object]:
        require_loopback(request)
        return {
            "code": 0,
            "msg": "success",
            "data": asdict(runtime.status()),
        }

    @router.post("")
    async def start_runtime(request: Request) -> dict[str, object]:
        require_loopback(request)
        return {
            "code": 0,
            "msg": "success",
            "data": asdict(await runtime.start()),
        }

    return router


async def _select_and_activate_status(
    service: WorkspaceService,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard,
    path: str,
) -> WorkspaceStatus:
    """Persist a new folder only when its replacement ACP session is ready."""
    previous = service.status()
    conflict = switch_guard.check(
        previous, WorkspaceChange(operation="replace", path=path)
    )
    if conflict is not None:
        raise HTTPException(status_code=409, detail=conflict)
    try:
        selected = service.select(path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    readiness = await runtime.activate_workspace()
    if readiness.state == "ready":
        return selected

    service.restore(previous)
    raise HTTPException(
        status_code=503,
        detail=readiness.error or "The local Codex runtime is not ready.",
    )
