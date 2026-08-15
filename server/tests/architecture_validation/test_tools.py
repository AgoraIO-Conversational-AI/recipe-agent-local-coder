"""Tests for the shared validation tool surface."""

import pytest

from architecture_validation.models import RuntimeSessionBinding
from architecture_validation.mcp_app import create_mcp_server
from architecture_validation.state import ValidationStateStore
from architecture_validation.tools import ValidationTools


@pytest.fixture
def store():
    return ValidationStateStore()


@pytest.fixture
def tools(store):
    return ValidationTools(store)


@pytest.fixture
def binding():
    return RuntimeSessionBinding.for_test(
        session_id="session-a", scenario_id="scenario-a"
    )


@pytest.mark.anyio
async def test_start_work_is_idempotent(tools, binding):
    first = await tools.start_work(
        binding=binding,
        objective="Add a health endpoint",
        idempotency_key="turn-1",
    )
    duplicate = await tools.start_work(
        binding=binding,
        objective="This different text must not replace the receipt",
        idempotency_key="turn-1",
    )

    assert first["code"] == "work_accepted"
    assert duplicate["code"] == "work_already_accepted"
    assert duplicate["work_id"] == first["work_id"]


@pytest.mark.anyio
async def test_start_work_is_blocked_while_permission_is_pending(
    store, tools, binding
):
    await store.seed_permission(
        session_id=binding.session_id,
        question="Allow tests?",
        operation="run_tests",
    )

    result = await tools.start_work(
        binding=binding,
        objective="Upgrade every dependency",
        idempotency_key="turn-2",
    )

    assert result == {"code": "permission_decision_required"}
    assert await store.list_works(binding.session_id) == []


@pytest.mark.anyio
async def test_status_defaults_to_current_work(tools, binding):
    accepted = await tools.start_work(
        binding=binding,
        objective="Add a health endpoint",
        idempotency_key="turn-1",
    )

    status = await tools.get_work_status(binding=binding)

    assert status["code"] == "work_found"
    assert status["work_id"] == accepted["work_id"]
    assert status["state"] == "accepted"


@pytest.mark.anyio
async def test_cancel_work_is_session_scoped(tools, binding):
    accepted = await tools.start_work(
        binding=binding,
        objective="Add a health endpoint",
        idempotency_key="turn-1",
    )
    other_binding = RuntimeSessionBinding.for_test(
        session_id="session-b", scenario_id="scenario-b"
    )

    wrong_session = await tools.cancel_work(
        binding=other_binding, work_id=accepted["work_id"]
    )
    cancelled = await tools.cancel_work(
        binding=binding, work_id=accepted["work_id"]
    )

    assert wrong_session == {"code": "work_not_found"}
    assert cancelled["code"] == "work_cancelled"


@pytest.mark.anyio
async def test_respond_permission_resolves_only_current_session(
    store, tools, binding
):
    pending = await store.seed_permission(
        session_id=binding.session_id,
        question="Allow tests?",
        operation="run_tests",
    )
    other_binding = RuntimeSessionBinding.for_test(
        session_id="session-b", scenario_id="scenario-b"
    )

    isolated = await tools.respond_permission(
        binding=other_binding, decision="allow"
    )
    resolved = await tools.respond_permission(binding=binding, decision="reject")

    assert isolated == {"code": "permission_not_found"}
    assert resolved == {
        "code": "permission_resolved",
        "authorization_id": pending.authorization_id,
        "version": pending.version,
        "decision": "reject",
    }


@pytest.mark.anyio
async def test_tools_record_bounded_observations(store, tools, binding):
    await tools.start_work(
        binding=binding,
        objective="A" * 5000,
        idempotency_key="turn-1",
    )

    observations = await store.list_observations(binding.session_id)

    assert len(observations) == 1
    assert observations[0].scenario_id == "scenario-a"
    assert len(observations[0].arguments["objective"]) == 512


@pytest.mark.anyio
async def test_invalid_permission_decision_is_rejected(tools, binding):
    with pytest.raises(ValueError, match="allow or reject"):
        await tools.respond_permission(binding=binding, decision="always")


@pytest.mark.anyio
async def test_mcp_exposes_exact_shared_tool_schemas(store):
    schemas = {
        tool.name: tool.inputSchema
        for tool in await create_mcp_server(store).list_tools()
    }

    assert set(schemas) == {
        "start_work",
        "get_work_status",
        "cancel_work",
        "respond_permission",
    }
    assert schemas["start_work"]["required"] == [
        "objective",
        "idempotency_key",
    ]
    assert schemas["respond_permission"]["properties"]["decision"]["enum"] == [
        "allow",
        "reject",
    ]
    assert "session_id" not in schemas["start_work"]["properties"]
