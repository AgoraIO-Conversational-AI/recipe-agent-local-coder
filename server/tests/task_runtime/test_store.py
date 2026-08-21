"""Durable Work Store behavior through its public interface."""

import os
import sqlite3
import stat

import pytest

from task_runtime.models import FinalPresentation, PendingPermission, PermissionOption
from task_runtime.store import WorkStore


@pytest.fixture
def store(tmp_path):
    work_store = WorkStore(tmp_path / "state" / "work.sqlite3")
    yield work_store
    work_store.close()


def test_create_or_get_is_idempotent_within_one_workspace(store):
    first, first_created = store.create_or_get(
        workspace_id="scope-a",
        idempotency_key="turn-1",
        objective="Run the tests",
    )
    second, second_created = store.create_or_get(
        workspace_id="scope-a",
        idempotency_key="turn-1",
        objective="A duplicate body must not replace the original",
    )

    assert first_created is True
    assert second_created is False
    assert second == first


def test_delivery_agent_is_persisted_and_idempotent_work_is_not_retargeted(store):
    first, first_created = store.create_or_get(
        "scope-a",
        "turn-delivery",
        "Inspect",
        delivery_agent_id="agent-a",
    )
    duplicate, duplicate_created = store.create_or_get(
        "scope-a",
        "turn-delivery",
        "Different objective",
        delivery_agent_id="agent-b",
    )

    assert first_created is True
    assert duplicate_created is False
    assert first.delivery_agent_id == "agent-a"
    assert duplicate.delivery_agent_id == "agent-a"
    assert store.get(first.work_id).delivery_agent_id == "agent-a"


def test_same_idempotency_key_is_independent_across_workspaces(store):
    first, _ = store.create_or_get("scope-a", "turn-1", "Inspect A")
    second, _ = store.create_or_get("scope-b", "turn-1", "Inspect B")

    assert first.work_id != second.work_id


def test_idempotency_lookup_and_queued_objective_bytes_follow_queue_state(store):
    first, _ = store.create_or_get("scope-a", "turn-1", "abcd")
    second, _ = store.create_or_get("scope-a", "turn-2", "é")

    assert store.find_by_idempotency("scope-a", "turn-1") == first
    assert store.find_by_idempotency("scope-b", "turn-1") is None
    assert store.queued_objective_bytes("scope-a") == 6

    store.transition(first.work_id, "starting")
    assert store.queued_objective_bytes("scope-a") == 2


def test_persisted_text_redacts_common_credentials(store):
    receipt, _ = store.create_or_get(
        "scope-a",
        "turn-secret",
        "Use OPENAI_API_KEY=spoken-secret and Authorization: Bearer abc123",
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(
            speech="Done with token: private-token",
            inline='Result for {"password": "private-password"}',
        ),
    )

    stored = store.get(receipt.work_id)
    assert "spoken-secret" not in stored.objective
    assert "abc123" not in stored.objective
    assert stored.final_presentation is not None
    assert "private-token" not in stored.final_presentation.speech
    assert "private-password" not in stored.final_presentation.inline
    assert "[REDACTED]" in stored.objective


def test_persisted_text_redacts_unlabelled_provider_and_pem_credentials(store):
    github_token = "ghp_1234567890abcdefghijklmnop"
    aws_key = "AKIA1234567890ABCDEF"
    jwt = "eyJabcdefghijk.abcdefghijkl.abcdefghijk"
    pem = "-----BEGIN PRIVATE KEY-----\nprivate-data\n-----END PRIVATE KEY-----"
    receipt, _ = store.create_or_get(
        "scope-a",
        "turn-provider-secret",
        (
            f"Use {github_token} {aws_key} {jwt} "
            "https://person:password@example.com and PATH=/private/bin"
        ),
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(speech="Credential removed", inline=pem),
    )

    stored = store.get(receipt.work_id)
    serialized = (
        stored.objective
        + stored.final_presentation.speech
        + stored.final_presentation.inline
    )
    for secret in (github_token, aws_key, jwt, "person:password", "private-data"):
        assert secret not in serialized
    assert "PATH=[REDACTED]" in stored.objective


