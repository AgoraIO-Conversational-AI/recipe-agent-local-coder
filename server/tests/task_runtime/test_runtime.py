"""Serial background Work execution through the TaskRuntime boundary."""

import asyncio
from types import SimpleNamespace

import pytest

from acp_runtime.acp_client import (
    AcpPermissionOption,
    AcpPermissionRequest,
    AcpPromptResult,
    AcpSession,
    AcpSessionEvent,
)
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService
from task_runtime.permissions import PermissionBroker
from task_runtime.runtime import (
    TaskRuntime,
    TaskRuntimeError,
    TaskRuntimeWorkspaceSwitchGuard,
)
from task_runtime.store import WorkStore


class FakeExecutionAcp:
    def __init__(self) -> None:
        self.opened: list[str] = []
        self.close_calls = 0
        self.objectives: list[str] = []
        self.active_prompts = 0
        self.max_active_prompts = 0
        self.cancel_calls = 0
        self.responses: asyncio.Queue[AcpPromptResult] = asyncio.Queue()
        self.cancel_event = asyncio.Event()
        self.permission_request: AcpPermissionRequest | None = None
        self.permission_outcomes = []
        self.fail_next_prompt: Exception | None = None

    async def open(self, primary_directory: str) -> AcpSession:
        self.opened.append(primary_directory)
        return AcpSession(primary_directory=primary_directory)

    async def close(self) -> None:
        self.close_calls += 1

    async def prompt(self, objective: str, observer) -> AcpPromptResult:
        self.objectives.append(objective)
        self.active_prompts += 1
        self.max_active_prompts = max(self.max_active_prompts, self.active_prompts)
        try:
            await observer.on_event(
                AcpSessionEvent(kind="execute", label="Running command")
            )
            if self.fail_next_prompt is not None:
                failure = self.fail_next_prompt
                self.fail_next_prompt = None
                raise failure
            if self.permission_request is not None:
                outcome = await observer.request_permission(self.permission_request)
                self.permission_outcomes.append(outcome)
                self.permission_request = None
            response = asyncio.create_task(self.responses.get())
            cancelled = asyncio.create_task(self.cancel_event.wait())
            done, pending = await asyncio.wait(
                {response, cancelled}, return_when=asyncio.FIRST_COMPLETED
            )
            for task in pending:
                task.cancel()
            if cancelled in done:
                self.cancel_event.clear()
                return AcpPromptResult(stop_reason="cancelled", final_text="")
            return response.result()
        finally:
            self.active_prompts -= 1

    async def cancel(self) -> None:
        self.cancel_calls += 1
        self.cancel_event.set()

    def complete(self, text: str) -> None:
        self.responses.put_nowait(
            AcpPromptResult(stop_reason="end_turn", final_text=text)
        )


async def wait_until(predicate, message: str) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError(message)


@pytest.fixture
async def runtime_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    selected = workspace.select(str(project))
    acp = FakeExecutionAcp()
    readiness = LocalRuntimeCoordinator(workspace, acp)
    await readiness.start()
    store = WorkStore(tmp_path / "work.sqlite3")
    permissions = PermissionBroker(store)
    runtime = TaskRuntime(workspace, readiness, acp, store, permissions)
    await runtime.start()
    yield SimpleNamespace(
        project=project,
        workspace=workspace,
        selected=selected,
        acp=acp,
        readiness=readiness,
        store=store,
        permissions=permissions,
        runtime=runtime,
    )
    await runtime.close()
    await readiness.close()
    store.close()


@pytest.mark.anyio
async def test_start_work_returns_after_persistence_and_completes_in_background(
    runtime_context,
):
    context = runtime_context

    accepted = await context.runtime.start_work("Run the tests", "turn-1")

    assert accepted.state == "queued"
    assert context.store.get(accepted.work_id).state == "queued"
    assert context.acp.objectives == []

    await wait_until(lambda: context.acp.objectives == ["Run the tests"], "prompt")
    context.acp.complete("All tests passed.")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "completed",
        "completion",
    )
    completed = context.store.get(accepted.work_id)

    assert completed.final_presentation is not None
    assert completed.final_presentation.speech == "All tests passed."
    assert completed.final_presentation.inline == "All tests passed."


