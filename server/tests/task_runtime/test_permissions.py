"""Current-operation permission behavior through the broker boundary."""

import asyncio

import pytest

from acp_runtime.acp_client import AcpPermissionOption, AcpPermissionRequest
from task_runtime.permissions import PermissionBroker, PermissionBrokerError
from task_runtime.store import WorkStore


@pytest.fixture
def permission_context(tmp_path):
    store = WorkStore(tmp_path / "work.sqlite3")
    receipt, _ = store.create_or_get("scope-a", "turn-a", "Update the project")
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    broker = PermissionBroker(store)
    yield store, receipt, broker
    store.close()


async def wait_for_pending(broker: PermissionBroker, workspace_id: str) -> None:
    for _ in range(100):
        if broker.has_pending(workspace_id):
            return
        await asyncio.sleep(0.001)
    raise AssertionError("Permission did not become pending")


def request_with_options(*options: AcpPermissionOption) -> AcpPermissionRequest:
    return AcpPermissionRequest(
        authorization_id="auth-a",
        operation="Run a command",
        options=tuple(options),
    )


@pytest.mark.anyio
async def test_allow_selects_only_allow_once(permission_context):
    store, receipt, broker = permission_context
    pending = asyncio.create_task(
        broker.request(
            receipt.work_id,
            receipt.workspace_id,
            request_with_options(
                AcpPermissionOption("always", "Always allow", "allow_always"),
                AcpPermissionOption("once", "Allow once", "allow_once"),
            ),
        )
    )
    await wait_for_pending(broker, "scope-a")

    resolution = await broker.respond("scope-a", "allow")

    assert resolution.authorization_id == "auth-a"
    assert resolution.selected_option_id == "once"
    assert (await pending).option_id == "once"
    assert store.pending_permission("scope-a") is None


@pytest.mark.anyio
async def test_reject_without_reject_once_returns_cancelled(permission_context):
    _store, receipt, broker = permission_context
    pending = asyncio.create_task(
        broker.request(
            receipt.work_id,
            receipt.workspace_id,
            request_with_options(
                AcpPermissionOption(
                    "reject-always", "Always reject", "reject_always"
                )
            ),
        )
    )
    await wait_for_pending(broker, "scope-a")

    resolution = await broker.respond("scope-a", "reject")

    assert resolution.selected_option_id is None
    assert (await pending).option_id is None


@pytest.mark.anyio
async def test_pending_permission_has_no_ttl_and_blocks_a_second_request(
    permission_context,
):
    _store, receipt, broker = permission_context
    pending = asyncio.create_task(
        broker.request(
            receipt.work_id,
            receipt.workspace_id,
            request_with_options(
                AcpPermissionOption("once", "Allow once", "allow_once")
            ),
        )
    )
    await wait_for_pending(broker, "scope-a")
    await asyncio.sleep(0.02)

    assert broker.has_pending("scope-a") is True
    with pytest.raises(PermissionBrokerError, match="permission_decision_required"):
        await broker.request(
            receipt.work_id,
            receipt.workspace_id,
            request_with_options(
                AcpPermissionOption("once-2", "Allow once", "allow_once")
            ),
        )

    await broker.cancel(receipt.work_id)
    assert (await pending).option_id is None


@pytest.mark.anyio
async def test_response_is_scoped_and_cancellation_resolves_exactly_once(
    permission_context,
):
    store, receipt, broker = permission_context
    pending = asyncio.create_task(
        broker.request(
            receipt.work_id,
            receipt.workspace_id,
            request_with_options(
                AcpPermissionOption("once", "Allow once", "allow_once")
            ),
        )
    )
    await wait_for_pending(broker, "scope-a")

    with pytest.raises(PermissionBrokerError, match="permission_not_found"):
        await broker.respond("scope-b", "allow")

    assert await broker.cancel(receipt.work_id) is True
    assert await broker.cancel(receipt.work_id) is False
    assert (await pending).option_id is None
    assert broker.has_pending("scope-a") is False
    assert store.pending_permission("scope-a") is None
