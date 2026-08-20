"""Safe public tool projections backed by the real Task Runtime."""

import asyncio
import json
from dataclasses import dataclass

import pytest

from acp_runtime.acp_client import (
    AcpPermissionOption,
    AcpPermissionRequest,
    AcpPromptResult,
    AcpSession,
)
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService
from managed_ingress.models import CapabilityBinding
from managed_ingress.tools import ManagedWorkTools
from task_runtime.permissions import PermissionBroker
from task_runtime.models import FinalPresentation, WorkReceipt
from task_runtime.runtime import TaskRuntime
from task_runtime.store import WorkStore


class FakeAcp:
    def __init__(self) -> None:
        self.responses: asyncio.Queue[AcpPromptResult] = asyncio.Queue()
        self.permission_request: AcpPermissionRequest | None = None
        self.permission_outcome = None

    async def open(self, primary_directory: str) -> AcpSession:
        return AcpSession(primary_directory)

    async def close(self) -> None:
        pass

    async def prompt(self, objective, observer) -> AcpPromptResult:
        del objective
        if self.permission_request is not None:
            self.permission_outcome = await observer.request_permission(
                self.permission_request
            )
            self.permission_request = None
        return await self.responses.get()

    async def cancel(self) -> None:
        self.responses.put_nowait(AcpPromptResult("cancelled", ""))


@dataclass
class FixedWorkspaceGeneration:
    workspace_id: str
    generation: int = 1

    def current_workspace_identity(self) -> tuple[str, int]:
        return self.workspace_id, self.generation


async def wait_until(predicate) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError("condition did not become true")


@pytest.fixture
async def tools_context(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    workspace = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    selected = workspace.select(str(project)).workspace
    acp = FakeAcp()
    readiness = LocalRuntimeCoordinator(workspace, acp)
    await readiness.start()
    store = WorkStore(tmp_path / "work.sqlite3")
    runtime = TaskRuntime(workspace, readiness, acp, store, PermissionBroker(store))
    await runtime.start()
    generation = FixedWorkspaceGeneration(selected.id)
    tools = ManagedWorkTools(
        runtime=runtime,
        store=store,
        workspace_generation=generation,
    )
    binding = CapabilityBinding(
        credential_id="credential-a",
        workspace_id=selected.id,
        workspace_generation=1,
        agora_agent_id="agent-a",
        issued_at=1.0,
    )
    yield tools, runtime, store, acp, generation, binding
    await runtime.close()
    await readiness.close()
    store.close()


@pytest.mark.anyio
async def test_start_and_status_return_safe_workspace_scoped_projections(tools_context):
    tools, _runtime, store, acp, _generation, binding = tools_context

    accepted = await tools.start_work(
        binding=binding,
        objective="Run tests",
        idempotency_key="turn-1",
    )
    duplicate = await tools.start_work(
        binding=binding,
        objective="Different body",
        idempotency_key="turn-1",
    )

    assert accepted["code"] == "work_accepted"
    assert accepted["state"] == "queued"
    assert duplicate == {
        "code": "work_already_accepted",
        "work_id": accepted["work_id"],
        "state": store.get(accepted["work_id"]).state,
    }
    assert store.get(accepted["work_id"]).delivery_agent_id == "agent-a"
    acp.responses.put_nowait(AcpPromptResult("end_turn", "All tests passed"))
    await wait_until(lambda: store.get(accepted["work_id"]).state == "completed")

    status = await tools.get_work_status(binding=binding, work_id=accepted["work_id"])
    assert status == {
        "code": "work_found",
        "work_id": accepted["work_id"],
        "objective": "Run tests",
        "state": "completed",
        "delivery_state": "pending_delivery",
        "final_presentation": {
            "speech": "All tests passed",
            "inline": "All tests passed",
        },
        "error": None,
        "pending_permission": None,
    }
    serialized = repr(status)
    for forbidden in (
        "workspace_id",
        "primary_directory",
        "authorization_id",
        "delivery_agent_id",
        "agent-a",
    ):
        assert forbidden not in serialized


@pytest.mark.anyio
async def test_stale_binding_and_missing_work_fail_closed(tools_context):
    tools, _runtime, store, _acp, generation, binding = tools_context
    generation.generation = 2

    stale = await tools.start_work(
        binding=binding,
        objective="Do not create",
        idempotency_key="turn-stale",
    )
    assert stale == {"code": "runtime_unavailable", "retriable": True}
    assert store.find_by_idempotency(binding.workspace_id, "turn-stale") is None

    generation.generation = 1
    assert await tools.get_work_status(binding=binding, work_id="missing") == {
        "code": "work_not_found"
    }


@pytest.mark.anyio
async def test_cancel_and_permission_errors_expose_no_internal_ids(tools_context):
    tools, _runtime, _store, _acp, _generation, binding = tools_context

    assert await tools.cancel_work(binding=binding, work_id="missing") == {
        "code": "work_not_found"
    }
    assert await tools.respond_permission(binding=binding, decision="allow") == {
        "code": "permission_not_found"
    }


@pytest.mark.anyio
async def test_serialized_status_is_bounded_to_256_kib(tools_context):
    tools, _runtime, _store, _acp, _generation, _binding = tools_context
    receipt = WorkReceipt(
        work_id="work-a",
        workspace_id="scope-a",
        idempotency_key="turn-a",
        objective="o" * (16 * 1024),
        state="completed",
        created_at="now",
        updated_at="now",
        final_presentation=FinalPresentation(
            speech="s" * (16 * 1024),
            inline="i" * (256 * 1024),
        ),
        delivery_state="pending_delivery",
    )

    projection = tools._status_projection(receipt)

    serialized = json.dumps(
        projection, ensure_ascii=False, separators=(",", ":")
    ).encode("utf-8")
    assert len(serialized) <= 256 * 1024
    assert projection["final_presentation"]["inline"].endswith(
        "Result shortened for voice status."
    )


@pytest.mark.anyio
async def test_permission_response_selects_once_without_exposing_correlation(
    tools_context,
):
    tools, _runtime, store, acp, _generation, binding = tools_context
    acp.permission_request = AcpPermissionRequest(
        authorization_id="private-auth-id",
        operation="Run project tests",
        options=(
            AcpPermissionOption("private-once-id", "Allow once", "allow_once"),
            AcpPermissionOption("private-always-id", "Always allow", "allow_always"),
        ),
    )
    accepted = await tools.start_work(
        binding=binding,
        objective="Run tests",
        idempotency_key="turn-permission",
    )
    await wait_until(
        lambda: store.get(accepted["work_id"]).state == "awaiting_permission"
    )

    status = await tools.get_work_status(
        binding=binding, work_id=accepted["work_id"]
    )
    response = await tools.respond_permission(binding=binding, decision="allow")

    assert status["pending_permission"] == {"operation": "Run project tests"}
    assert response == {"code": "permission_resolved", "decision": "allow"}
    assert "private" not in repr(response)
    await wait_until(lambda: acp.permission_outcome is not None)
    assert acp.permission_outcome.option_id == "private-once-id"
    acp.responses.put_nowait(AcpPromptResult("end_turn", "Tests passed"))
    await wait_until(lambda: store.get(accepted["work_id"]).state == "completed")
