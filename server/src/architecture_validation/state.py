"""Small in-memory state fixture for architecture validation.

This store is intentionally not the production Task Runtime or Work Store.
"""

import asyncio
import secrets
import threading
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from typing import Optional

from .models import (
    PendingPermission,
    PermissionDecision,
    PermissionResolution,
    RuntimeSessionBinding,
    SyntheticWork,
    ToolObservation,
)


class CapabilityRegistry:
    """Map unguessable per-session capabilities to trusted local bindings."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._mcp: dict[str, RuntimeSessionBinding] = {}
        self._llm: dict[str, RuntimeSessionBinding] = {}

    def issue_sync(
        self, *, session_id: str, scenario_id: str, ttl_seconds: int = 3600
    ) -> RuntimeSessionBinding:
        if not session_id.strip() or not scenario_id.strip():
            raise ValueError("session_id and scenario_id are required")
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")

        binding = RuntimeSessionBinding(
            session_id=session_id,
            scenario_id=scenario_id,
            mcp_bearer=secrets.token_urlsafe(32),
            llm_callback_bearer=secrets.token_urlsafe(32),
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=ttl_seconds),
        )
        with self._lock:
            self.expire_session_sync(session_id)
            self._mcp[binding.mcp_bearer] = binding
            self._llm[binding.llm_callback_bearer] = binding
        return binding

    def resolve_mcp_sync(self, bearer: str) -> Optional[RuntimeSessionBinding]:
        with self._lock:
            return self._resolve(self._mcp, bearer)

    def resolve_llm_sync(self, bearer: str) -> Optional[RuntimeSessionBinding]:
        with self._lock:
            return self._resolve(self._llm, bearer)

    def _resolve(
        self, index: dict[str, RuntimeSessionBinding], bearer: str
    ) -> Optional[RuntimeSessionBinding]:
        binding = index.get(bearer)
        if binding is None:
            return None
        if binding.expires_at <= datetime.now(timezone.utc):
            self.expire_session_sync(binding.session_id)
            return None
        return binding

    def expire_session_sync(self, session_id: str) -> None:
        with self._lock:
            self._mcp = {
                token: binding
                for token, binding in self._mcp.items()
                if binding.session_id != session_id
            }
            self._llm = {
                token: binding
                for token, binding in self._llm.items()
                if binding.session_id != session_id
            }

    def set_scenario_sync(
        self, session_id: str, scenario_id: str
    ) -> RuntimeSessionBinding:
        with self._lock:
            binding = next(
                (
                    item
                    for item in self._mcp.values()
                    if item.session_id == session_id
                ),
                None,
            )
            if binding is None:
                raise KeyError("active session binding not found")
            updated = replace(binding, scenario_id=scenario_id)
            self._mcp[updated.mcp_bearer] = updated
            self._llm[updated.llm_callback_bearer] = updated
            return updated


class ValidationStateStore:
    """Hold the current validation permission independently for each session."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._permissions: dict[str, PendingPermission] = {}
        self._versions: dict[str, int] = {}
        self._works: dict[str, list[SyntheticWork]] = {}
        self._idempotency: dict[tuple[str, str], str] = {}
        self._observations: list[ToolObservation] = []

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

    async def accept_work(
        self, *, session_id: str, objective: str, idempotency_key: str
    ) -> tuple[str, Optional[SyntheticWork]]:
        async with self._lock:
            if session_id in self._permissions:
                return "permission_decision_required", None

            idempotency_identity = (session_id, idempotency_key)
            existing_id = self._idempotency.get(idempotency_identity)
            if existing_id is not None:
                existing = next(
                    work
                    for work in self._works.get(session_id, [])
                    if work.work_id == existing_id
                )
                return "work_already_accepted", existing

            work = SyntheticWork(
                work_id=f"work_{secrets.token_urlsafe(12)}",
                session_id=session_id,
                objective=objective[:512],
                idempotency_key=idempotency_key,
                state="accepted",
                created_at=datetime.now(timezone.utc),
            )
            self._works.setdefault(session_id, []).append(work)
            self._idempotency[idempotency_identity] = work.work_id
            return "work_accepted", work

    async def list_works(self, session_id: str) -> list[SyntheticWork]:
        async with self._lock:
            return list(self._works.get(session_id, []))

    async def find_work(
        self, *, session_id: str, work_id: Optional[str] = None
    ) -> Optional[SyntheticWork]:
        async with self._lock:
            works = self._works.get(session_id, [])
            if work_id is None:
                return works[-1] if works else None
            return next((work for work in works if work.work_id == work_id), None)

    async def cancel_work(
        self, *, session_id: str, work_id: Optional[str] = None
    ) -> Optional[SyntheticWork]:
        async with self._lock:
            works = self._works.get(session_id, [])
            target_index = next(
                (
                    index
                    for index in range(len(works) - 1, -1, -1)
                    if work_id is None or works[index].work_id == work_id
                ),
                None,
            )
            if target_index is None:
                return None
            cancelled = replace(works[target_index], state="cancelled")
            works[target_index] = cancelled
            return cancelled

    async def record_observation(self, observation: ToolObservation) -> None:
        async with self._lock:
            self._observations.append(observation)

    async def list_observations(self, session_id: str) -> list[ToolObservation]:
        async with self._lock:
            return [
                observation
                for observation in self._observations
                if observation.session_id == session_id
            ]

    async def reset_session(self, session_id: str) -> None:
        """Clear trial state while preserving monotonic permission versions."""
        async with self._lock:
            self._permissions.pop(session_id, None)
            self._works.pop(session_id, None)
            self._idempotency = {
                identity: work_id
                for identity, work_id in self._idempotency.items()
                if identity[0] != session_id
            }
            self._observations = [
                observation
                for observation in self._observations
                if observation.session_id != session_id
            ]

    async def rebind_session(self, old_session_id: str, new_session_id: str) -> None:
        """Move synthetic runtime state to a reconnected voice session."""
        if old_session_id == new_session_id:
            return
        async with self._lock:
            if new_session_id in self._permissions or new_session_id in self._works:
                raise ValueError("new session already has validation state")
            pending = self._permissions.pop(old_session_id, None)
            if pending is not None:
                self._permissions[new_session_id] = replace(
                    pending, session_id=new_session_id
                )
                self._versions[new_session_id] = max(
                    self._versions.get(new_session_id, 0), pending.version
                )
            works = self._works.pop(old_session_id, [])
            if works:
                self._works[new_session_id] = [
                    replace(work, session_id=new_session_id) for work in works
                ]
