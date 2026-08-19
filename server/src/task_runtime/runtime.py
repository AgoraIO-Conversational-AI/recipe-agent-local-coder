"""Durable FIFO coordination of background Work through one ACP session."""

from __future__ import annotations

import asyncio
from contextlib import suppress
from typing import Any

from acp_runtime.acp_client import (
    AcpClientPort,
    AcpPermissionOutcome,
    AcpPermissionRequest,
    AcpPromptObserver,
    AcpPromptResult,
    AcpSessionEvent,
)
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.workspace import WorkspaceService, WorkspaceStatus

from .models import (
    NONTERMINAL_STATES,
    TERMINAL_STATES,
    FinalPresentation,
    PermissionDecision,
    WorkReceipt,
)
from .permissions import PermissionBroker, PermissionResolution
from .store import WorkStore


_RESTART_ERROR = "Local Runner restarted before Work completed."
_STOPPED_ERROR = "Local Runner stopped before Work completed."
_WORK_ERROR = "The coding Agent could not complete this Work."
_SWITCH_CONFLICT = (
    "Wait for the current Work or permission decision before changing Project Folder."
)
MAX_QUEUED_OBJECTIVE_BYTES = 1024 * 1024


class TaskRuntimeError(RuntimeError):
    """A bounded Work state error suitable for a future MCP response."""


class TaskRuntimeWorkspaceSwitchGuard:
    """Prevent Workspace mutation while durable Work remains nonterminal."""

    def __init__(self, store: WorkStore, permissions: PermissionBroker) -> None:
        self._store = store
        self._permissions = permissions

    def check(self, previous: WorkspaceStatus, change: Any) -> str | None:
        del change
        if previous.workspace is None:
            return None
        workspace_id = previous.workspace.id
        if self._store.has_nonterminal(workspace_id) or self._permissions.has_pending(
            workspace_id
        ):
            return _SWITCH_CONFLICT
        return None


class _WorkObserver(AcpPromptObserver):
    def __init__(self, runtime: TaskRuntime, receipt: WorkReceipt) -> None:
        self._runtime = runtime
        self._receipt = receipt

    async def on_event(self, event: AcpSessionEvent) -> None:
        self._runtime.store.append_activity(
            self._receipt.work_id,
            event.kind,
            event.label,
        )

    async def request_permission(
        self, request: AcpPermissionRequest
    ) -> AcpPermissionOutcome:
        current = self._runtime.store.get(self._receipt.work_id)
        if current.state != "running":
            return AcpPermissionOutcome(option_id=None)
        self._runtime.store.transition(current.work_id, "awaiting_permission")
        try:
            return await self._runtime.permissions.request(
                current.work_id,
                current.workspace_id,
                request,
            )
        finally:
            latest = self._runtime.store.get(current.work_id)
            if latest.state == "awaiting_permission":
                self._runtime.store.transition(latest.work_id, "running")