def test_transition_persists_activity_permission_and_final_result(store):
    receipt, _ = store.create_or_get("scope-a", "turn-1", "Run tests")

    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    custom = store.append_activity(receipt.work_id, "execute", "Running tests")
    permission = PendingPermission(
        work_id=receipt.work_id,
        authorization_id="auth-a",
        operation="Run tests",
        options=(PermissionOption("once", "Allow once", "allow_once"),),
    )
    store.save_permission(permission)

    assert store.pending_permission("scope-a") == permission
    assert store.list_activity("scope-a", after_event_id=custom.event_id - 1) == [
        custom
    ]

    store.clear_permission(receipt.work_id)
    stored = store.save_final(
        receipt.work_id,
        FinalPresentation(speech="Tests passed.", inline="`pytest` passed"),
    )
    stored = store.transition(stored.work_id, "completed")

    assert stored.final_presentation == FinalPresentation(
        speech="Tests passed.", inline="`pytest` passed"
    )
    assert stored.delivery_state == "pending_delivery"
    assert store.pending_permission("scope-a") is None


def test_delivery_state_transitions_are_compare_and_set(store):
    receipt, _ = store.create_or_get(
        "scope-a",
        "turn-delivery-state",
        "Run tests",
        delivery_agent_id="agent-a",
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(speech="Tests passed.", inline="Tests passed."),
    )

    claimed = store.claim_delivery(receipt.work_id)

    assert claimed is not None
    assert claimed.delivery_state == "sending"
    assert store.claim_delivery(receipt.work_id) is None
    released = store.release_delivery(receipt.work_id)
    assert released is not None
    assert released.delivery_state == "pending_delivery"
    assert store.claim_delivery(receipt.work_id).delivery_state == "sending"
    accepted = store.mark_delivery_accepted(receipt.work_id)
    assert accepted is not None
    assert accepted.delivery_state == "accepted"
    assert store.mark_delivery_unknown(receipt.work_id) is None
    assert store.release_delivery(receipt.work_id) is None


def test_delivery_unknown_is_terminal_for_automatic_delivery(store):
    receipt, _ = store.create_or_get(
        "scope-a",
        "turn-delivery-unknown",
        "Run tests",
        delivery_agent_id="agent-a",
    )
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.save_final(
        receipt.work_id,
        FinalPresentation(speech="Tests passed.", inline=None),
    )
    assert store.mark_delivery_unknown(receipt.work_id) is None
    assert store.claim_delivery(receipt.work_id).delivery_state == "sending"

    unknown = store.mark_delivery_unknown(receipt.work_id)

    assert unknown is not None
    assert unknown.delivery_state == "delivery_unknown"
    assert store.claim_delivery(receipt.work_id) is None


def test_targeted_failure_becomes_pending_delivery_but_cancellation_does_not(store):
    failed, _ = store.create_or_get(
        "scope-a", "turn-failed", "Fail", delivery_agent_id="agent-a"
    )
    store.transition(failed.work_id, "starting")
    failed = store.transition(failed.work_id, "failed", "Safe failure")
    cancelled, _ = store.create_or_get(
        "scope-a", "turn-cancelled", "Cancel", delivery_agent_id="agent-a"
    )
    cancelled = store.transition(cancelled.work_id, "cancelled")

    assert failed.delivery_state == "pending_delivery"
    assert cancelled.delivery_state == "not_ready"


def test_restart_marks_every_nonterminal_work_failed(store):
    receipts = [
        store.create_or_get("scope-a", f"key-{index}", "Work")[0]
        for index in range(5)
    ]
    store.transition(receipts[0].work_id, "starting")
    store.transition(receipts[0].work_id, "running")
    store.transition(receipts[1].work_id, "starting")
    store.transition(receipts[1].work_id, "running")
    store.transition(receipts[1].work_id, "awaiting_permission")
    store.transition(receipts[2].work_id, "cancelled")

    recovered = store.recover_nonterminal(
        "Local Runner restarted before Work completed."
    )

    assert len(recovered) == 4
    assert {item.state for item in recovered} == {"failed"}
    assert {item.error for item in recovered} == {
        "Local Runner restarted before Work completed."
    }
    assert store.get(receipts[2].work_id).state == "cancelled"
    assert store.has_nonterminal("scope-a") is False


