"""Tests for the SDK-backed Managed dynamic-context adapter."""

import pytest

from architecture_validation.managed import ManagedContextSynchronizer
from architecture_validation.state import ValidationStateStore


class FakeSession:
    def __init__(self):
        self.updates = []
        self.speech = []
        self.update_error = None

    async def update(self, properties):
        if self.update_error:
            raise self.update_error
        self.updates.append(properties)

    async def say(self, text, priority=None, interruptable=None):
        self.speech.append(
            {
                "text": text,
                "priority": priority,
                "interruptable": interruptable,
            }
        )


@pytest.fixture
def store():
    return ValidationStateStore()


@pytest.fixture
def base_messages():
    return [{"role": "system", "content": "Base routing instructions."}]


@pytest.mark.anyio
async def test_pending_permission_replaces_complete_system_messages(
    store, base_messages
):
    session = FakeSession()
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)

    applied = await synchronizer.on_permission_changed(
        session_id="session-a", session=session
    )

    assert applied == pending.version
    assert session.updates[0]["llm"]["system_messages"][0] == base_messages[0]
    assert len(session.updates[0]["llm"]["system_messages"]) == 2
    assert "params" not in session.updates[0]["llm"]


@pytest.mark.anyio
async def test_resolved_permission_clears_dynamic_message(store, base_messages):
    session = FakeSession()
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)
    await synchronizer.on_permission_changed(session_id="session-a", session=session)
    await store.resolve_permission(
        session_id="session-a",
        authorization_id=pending.authorization_id,
        version=pending.version,
        decision="reject",
    )

    applied = await synchronizer.on_permission_changed(
        session_id="session-a", session=session
    )

    assert applied is None
    assert session.updates[-1] == {"llm": {"system_messages": base_messages}}


@pytest.mark.anyio
async def test_permission_question_uses_one_append_speech_call(store, base_messages):
    session = FakeSession()
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)

    await synchronizer.announce_permission(session=session, pending=pending)

    assert session.speech == [
        {
            "text": "Permission required: Allow running tests?",
            "priority": "APPEND",
            "interruptable": True,
        }
    ]


@pytest.mark.anyio
async def test_permission_speech_is_capped_at_512_utf8_bytes(store, base_messages):
    session = FakeSession()
    pending = await store.seed_permission(
        session_id="session-a",
        question="🙂" * 1000,
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)

    await synchronizer.announce_permission(session=session, pending=pending)

    assert len(session.speech[0]["text"].encode("utf-8")) <= 512


@pytest.mark.anyio
async def test_failed_update_propagates_and_is_not_marked_applied(store, base_messages):
    session = FakeSession()
    session.update_error = RuntimeError("update failed")
    await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)

    with pytest.raises(RuntimeError, match="update failed"):
        await synchronizer.on_permission_changed(
            session_id="session-a", session=session
        )

    assert synchronizer.applied_version("session-a") is None


@pytest.mark.anyio
async def test_repeated_same_version_does_not_send_duplicate_update(store, base_messages):
    session = FakeSession()
    await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    synchronizer = ManagedContextSynchronizer(store, base_messages)

    await synchronizer.on_permission_changed(session_id="session-a", session=session)
    await synchronizer.on_permission_changed(session_id="session-a", session=session)

    assert len(session.updates) == 1