class TaskRuntime:
    """Accept durable Work immediately and execute one ACP prompt at a time."""

    def __init__(
        self,
        workspace: WorkspaceService,
        readiness: LocalRuntimeCoordinator,
        acp_client: AcpClientPort,
        store: WorkStore,
        permissions: PermissionBroker,
        max_queued_objective_bytes: int = MAX_QUEUED_OBJECTIVE_BYTES,
    ) -> None:
        self._workspace = workspace
        self._readiness = readiness
        self._acp = acp_client
        self.store = store
        self.permissions = permissions
        self.max_queued_objective_bytes = max_queued_objective_bytes
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._worker: asyncio.Task[None] | None = None
        self._accepting = False
        self._active_work_id: str | None = None

    async def start(self) -> None:
        """Recover interrupted receipts and start one idle FIFO worker."""
        if self._worker is not None:
            return
        self.store.recover_nonterminal(_RESTART_ERROR)
        self._accepting = True
        self._worker = asyncio.create_task(self._run(), name="voice-acp-task-runtime")

    async def close(self) -> None:
        """Stop acceptance and leave no durable Work in an active state."""
        self._accepting = False
        worker = self._worker
        if worker is None:
            self.store.recover_nonterminal(_STOPPED_ERROR)
            return
        active_work_id = self._active_work_id
        if active_work_id is not None:
            with suppress(KeyError):
                active = self.store.get(active_work_id)
                if active.state in {"running", "awaiting_permission"}:
                    self.store.transition(active.work_id, "cancelling")
                    await self.permissions.cancel(active.work_id)
                    with suppress(Exception):
                        await self._acp.cancel()
            try:
                await asyncio.wait_for(
                    self._wait_for_active_terminal(active_work_id), timeout=2
                )
            except TimeoutError:
                pass
        worker.cancel()
        with suppress(asyncio.CancelledError):
            await worker
        self._worker = None
        self._active_work_id = None
        self.store.recover_nonterminal(_STOPPED_ERROR)

    async def start_work(
        self, objective: str, idempotency_key: str
    ) -> WorkReceipt:
        """Persist and enqueue one Work without awaiting ACP execution."""
        if not self._accepting:
            raise TaskRuntimeError("task_runtime_unavailable")
        workspace_id = self._ready_workspace_id()
        try:
            existing = self.store.find_by_idempotency(
                workspace_id, idempotency_key
            )
        except ValueError as exc:
            raise TaskRuntimeError("invalid_work_request") from exc
        if existing is not None:
            return existing
        if self.permissions.has_pending(workspace_id):
            raise TaskRuntimeError("permission_decision_required")
        normalized_objective_bytes = len(
            " ".join(objective.split()).encode("utf-8")
        )
        if (
            self.store.queued_objective_bytes(workspace_id)
            + normalized_objective_bytes
            > self.max_queued_objective_bytes
        ):
            raise TaskRuntimeError("work_queue_budget_exceeded")
        try:
            receipt, created = self.store.create_or_get(
                workspace_id,
                idempotency_key,
                objective,
            )
        except ValueError as exc:
            raise TaskRuntimeError("invalid_work_request") from exc
        if created:
            self._queue.put_nowait(receipt.work_id)
        return receipt

    async def get_work_status(self, work_id: str | None = None) -> WorkReceipt:
        workspace_id = self._selected_workspace_id()
        try:
            return self.store.resolve(workspace_id, work_id)
        except KeyError as exc:
            raise TaskRuntimeError("work_not_found") from exc

    async def cancel_work(self, work_id: str | None = None) -> WorkReceipt:
        receipt = await self.get_work_status(work_id)
        if receipt.state in TERMINAL_STATES or receipt.state == "cancelling":
            return receipt
        if receipt.state == "queued":
            return self.store.transition(receipt.work_id, "cancelled")
        if receipt.state not in {"running", "awaiting_permission"}:
            raise TaskRuntimeError("work_not_cancellable")
        cancelling = self.store.transition(receipt.work_id, "cancelling")
        await self.permissions.cancel(receipt.work_id)
        if self._active_work_id == receipt.work_id:
            try:
                await self._acp.cancel()
            except Exception as exc:
                self.store.transition(receipt.work_id, "failed", _WORK_ERROR)
                raise TaskRuntimeError("work_cancellation_failed") from exc
        return cancelling

    async def respond_permission(
        self, decision: PermissionDecision
    ) -> PermissionResolution:
        return await self.permissions.respond(self._selected_workspace_id(), decision)

    def queue_depth(self) -> int:
        return self.store.queue_depth(self._selected_workspace_id())

    async def _run(self) -> None:
        while True:
            work_id = await self._queue.get()
            try:
                receipt = self.store.get(work_id)
                if receipt.state == "queued":
                    await self._execute(receipt)
            finally:
                self._queue.task_done()

    async def _execute(self, receipt: WorkReceipt) -> None:
        self._active_work_id = receipt.work_id
        try:
            self.store.transition(receipt.work_id, "starting")
            readiness = await self._readiness.start()
            if readiness.state != "ready":
                raise TaskRuntimeError("workspace_not_ready")
            running = self.store.transition(receipt.work_id, "running")
            result = await self._acp.prompt(
                running.objective,
                _WorkObserver(self, running),
            )
            self._finish_prompt(running.work_id, result)
        except asyncio.CancelledError:
            raise
        except Exception:
            self._fail_work(receipt.work_id)
            with suppress(Exception):
                await self._readiness.close()
        finally:
            self._active_work_id = None

    def _finish_prompt(self, work_id: str, result: AcpPromptResult) -> None:
        current = self.store.get(work_id)
        if result.stop_reason == "cancelled":
            if current.state in {"running", "awaiting_permission"}:
                current = self.store.transition(current.work_id, "cancelling")
            if current.state == "cancelling":
                self.store.transition(current.work_id, "cancelled")
            else:
                self._fail_work(current.work_id)
            return
        if current.state == "cancelling":
            self.store.transition(current.work_id, "failed", _WORK_ERROR)
            return
        if result.stop_reason != "end_turn" or not result.final_text.strip():
            self._fail_work(current.work_id)
            return
        presentation = FinalPresentation(
            speech=_speech_from_result(result.final_text),
            inline=result.final_text,
        )
        self.store.save_final(current.work_id, presentation)
        self.store.transition(current.work_id, "completed")

    def _fail_work(self, work_id: str) -> None:
        current = self.store.get(work_id)
        if current.state in TERMINAL_STATES:
            return
        if current.state == "queued":
            current = self.store.transition(current.work_id, "starting")
        if current.state == "awaiting_permission":
            current = self.store.transition(current.work_id, "cancelling")
        if current.state in {"starting", "running", "cancelling"}:
            self.store.transition(current.work_id, "failed", _WORK_ERROR)

    async def _wait_for_active_terminal(self, work_id: str) -> None:
        while self.store.get(work_id).state in NONTERMINAL_STATES:
            await asyncio.sleep(0.01)

    def _ready_workspace_id(self) -> str:
        status = self._readiness.status()
        if (
            status.state != "ready"
            or status.workspace.workspace is None
            or status.workspace.state != "ready"
        ):
            raise TaskRuntimeError("workspace_not_ready")
        return status.workspace.workspace.id

    def _selected_workspace_id(self) -> str:
        status = self._workspace.status()
        if status.workspace is None or status.state != "ready":
            raise TaskRuntimeError("workspace_not_ready")
        return status.workspace.id


def _speech_from_result(value: str) -> str:
    normalized = value.replace("\x00", "").strip()
    encoded = normalized.encode("utf-8")
    if len(encoded) <= 16 * 1024:
        return normalized
    return encoded[: 16 * 1024].decode("utf-8", errors="ignore").rstrip()
