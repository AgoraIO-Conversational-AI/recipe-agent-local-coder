"""Safe public MCP projections over the authoritative Task Runtime."""

from __future__ import annotations

import json
from typing import Protocol

from task_runtime.models import WorkReceipt
from task_runtime.permissions import PermissionBrokerError
from task_runtime.runtime import TaskRuntime, TaskRuntimeError
from task_runtime.store import WorkStore

from .models import CapabilityBinding


_PUBLIC_RUNTIME_ERRORS = {
    "invalid_work_request",
    "permission_decision_required",
    "permission_not_found",
    "permission_option_unavailable",
    "task_runtime_unavailable",
    "work_cancellation_failed",
    "work_not_cancellable",
    "work_not_found",
    "work_queue_budget_exceeded",
    "workspace_not_ready",
}
_PUBLIC_STATUS_BYTES = 256 * 1024
_TRUNCATION_SUFFIX = "\n\nResult shortened for voice status."


class WorkspaceGenerationPort(Protocol):
    def current_workspace_identity(self) -> tuple[str, int] | None:
        """Return the active stable Workspace and in-memory generation."""


class ManagedWorkTools:
    """Map authenticated MCP calls to safe Workspace-scoped Work operations."""

    def __init__(
        self,
        *,
        runtime: TaskRuntime,
        store: WorkStore,
        workspace_generation: WorkspaceGenerationPort,
    ) -> None:
        self._runtime = runtime
        self._store = store
        self._workspace_generation = workspace_generation

    async def start_work(
        self,
        *,
        binding: CapabilityBinding,
        objective: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        unavailable = self._authorize(binding, "start_work")
        if unavailable is not None:
            return unavailable
        try:
            existing = self._store.find_by_idempotency(
                binding.workspace_id, idempotency_key
            )
            receipt = await self._runtime.start_work(objective, idempotency_key)
        except (TaskRuntimeError, ValueError) as exc:
            return _public_error(exc)
        return {
            "code": "work_already_accepted" if existing is not None else "work_accepted",
            "work_id": receipt.work_id,
            "state": receipt.state,
        }

    async def get_work_status(
        self,
        *,
        binding: CapabilityBinding,
        work_id: str | None = None,
    ) -> dict[str, object]:
        unavailable = self._authorize(binding, "get_work_status")
        if unavailable is not None:
            return unavailable
        try:
            receipt = await self._runtime.get_work_status(work_id)
        except TaskRuntimeError as exc:
            return _public_error(exc)
        return self._status_projection(receipt)

    async def cancel_work(
        self,
        *,
        binding: CapabilityBinding,
        work_id: str | None = None,
    ) -> dict[str, object]:
        unavailable = self._authorize(binding, "cancel_work")
        if unavailable is not None:
            return unavailable
        try:
            receipt = await self._runtime.cancel_work(work_id)
        except TaskRuntimeError as exc:
            return _public_error(exc)
        code = "work_cancelled" if receipt.state == "cancelled" else "work_cancelling"
        return {"code": code, "work_id": receipt.work_id, "state": receipt.state}

    async def respond_permission(
        self,
        *,
        binding: CapabilityBinding,
        decision: str,
    ) -> dict[str, object]:
        unavailable = self._authorize(binding, "respond_permission")
        if unavailable is not None:
            return unavailable
        if decision not in {"allow", "reject"}:
            return {"code": "invalid_work_request"}
        try:
            await self._runtime.respond_permission(decision)
        except (PermissionBrokerError, TaskRuntimeError) as exc:
            return _public_error(exc)
        return {"code": "permission_resolved", "decision": decision}

    def _authorize(
        self, binding: CapabilityBinding, operation: str
    ) -> dict[str, object] | None:
        current = self._workspace_generation.current_workspace_identity()
        if current != (binding.workspace_id, binding.workspace_generation):
            return {"code": "runtime_unavailable", "retriable": True}
        return None

    def _status_projection(self, receipt: WorkReceipt) -> dict[str, object]:
        permission = self._store.pending_permission(receipt.workspace_id)
        if permission is not None and permission.work_id != receipt.work_id:
            permission = None
        presentation = receipt.final_presentation
        projection = {
            "code": "work_found",
            "work_id": receipt.work_id,
            "objective": receipt.objective,
            "state": receipt.state,
            "delivery_state": receipt.delivery_state,
            "final_presentation": (
                {
                    "speech": presentation.speech,
                    "inline": (
                        presentation.inline
                        if presentation.inline is not None
                        else None
                    ),
                }
                if presentation is not None
                else None
            ),
            "error": receipt.error,
            "pending_permission": (
                {"operation": permission.operation}
                if permission is not None
                else None
            ),
        }
        return _bounded_status(projection)


def _public_error(exc: Exception) -> dict[str, object]:
    code = str(exc)
    if code == "task_runtime_unavailable":
        return {"code": "runtime_unavailable", "retriable": True}
    if code in {"workspace_not_ready", "work_cancellation_failed"}:
        return {"code": "runtime_unavailable", "retriable": True}
    if code not in _PUBLIC_RUNTIME_ERRORS:
        return {"code": "runtime_unavailable", "retriable": True}
    return {"code": code}


def _serialized_size(value: dict[str, object]) -> int:
    return len(
        json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    )


def _bounded_status(projection: dict[str, object]) -> dict[str, object]:
    if _serialized_size(projection) <= _PUBLIC_STATUS_BYTES:
        return projection
    presentation = projection.get("final_presentation")
    if not isinstance(presentation, dict):
        return projection
    inline = presentation.get("inline")
    if not isinstance(inline, str):
        return projection
    presentation["inline"] = _TRUNCATION_SUFFIX
    encoded = inline.encode("utf-8")
    low = 0
    high = len(encoded)
    best = ""
    while low <= high:
        midpoint = (low + high) // 2
        candidate = encoded[:midpoint].decode("utf-8", errors="ignore").rstrip()
        presentation["inline"] = candidate + _TRUNCATION_SUFFIX
        if _serialized_size(projection) <= _PUBLIC_STATUS_BYTES:
            best = candidate
            low = midpoint + 1
        else:
            high = midpoint - 1
    presentation["inline"] = best + _TRUNCATION_SUFFIX
    return projection