def test_terminal_work_rejects_permission_without_persisting_it(store):
    receipt, _ = store.create_or_get("scope-a", "turn-1", "Run tests")
    store.transition(receipt.work_id, "starting")
    store.transition(receipt.work_id, "running")
    store.transition(receipt.work_id, "completed")
    permission = PendingPermission(
        work_id=receipt.work_id,
        authorization_id="auth-a",
        operation="Run tests",
        options=(PermissionOption("once", "Allow once", "allow_once"),),
    )

    with pytest.raises(ValueError, match="terminal Work"):
        store.save_permission(permission)

    assert store.pending_permission("scope-a") is None


def test_resolve_prefers_active_then_most_recent_and_reports_queue_depth(store):
    older, _ = store.create_or_get("scope-a", "turn-1", "First")
    newer, _ = store.create_or_get("scope-a", "turn-2", "Second")

    assert store.resolve("scope-a").work_id == newer.work_id
    assert store.queue_depth("scope-a") == 2

    store.transition(older.work_id, "starting")
    store.transition(older.work_id, "running")

    assert store.resolve("scope-a").work_id == older.work_id
    with pytest.raises(KeyError, match="Work was not found"):
        store.resolve("scope-b", older.work_id)


def test_database_reopens_with_private_permissions(tmp_path):
    path = tmp_path / "state" / "work.sqlite3"
    first = WorkStore(path)
    receipt, _ = first.create_or_get("scope-a", "turn-1", "Inspect")
    first.close()

    reopened = WorkStore(path)
    try:
        assert reopened.get(receipt.work_id) == receipt
        if os.name == "posix":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
    finally:
        reopened.close()


def test_version_1_database_adds_delivery_target_without_breaking_rollback(tmp_path):
    path = tmp_path / "state" / "work.sqlite3"
    path.parent.mkdir()
    connection = sqlite3.connect(path)
    connection.executescript(
        """
        CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO metadata(key, value) VALUES('schema_version', '1.0');
        CREATE TABLE works (
          work_id TEXT PRIMARY KEY,
          workspace_id TEXT NOT NULL,
          idempotency_key TEXT NOT NULL,
          objective TEXT NOT NULL,
          state TEXT NOT NULL,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          speech TEXT,
          inline TEXT,
          error TEXT,
          delivery_state TEXT NOT NULL,
          UNIQUE(workspace_id, idempotency_key)
        );
        INSERT INTO works(
          work_id, workspace_id, idempotency_key, objective, state,
          created_at, updated_at, delivery_state
        ) VALUES(
          'work-old', 'scope-a', 'turn-old', 'Inspect', 'queued',
          '2026-08-20T00:00:00Z', '2026-08-20T00:00:00Z', 'not_ready'
        );
        """
    )
    connection.commit()
    connection.close()

    upgraded = WorkStore(path)
    try:
        assert upgraded.get("work-old").objective == "Inspect"
        assert upgraded.get("work-old").delivery_agent_id is None
    finally:
        upgraded.close()

    inspection = sqlite3.connect(path)
    inspection.row_factory = sqlite3.Row
    try:
        columns = {
            row["name"] for row in inspection.execute("PRAGMA table_info(works)")
        }
        version = inspection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()["value"]

        assert "delivery_agent_id" in columns
        assert version == "1.0"
        inspection.execute(
            """
            INSERT INTO works(
              work_id, workspace_id, idempotency_key, objective, state,
              created_at, updated_at, delivery_state
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "work-after-rollback",
                "scope-a",
                "turn-after-rollback",
                "Old writer",
                "queued",
                "2026-08-20T00:00:01Z",
                "2026-08-20T00:00:01Z",
                "not_ready",
            ),
        )
        inspection.commit()
        inserted = inspection.execute(
            "SELECT delivery_agent_id FROM works WHERE work_id = ?",
            ("work-after-rollback",),
        ).fetchone()
        assert inserted["delivery_agent_id"] is None
    finally:
        inspection.close()
