"""Loopback-only Project Folder configuration routes."""

from dataclasses import asdict
from dataclasses import dataclass
from typing import Literal, Protocol

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

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


def _envelope(status: WorkspaceStatus) -> dict[str, object]:
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

    @router.get("")
    async def get_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(service.status())

    @router.post("/browse")
    async def browse_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        selected = await picker.pick()
        if selected is None:
            raise HTTPException(
                status_code=409,
                detail="Project Folder selection was cancelled",
            )
        return await _select_and_activate(service, runtime, resolved_guard, selected)

    @router.put("")
    async def select_workspace(
        payload: SelectWorkspaceRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        return await _select_and_activate(service, runtime, resolved_guard, payload.path)

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


async def _select_and_activate(
    service: WorkspaceService,
    runtime: LocalRuntimeCoordinator,
    switch_guard: WorkspaceSwitchGuard,
    path: str,
) -> dict[str, object]:
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
        return _envelope(selected)

    service.restore(previous)
    raise HTTPException(
        status_code=503,
        detail=readiness.error or "The local Codex runtime is not ready.",
    )
