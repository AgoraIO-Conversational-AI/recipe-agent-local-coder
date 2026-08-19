"""Correlate one explicit voice decision to one current ACP operation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from acp_runtime.acp_client import (
    AcpPermissionOutcome,
    AcpPermissionRequest,
)

from .models import (
    PendingPermission,
    PermissionDecision,
    PermissionOption,
)
from .store import WorkStore


class PermissionBrokerError(RuntimeError):
    """A bounded permission state error suitable for a future tool response."""


@dataclass(frozen=True)
class PermissionResolution:
    authorization_id: str
    decision: PermissionDecision
    selected_option_id: str | None


@dataclass
class _PendingResolution:
    workspace_id: str
    permission: PendingPermission
    future: asyncio.Future[AcpPermissionOutcome]


class PermissionBroker:
    """Hold at most one Pending Permission until an explicit terminal event."""

    def __init__(self, store: WorkStore) -> None:
        self._store = store
        self._lock = asyncio.Lock()
        self._current: _PendingResolution | None = None

    def has_pending(self, workspace_id: str) -> bool:
        current = self._current
        return current is not None and current.workspace_id == workspace_id

    async def request(
        self,
        work_id: str,
        workspace_id: str,
        request: AcpPermissionRequest,
    ) -> AcpPermissionOutcome:
        receipt = self._store.get(work_id)
        if receipt.workspace_id != workspace_id:
            raise PermissionBrokerError("permission_authorization_mismatch")
        permission = PendingPermission(
            work_id=work_id,
            authorization_id=request.authorization_id,
            operation=request.operation,
            options=tuple(
                PermissionOption(
                    option_id=option.option_id,
                    name=option.name,
                    kind=option.kind,
                )
                for option in request.options
            ),
        )
        async with self._lock:
            if self._current is not None:
                raise PermissionBrokerError("permission_decision_required")
            future = asyncio.get_running_loop().create_future()
            self._store.save_permission(permission)
            current = _PendingResolution(
                workspace_id=workspace_id,
                permission=permission,
                future=future,
            )
            self._current = current
        try:
            return await future
        finally:
            async with self._lock:
                if self._current is current:
                    self._store.clear_permission(work_id)
                    self._current = None

    async def respond(
        self, workspace_id: str, decision: PermissionDecision
    ) -> PermissionResolution:
        if decision not in {"allow", "reject"}:
            raise ValueError("Permission decision must be allow or reject")
        async with self._lock:
            current = self._current
            if current is None or current.workspace_id != workspace_id:
                raise PermissionBrokerError("permission_not_found")
            expected_kind = "allow_once" if decision == "allow" else "reject_once"
            selected = next(
                (
                    option
                    for option in current.permission.options
                    if option.kind == expected_kind
                ),
                None,
            )
            outcome = AcpPermissionOutcome(
                option_id=selected.option_id if selected is not None else None
            )
            resolution = PermissionResolution(
                authorization_id=current.permission.authorization_id,
                decision=decision,
                selected_option_id=outcome.option_id,
            )
            self._finish_locked(current, outcome)
            return resolution

    async def cancel(self, work_id: str) -> bool:
        async with self._lock:
            current = self._current
            if current is None or current.permission.work_id != work_id:
                return False
            self._finish_locked(current, AcpPermissionOutcome(option_id=None))
            return True

    def _finish_locked(
        self,
        current: _PendingResolution,
        outcome: AcpPermissionOutcome,
    ) -> None:
        self._store.clear_permission(current.permission.work_id)
        self._current = None
        if not current.future.done():
            current.future.set_result(outcome)
