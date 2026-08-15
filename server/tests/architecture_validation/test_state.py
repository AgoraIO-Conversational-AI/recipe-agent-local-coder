"""Tests for validation-only permission state."""

import pytest

from architecture_validation.models import PermissionDecision
from architecture_validation.state import ValidationStateStore


@pytest.fixture
def store():
    return ValidationStateStore()


@pytest.mark.anyio
async def test_seed_permission_is_current_and_versions_increase(store):
    first = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    second = await store.seed_permission(
        session_id="session-a",
        question="Allow installing dependencies?",
        operation="install_dependencies",
    )

    assert first.version == 1
    assert second.version == 2
    assert second.authorization_id != first.authorization_id
    assert await store.current_permission("session-a") == second


@pytest.mark.anyio
async def test_permission_resolution_requires_matching_session_authorization_and_version(store):
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )

    wrong_session = await store.resolve_permission(
        session_id="session-b",
        authorization_id=pending.authorization_id,
        version=pending.version,
        decision="allow",
    )
    wrong_version = await store.resolve_permission(
        session_id="session-a",
        authorization_id=pending.authorization_id,
        version=pending.version + 1,
        decision="allow",
    )

    assert wrong_session.code == "permission_not_found"
    assert wrong_version.code == "permission_stale"
    assert await store.current_permission("session-a") == pending


@pytest.mark.anyio
@pytest.mark.parametrize("decision", ["allow", "reject"])
async def test_resolution_clears_current_permission(
    store, decision: PermissionDecision
):
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )

    result = await store.resolve_permission(
        session_id="session-a",
        authorization_id=pending.authorization_id,
        version=pending.version,
        decision=decision,
    )

    assert result.code == "permission_resolved"
    assert result.decision == decision
    assert await store.current_permission("session-a") is None


@pytest.mark.anyio
async def test_resolved_permission_cannot_be_replayed(store):
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow running tests?",
        operation="run_tests",
    )
    await store.resolve_permission(
        session_id="session-a",
        authorization_id=pending.authorization_id,
        version=pending.version,
        decision="allow",
    )

    replay = await store.resolve_permission(
        session_id="session-a",
        authorization_id=pending.authorization_id,
        version=pending.version,
        decision="allow",
    )

    assert replay.code == "permission_not_found"


@pytest.mark.anyio
async def test_sessions_are_isolated(store):
    permission_a = await store.seed_permission(
        session_id="session-a",
        question="Allow A?",
        operation="operation_a",
    )
    permission_b = await store.seed_permission(
        session_id="session-b",
        question="Allow B?",
        operation="operation_b",
    )

    assert await store.current_permission("session-a") == permission_a
    assert await store.current_permission("session-b") == permission_b


@pytest.mark.anyio
async def test_reconnect_rebind_preserves_permission_identity(store):
    pending = await store.seed_permission(
        session_id="session-a",
        question="Allow A?",
        operation="operation_a",
    )

    await store.rebind_session("session-a", "session-b")

    rebound = await store.current_permission("session-b")
    assert await store.current_permission("session-a") is None
    assert rebound is not None
    assert rebound.authorization_id == pending.authorization_id
    assert rebound.version == pending.version