@pytest.mark.anyio
async def test_queue_has_no_small_count_cap_and_executes_fifo_without_concurrency(
    runtime_context,
):
    context = runtime_context
    accepted = [
        await context.runtime.start_work(f"Work {index}", f"turn-{index}")
        for index in range(6)
    ]
    duplicate = await context.runtime.start_work("Different body", "turn-5")

    assert duplicate.work_id == accepted[5].work_id
    assert context.runtime.queue_depth() >= 5
    for index in range(6):
        await wait_until(
            lambda index=index: len(context.acp.objectives) == index + 1,
            f"prompt {index}",
        )
        assert context.acp.objectives[index] == f"Work {index}"
        context.acp.complete(f"Completed {index}")

    await wait_until(
        lambda: all(
            context.store.get(receipt.work_id).state == "completed"
            for receipt in accepted
        ),
        "all completions",
    )
    assert context.acp.max_active_prompts == 1
    assert len(context.acp.opened) == 1


@pytest.mark.anyio
async def test_queue_byte_budget_rejects_only_new_work(runtime_context):
    context = runtime_context
    context.runtime.max_queued_objective_bytes = 8
    context.acp.permission_request = AcpPermissionRequest(
        authorization_id="auth-a",
        operation="Run a command",
        options=(AcpPermissionOption("once", "Allow once", "allow_once"),),
    )
    accepted = await context.runtime.start_work("12345678", "turn-1")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "awaiting_permission",
        "pending permission",
    )

    duplicate = await context.runtime.start_work("different", "turn-1")
    assert duplicate.work_id == accepted.work_id
    with pytest.raises(TaskRuntimeError, match="permission_decision_required"):
        await context.runtime.start_work("x", "turn-2")

    await context.runtime.respond_permission("reject")
    context.acp.complete("Permission rejected")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "completed",
        "completion",
    )

    blocker = await context.runtime.start_work("block", "turn-blocker")
    await wait_until(
        lambda: context.store.get(blocker.work_id).state == "running",
        "blocking work",
    )
    queued = await context.runtime.start_work("12345678", "turn-3")
    with pytest.raises(TaskRuntimeError, match="work_queue_budget_exceeded"):
        await context.runtime.start_work("x", "turn-4")
    assert context.store.find_by_idempotency("scope-a", "turn-4") is None
    await context.runtime.cancel_work(queued.work_id)
    await context.runtime.cancel_work(blocker.work_id)


@pytest.mark.anyio
async def test_permission_gate_blocks_new_work_but_allows_explicit_response(
    runtime_context,
):
    context = runtime_context
    context.acp.permission_request = AcpPermissionRequest(
        authorization_id="auth-a",
        operation="Run a command",
        options=(
            AcpPermissionOption("once", "Allow once", "allow_once"),
            AcpPermissionOption("always", "Always allow", "allow_always"),
        ),
    )
    accepted = await context.runtime.start_work("Update the project", "turn-1")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "awaiting_permission",
        "pending permission",
    )

    with pytest.raises(TaskRuntimeError, match="permission_decision_required"):
        await context.runtime.start_work("Run another task", "turn-2")

    resolution = await context.runtime.respond_permission("allow")
    context.acp.complete("Project updated.")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "completed",
        "permission completion",
    )

    assert resolution.selected_option_id == "once"
    assert context.acp.permission_outcomes[0].option_id == "once"


@pytest.mark.anyio
async def test_queued_and_running_cancellation_are_confirmed(runtime_context):
    context = runtime_context
    running = await context.runtime.start_work("Long task", "turn-1")
    queued = await context.runtime.start_work("Queued task", "turn-2")
    await wait_until(
        lambda: context.store.get(running.work_id).state == "running", "running"
    )

    queued_result = await context.runtime.cancel_work(queued.work_id)
    running_result = await context.runtime.cancel_work(running.work_id)

    assert queued_result.state == "cancelled"
    assert running_result.state == "cancelling"
    await wait_until(
        lambda: context.store.get(running.work_id).state == "cancelled",
        "confirmed cancellation",
    )
    assert context.acp.cancel_calls == 1


