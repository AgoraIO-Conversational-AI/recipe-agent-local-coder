"""Loopback-only controls for seeding reproducible live validation state."""

from fastapi import APIRouter, Request
from pydantic import BaseModel

from acp_runtime.loopback import require_loopback

from .state import ValidationStateStore


class SeedPermissionRequest(BaseModel):
    session_id: str
    question: str
    operation: str


def build_admin_router(*, store: ValidationStateStore) -> APIRouter:
    router = APIRouter(prefix="/validation/admin", include_in_schema=False)

    @router.post("/permissions")
    async def seed_permission(
        payload: SeedPermissionRequest, request: Request
    ) -> dict[str, object]:
        require_loopback(request)
        pending = await store.seed_permission(
            session_id=payload.session_id,
            question=payload.question,
            operation=payload.operation,
        )
        return {
            "authorization_id": pending.authorization_id,
            "version": pending.version,
            "operation": pending.operation,
            "question": pending.question,
        }

    return router
