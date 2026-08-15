"""Small in-memory state fixture for architecture validation.

This store is intentionally not the production Task Runtime or Work Store.
"""

import asyncio
import secrets
from datetime import datetime, timezone
from typing import Optional

from .models import (
    PendingPermission,
    PermissionDecision,
    PermissionResolution,
)


class ValidationStateStore:
    """Hold the current validation permission independently for each session."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._permissions: dict[str, PendingPermission] = {}
        self._versions: dict[str, int] = {}

    async def seed_permission(
        self, session_id: str, question: str, operation: str
    ) -> PendingPermission:
        if not session_id.strip():
            raise ValueError("session_id is required")
        if not question.strip():
            raise ValueError("question is required")
        if not operation.strip():
            raise ValueError("operation is required")

        async with self._lock:
            version = self._versions.get(session_id, 0) + 1
            permission = PendingPermission(
                session_id=session_id,
                authorization_id=secrets.token_urlsafe(24),
                version=version,
                operation=operation.strip(),
                question=question.strip(),
                created_at=datetime.now(timezone.utc),
            )
            self._versions[session_id] = version
            self._permissions[session_id] = permission
            return permission

    async def current_permission(
        self, session_id: str
    ) -> Optional[PendingPermission]:
        async with self._lock:
            return self._permissions.get(session_id)

    async def resolve_permission(
        self,
        *,
        session_id: str,
        authorization_id: str,
        version: int,
        decision: PermissionDecision,
    ) -> PermissionResolution:
        if decision not in ("allow", "reject"):
            raise ValueError("decision must be allow or reject")

        async with self._lock:
            pending = self._permissions.get(session_id)
            if pending is None:
                return PermissionResolution(code="permission_not_found")
            if pending.authorization_id != authorization_id:
                return PermissionResolution(code="permission_not_found")
            if pending.version != version:
                return PermissionResolution(
                    code="permission_stale",
                    authorization_id=pending.authorization_id,
                    version=pending.version,
                )

            del self._permissions[session_id]
            return PermissionResolution(
                code="permission_resolved",
                authorization_id=pending.authorization_id,
                version=pending.version,
                decision=decision,
            )