@pytest.mark.anyio
async def test_cancelling_pending_permission_never_grants_it(runtime_context):
    context = runtime_context
    context.acp.permission_request = AcpPermissionRequest(
        authorization_id="auth-a",
        operation="Run a command",
        options=(AcpPermissionOption("once", "Allow once", "allow_once"),),
    )
    accepted = await context.runtime.start_work("Update the project", "turn-1")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "awaiting_permission",
        "pending permission",
    )

    await context.runtime.cancel_work(accepted.work_id)
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "cancelled",
        "cancelled permission",
    )

    assert context.acp.permission_outcomes[0].option_id is None
    assert context.permissions.has_pending("scope-a") is False


@pytest.mark.anyio
async def test_acp_failure_is_bounded_and_unready_runtime_rejects_acceptance(
    runtime_context,
):
    context = runtime_context
    accepted = await context.runtime.start_work("Unsafe raw failure", "turn-1")
    context.acp.responses.put_nowait(
        AcpPromptResult(stop_reason="refusal", final_text="SECRET raw failure")
    )
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "failed", "failed"
    )

    failed = context.store.get(accepted.work_id)
    assert failed.error == "The coding Agent could not complete this Work."
    assert "SECRET" not in failed.error

    await context.readiness.close()
    with pytest.raises(TaskRuntimeError, match="workspace_not_ready"):
        await context.runtime.start_work("Another task", "turn-2")


@pytest.mark.anyio
async def test_acp_process_failure_reopens_only_for_subsequent_work(runtime_context):
    context = runtime_context
    context.acp.fail_next_prompt = ConnectionError("child exited with SECRET")
    failed = await context.runtime.start_work("First task", "turn-1")
    following = await context.runtime.start_work("Second task", "turn-2")

    await wait_until(
        lambda: context.store.get(failed.work_id).state == "failed",
        "first failure",
    )
    await wait_until(
        lambda: context.acp.objectives == ["First task", "Second task"],
        "subsequent prompt",
    )
    context.acp.complete("Second task completed")
    await wait_until(
        lambda: context.store.get(following.work_id).state == "completed",
        "subsequent completion",
    )

    assert context.acp.close_calls >= 1
    assert len(context.acp.opened) == 2


@pytest.mark.anyio
async def test_runtime_rejects_unready_workspace_and_guard_blocks_active_switch(
    runtime_context,
):
    context = runtime_context
    guard = TaskRuntimeWorkspaceSwitchGuard(context.store, context.permissions)
    accepted = await context.runtime.start_work("Long task", "turn-1")
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "running", "running"
    )

    reason = guard.check(
        context.workspace.status(), SimpleNamespace(operation="replace")
    )
    assert reason == (
        "Wait for the current Work or permission decision before changing "
        "Project Folder."
    )

    await context.runtime.cancel_work(accepted.work_id)
    await wait_until(
        lambda: context.store.get(accepted.work_id).state == "cancelled", "cancelled"
    )
    assert guard.check(
        context.workspace.status(), SimpleNamespace(operation="replace")
    ) is None


@pytest.mark.anyio
async def test_start_recovers_nonterminal_receipts_as_failed(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    workspace.select(str(project))
    acp = FakeExecutionAcp()
    readiness = LocalRuntimeCoordinator(workspace, acp)
    await readiness.start()
    store = WorkStore(tmp_path / "work.sqlite3")
    receipt, _ = store.create_or_get("scope-old", "turn-old", "Old work")
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    runtime = TaskRuntime(workspace, readiness, acp, store, PermissionBroker(store))

    await runtime.start()

    recovered = store.get(receipt.work_id)
    assert recovered.state == "failed"
    assert recovered.error == "Local Runner restarted before Work completed."
    await runtime.close()
    await readiness.close()
    store.close()
