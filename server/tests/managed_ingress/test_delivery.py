"""Active exact-session delivery of durable terminal Work results."""

import asyncio

import pytest

from managed_ingress.delivery import WorkDeliveryCoordinator
from task_runtime.models import FinalPresentation
from task_runtime.store import WorkStore


async def wait_until(predicate, message: str) -> None:
    for _ in range(500):
        if predicate():
            return
        await asyncio.sleep(0.002)
    raise AssertionError(message)


class FakeSessions:
    def __init__(self) -> None:
        self.active = {"agent-a"}
        self.availability: list[bool] = []
        self.has_checks = 0
        self.say_calls: list[tuple[str, str]] = []
        self.say_result = True
        self.say_error: Exception | None = None
        self.say_started = asyncio.Event()
        self.block_say = False

    def has_work_session(self, agent_id: str) -> bool:
        self.has_checks += 1
        if self.availability:
            return self.availability.pop(0)
        return agent_id in self.active

    async def say_work_result(self, agent_id: str, text: str) -> bool:
        self.say_calls.append((agent_id, text))
        self.say_started.set()
        if self.block_say:
            await asyncio.Event().wait()
        if self.say_error is not None:
            raise self.say_error
        return self.say_result


class FixedWorkspace:
    def __init__(self, workspace_id: str = "scope-a") -> None:
        self.workspace_id = workspace_id
        self.calls = 0

    def current_workspace_identity(self) -> tuple[str, int]:
        self.calls += 1
        return self.workspace_id, 1


@pytest.fixture
def store(tmp_path):
    work_store = WorkStore(tmp_path / "work.sqlite3")
    yield work_store
    work_store.close()


def completed_work(store: WorkStore, key: str = "turn-completed"):
    receipt, _ = store.create_or_get(
        "scope-a", key, "Run tests", delivery_agent_id="agent-a"
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(speech="Tests passed.", inline="Tests passed."),
    )
    return store.transition(receipt.work_id, "completed")


def failed_work(store: WorkStore):
    receipt, _ = store.create_or_get(
        "scope-a", "turn-failed", "Fail", delivery_agent_id="agent-a"
    )
    store.transition(receipt.work_id, "starting")
    return store.transition(receipt.work_id, "failed", "Safe failure")


@pytest.mark.anyio
async def test_completed_work_is_spoken_once_and_marked_accepted(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "accepted",
        "accepted delivery",
    )
    assert sessions.say_calls == [("agent-a", "Tests passed.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_failed_work_speaks_only_its_safe_stored_error(store):
    receipt = failed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "accepted",
        "accepted failure delivery",
    )
    assert sessions.say_calls == [("agent-a", "Safe failure")]
    await coordinator.close()


@pytest.mark.anyio
async def test_cancelled_work_is_never_spoken(store):
    receipt, _ = store.create_or_get(
        "scope-a", "turn-cancelled", "Cancel", delivery_agent_id="agent-a"
    )
    receipt = store.transition(receipt.work_id, "cancelled")
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "not_ready"
    await coordinator.close()


@pytest.mark.anyio
async def test_missing_session_leaves_delivery_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.active.clear()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: sessions.has_checks > 0, "session check")

    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_workspace_mismatch_leaves_delivery_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    workspace = FixedWorkspace("scope-b")
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=workspace
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: workspace.calls > 0, "workspace check")

    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_session_loss_after_claim_releases_delivery_to_pending(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.availability = [True, False]
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: sessions.has_checks == 2, "session revalidation")

    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()


@pytest.mark.anyio
async def test_session_unavailable_at_submission_releases_claim(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.say_result = False
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    await wait_until(lambda: len(sessions.say_calls) == 1, "submission attempt")
    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "pending_delivery",
        "released delivery",
    )

    assert sessions.say_calls == [("agent-a", "Tests passed.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_ambiguous_say_failure_becomes_unknown_without_retry(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.say_error = ConnectionError("network outcome unknown with SECRET")
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()

    coordinator.notify(receipt.work_id)
    coordinator.notify(receipt.work_id)

    await wait_until(
        lambda: store.get(receipt.work_id).delivery_state == "delivery_unknown",
        "unknown delivery",
    )
    assert sessions.say_calls == [("agent-a", "Tests passed.")]
    await coordinator.close()


@pytest.mark.anyio
async def test_close_marks_an_inflight_submission_unknown(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    sessions.block_say = True
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )
    await coordinator.start()
    coordinator.notify(receipt.work_id)
    await sessions.say_started.wait()

    await coordinator.close()

    assert store.get(receipt.work_id).delivery_state == "delivery_unknown"
    coordinator.notify(receipt.work_id)
    assert sessions.say_calls == [("agent-a", "Tests passed.")]


@pytest.mark.anyio
async def test_notification_before_start_does_not_replay(store):
    receipt = completed_work(store)
    sessions = FakeSessions()
    coordinator = WorkDeliveryCoordinator(
        store=store, sessions=sessions, workspace=FixedWorkspace()
    )

    coordinator.notify(receipt.work_id)
    await coordinator.start()
    await asyncio.sleep(0)

    assert sessions.say_calls == []
    assert store.get(receipt.work_id).delivery_state == "pending_delivery"
    await coordinator.close()
