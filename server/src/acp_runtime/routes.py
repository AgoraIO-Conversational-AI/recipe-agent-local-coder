"""Loopback-only Project Folder configuration routes."""

from dataclasses import asdict

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from .loopback import require_loopback
from .picker import DirectoryPicker
from .workspace import WorkspaceService, WorkspaceStatus


class SelectWorkspaceRequest(BaseModel):
    path: str


def _envelope(status: WorkspaceStatus) -> dict[str, object]:
    return {
        "code": 0,
        "msg": "success",
        "data": asdict(status),
    }


def build_workspace_router(
    *, service: WorkspaceService, picker: DirectoryPicker
) -> APIRouter:
    router = APIRouter(prefix="/local/workspace", include_in_schema=False)

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
        try:
            return _envelope(service.select(selected))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.put("")
    async def select_workspace(
        payload: SelectWorkspaceRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        try:
            return _envelope(service.select(payload.path))
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @router.delete("")
    async def clear_workspace(request: Request) -> dict[str, object]:
        require_loopback(request)
        return _envelope(service.clear())

    return router
