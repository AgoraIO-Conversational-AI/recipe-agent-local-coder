"""SQLite persistence for durable Workspace-scoped Work receipts."""

from __future__ import annotations

import json
import os
import sqlite3
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .models import (
    NONTERMINAL_STATES,
    DeliveryState,
    FinalPresentation,
    PendingPermission,
    PermissionOption,
    SafeActivity,
    WorkReceipt,
    WorkState,
    ensure_transition,
)
from .safety import redact_durable_text


_SCHEMA_VERSION = "1.0"
_STATE_ACTIVITY: dict[WorkState, tuple[str, str]] = {
    "queued": ("accepted", "Work accepted"),
    "starting": ("starting", "Starting work"),
    "running": ("running", "Working"),
    "awaiting_permission": ("waiting_for_permission", "Waiting for permission"),
    "cancelling": ("cancelling", "Cancelling"),
    "completed": ("completed", "Completed"),
    "cancelled": ("cancelled", "Cancelled"),
    "failed": ("failed", "Failed"),
}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bounded(value: str, *, name: str, max_bytes: int) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ValueError(f"{name} is required")
    if "\x00" in normalized:
        raise ValueError(f"{name} cannot contain NUL characters")
    if len(normalized.encode("utf-8")) > max_bytes:
        raise ValueError(f"{name} cannot exceed {max_bytes} bytes")
    return normalized


class WorkStore:
    """Authoritative local Work state with transactional activity records."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self.path.parent, 0o700)
        # FastAPI's TestClient executes the app on its portal thread. Production
        # access remains serialized by the one Task Runtime event loop.
        self._connection = sqlite3.connect(self.path, check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._create_schema()
        os.chmod(self.path, 0o600)

    @classmethod
    def default(cls) -> WorkStore:
        state_directory = os.getenv("VOICE_ACP_STATE_DIR")
        root = (
            Path(state_directory).expanduser()
            if state_directory
            else Path.home()
            / "Library"
            / "Application Support"
            / "Agora Voice ACP"
        )
        return cls(root / "work.sqlite3")

    def _create_schema(self) -> None:
        with self._connection:
            self._connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS metadata (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS works (
                  work_id TEXT PRIMARY KEY,
                  workspace_id TEXT NOT NULL,
                  idempotency_key TEXT NOT NULL,
                  objective TEXT NOT NULL,
                  delivery_agent_id TEXT,
                  state TEXT NOT NULL,
                  created_at TEXT NOT NULL,
                  updated_at TEXT NOT NULL,
                  speech TEXT,
                  inline TEXT,
                  error TEXT,
                  delivery_state TEXT NOT NULL,
                  UNIQUE(workspace_id, idempotency_key)
                );
                CREATE INDEX IF NOT EXISTS works_scope_created
                  ON works(workspace_id, created_at DESC);
                CREATE TABLE IF NOT EXISTS activity (
                  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
                  work_id TEXT NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
                  workspace_id TEXT NOT NULL,
                  kind TEXT NOT NULL,
                  label TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS activity_scope_event
                  ON activity(workspace_id, event_id);
                CREATE TABLE IF NOT EXISTS permissions (
                  work_id TEXT PRIMARY KEY REFERENCES works(work_id) ON DELETE CASCADE,
                  authorization_id TEXT NOT NULL,
                  operation TEXT NOT NULL,
                  options_json TEXT NOT NULL,
                  created_at TEXT NOT NULL
                );
                """
            )
            existing = self._connection.execute(
                "SELECT value FROM metadata WHERE key = 'schema_version'"
            ).fetchone()
            if existing is None:
                self._connection.execute(
                    "INSERT INTO metadata(key, value) VALUES('schema_version', ?)",
                    (_SCHEMA_VERSION,),
                )
            elif existing["value"] != _SCHEMA_VERSION:
                raise ValueError("Unsupported Work Store schema version")
            columns = {
                row["name"]
                for row in self._connection.execute("PRAGMA table_info(works)")
            }
            if "delivery_agent_id" not in columns:
                # Additive and nullable so a rollback to the prior 1.0 artifact
                # can continue reading and writing the same database.
                self._connection.execute(
                    "ALTER TABLE works ADD COLUMN delivery_agent_id TEXT"
                )

    def close(self) -> None:
        self._connection.close()

    def create_or_get(
        self,
        workspace_id: str,
        idempotency_key: str,
        objective: str,
        delivery_agent_id: str | None = None,
    ) -> tuple[WorkReceipt, bool]:
        workspace_id = _bounded(workspace_id, name="workspace_id", max_bytes=128)
        idempotency_key = _bounded(
            idempotency_key, name="idempotency_key", max_bytes=256
        )
        objective = _bounded(
            redact_durable_text(objective),
            name="objective",
            max_bytes=16 * 1024,
        )
        delivery_agent_id = (
            _bounded(
                delivery_agent_id,
                name="delivery_agent_id",
                max_bytes=128,
            )
            if delivery_agent_id is not None
            else None
        )
        existing = self._connection.execute(
            "SELECT * FROM works WHERE workspace_id = ? AND idempotency_key = ?",
            (workspace_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            return self._receipt(existing), False

        work_id = uuid.uuid4().hex
        timestamp = _now()
        try:
            with self._connection:
                self._connection.execute(
                    """
                    INSERT INTO works(
                      work_id, workspace_id, idempotency_key, objective,
                      delivery_agent_id, state,
                      created_at, updated_at, delivery_state
                    ) VALUES (?, ?, ?, ?, ?, 'queued', ?, ?, 'not_ready')
                    """,
                    (
                        work_id,
                        workspace_id,
                        idempotency_key,
                        objective,
                        delivery_agent_id,
                        timestamp,
                        timestamp,
                    ),
                )
                self._insert_activity(
                    work_id,
                    workspace_id,
                    *_STATE_ACTIVITY["queued"],
                    timestamp,
                )
        except sqlite3.IntegrityError:
            existing = self._connection.execute(
                "SELECT * FROM works WHERE workspace_id = ? AND idempotency_key = ?",
                (workspace_id, idempotency_key),
            ).fetchone()
            if existing is None:
                raise
            return self._receipt(existing), False
        return self.get(work_id), True

    def get(self, work_id: str) -> WorkReceipt:
        row = self._connection.execute(
            "SELECT * FROM works WHERE work_id = ?", (work_id,)
        ).fetchone()
        if row is None:
            raise KeyError("Work was not found")
        return self._receipt(row)

    def find_by_idempotency(
        self, workspace_id: str, idempotency_key: str
    ) -> WorkReceipt | None:
        workspace_id = _bounded(workspace_id, name="workspace_id", max_bytes=128)
        idempotency_key = _bounded(
            idempotency_key, name="idempotency_key", max_bytes=256
        )
        row = self._connection.execute(
            "SELECT * FROM works WHERE workspace_id = ? AND idempotency_key = ?",
            (workspace_id, idempotency_key),
        ).fetchone()
        return self._receipt(row) if row is not None else None

    def resolve(self, workspace_id: str, work_id: str | None = None) -> WorkReceipt:
        if work_id is not None:
            row = self._connection.execute(
                "SELECT * FROM works WHERE workspace_id = ? AND work_id = ?",
                (workspace_id, work_id),
            ).fetchone()
        else:
            row = self._connection.execute(
                """
                SELECT * FROM works
                WHERE workspace_id = ?
                ORDER BY
                  CASE WHEN state IN ('starting', 'running', 'awaiting_permission', 'cancelling')
                    THEN 0 ELSE 1 END,
                  updated_at DESC,
                  created_at DESC,
                  rowid DESC
                LIMIT 1
                """,
                (workspace_id,),
            ).fetchone()
        if row is None:
            raise KeyError("Work was not found")
        return self._receipt(row)

    def transition(
        self,
        work_id: str,
        target: WorkState,
        error: str | None = None,
    ) -> WorkReceipt:
        current = self.get(work_id)
        ensure_transition(current.state, target)
        safe_error = (
            _bounded(error, name="error", max_bytes=1024) if error is not None else None
        )
        timestamp = _now()
        kind, label = _STATE_ACTIVITY[target]
        with self._connection:
            self._connection.execute(
                """
                UPDATE works
                SET state = ?, updated_at = ?, error = ?,
                    delivery_state = CASE
                      WHEN ? = 'failed' AND delivery_agent_id IS NOT NULL
                        THEN 'pending_delivery'
                      ELSE delivery_state
                    END
                WHERE work_id = ?
                """,
                (target, timestamp, safe_error, target, work_id),
            )
            self._insert_activity(
                work_id,
                current.workspace_id,
                kind,
                label,
                timestamp,
            )
        return self.get(work_id)

    def append_activity(self, work_id: str, kind: str, label: str) -> SafeActivity:
        receipt = self.get(work_id)
        kind = _bounded(kind, name="activity kind", max_bytes=64)
        label = _bounded(
            redact_durable_text(label), name="activity label", max_bytes=512
        )
        timestamp = _now()
        with self._connection:
            cursor = self._insert_activity(
                work_id,
                receipt.workspace_id,
                kind,
                label,
                timestamp,
            )
        return SafeActivity(
            event_id=int(cursor.lastrowid),
            work_id=work_id,
            workspace_id=receipt.workspace_id,
            kind=kind,
            label=label,
            created_at=timestamp,
        )

    def list_activity(
        self, workspace_id: str, after_event_id: int | None = None
    ) -> list[SafeActivity]:
        rows = self._connection.execute(
            """
            SELECT event_id, work_id, workspace_id, kind, label, created_at
            FROM activity
            WHERE workspace_id = ? AND event_id > ?
            ORDER BY event_id
            """,
            (workspace_id, after_event_id or 0),
        ).fetchall()
        return [self._activity(row) for row in rows]

    def save_permission(self, permission: PendingPermission) -> None:
        receipt = self.get(permission.work_id)
        if receipt.state not in NONTERMINAL_STATES:
            raise ValueError("Cannot attach permission to terminal Work")
        options_json = json.dumps(
            [
                {
                    "option_id": option.option_id,
                    "name": option.name,
                    "kind": option.kind,
                }
                for option in permission.options
            ],
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self._connection:
            self._connection.execute(
                """
                INSERT INTO permissions(
                  work_id, authorization_id, operation, options_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(work_id) DO UPDATE SET
                  authorization_id = excluded.authorization_id,
                  operation = excluded.operation,
                  options_json = excluded.options_json,
                  created_at = excluded.created_at
                """,
                (
                    permission.work_id,
                    permission.authorization_id,
                    permission.operation,
                    options_json,
                    _now(),
                ),
            )

    def pending_permission(self, workspace_id: str) -> PendingPermission | None:
        row = self._connection.execute(
            """
            SELECT p.work_id, p.authorization_id, p.operation, p.options_json
            FROM permissions p
            JOIN works w ON w.work_id = p.work_id
            WHERE w.workspace_id = ?
            ORDER BY p.created_at DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        options = json.loads(row["options_json"])
        return PendingPermission(
            work_id=row["work_id"],
            authorization_id=row["authorization_id"],
            operation=row["operation"],
            options=tuple(PermissionOption(**option) for option in options),
        )

    def clear_permission(self, work_id: str) -> None:
        with self._connection:
            self._connection.execute(
                "DELETE FROM permissions WHERE work_id = ?", (work_id,)
            )

    def save_final(
        self, work_id: str, presentation: FinalPresentation
    ) -> WorkReceipt:
        self.get(work_id)
        safe_presentation = FinalPresentation(
            speech=redact_durable_text(presentation.speech),
            inline=(
                redact_durable_text(presentation.inline)
                if presentation.inline is not None
                else None
            ),
        )
        with self._connection:
            self._connection.execute(
                """
                UPDATE works
                SET speech = ?, inline = ?, delivery_state = 'pending_delivery', updated_at = ?
                WHERE work_id = ?
                """,
                (
                    safe_presentation.speech,
                    safe_presentation.inline,
                    _now(),
                    work_id,
                ),
            )
        return self.get(work_id)

    def claim_delivery(self, work_id: str) -> WorkReceipt | None:
        return self._change_delivery(
            work_id, source="pending_delivery", target="sending"
        )

    def release_delivery(self, work_id: str) -> WorkReceipt | None:
        return self._change_delivery(
            work_id, source="sending", target="pending_delivery"
        )

    def mark_delivery_accepted(self, work_id: str) -> WorkReceipt | None:
        return self._change_delivery(work_id, source="sending", target="accepted")

    def mark_delivery_unknown(self, work_id: str) -> WorkReceipt | None:
        return self._change_delivery(
            work_id, source="sending", target="delivery_unknown"
        )

    def recover_nonterminal(self, error: str) -> list[WorkReceipt]:
        safe_error = _bounded(error, name="error", max_bytes=1024)
        rows = self._connection.execute(
            f"SELECT * FROM works WHERE state IN ({','.join('?' for _ in NONTERMINAL_STATES)})",
            tuple(NONTERMINAL_STATES),
        ).fetchall()
        timestamp = _now()
        recovered: list[WorkReceipt] = []
        with self._connection:
            for row in rows:
                self._connection.execute(
                    """
                    UPDATE works
                    SET state = 'failed', updated_at = ?, error = ?,
                        delivery_state = CASE
                          WHEN delivery_agent_id IS NOT NULL
                            THEN 'pending_delivery'
                          ELSE delivery_state
                        END
                    WHERE work_id = ?
                    """,
                    (timestamp, safe_error, row["work_id"]),
                )
                self._connection.execute(
                    "DELETE FROM permissions WHERE work_id = ?", (row["work_id"],)
                )
                self._insert_activity(
                    row["work_id"],
                    row["workspace_id"],
                    *_STATE_ACTIVITY["failed"],
                    timestamp,
                )
                recovered.append(self.get(row["work_id"]))
        return recovered

    def has_nonterminal(self, workspace_id: str) -> bool:
        row = self._connection.execute(
            f"SELECT 1 FROM works WHERE workspace_id = ? AND state IN ({','.join('?' for _ in NONTERMINAL_STATES)}) LIMIT 1",
            (workspace_id, *tuple(NONTERMINAL_STATES)),
        ).fetchone()
        return row is not None

    def queue_depth(self, workspace_id: str) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) AS count FROM works WHERE workspace_id = ? AND state = 'queued'",
            (workspace_id,),
        ).fetchone()
        return int(row["count"])

    def queued_objective_bytes(self, workspace_id: str) -> int:
        rows = self._connection.execute(
            "SELECT objective FROM works WHERE workspace_id = ? AND state = 'queued'",
            (workspace_id,),
        ).fetchall()
        return sum(len(str(row["objective"]).encode("utf-8")) for row in rows)

    def _change_delivery(
        self,
        work_id: str,
        *,
        source: DeliveryState,
        target: DeliveryState,
    ) -> WorkReceipt | None:
        with self._connection:
            cursor = self._connection.execute(
                """
                UPDATE works
                SET delivery_state = ?, updated_at = ?
                WHERE work_id = ? AND delivery_state = ?
                """,
                (target, _now(), work_id, source),
            )
        return self.get(work_id) if cursor.rowcount == 1 else None

    def _insert_activity(
        self,
        work_id: str,
        workspace_id: str,
        kind: str,
        label: str,
        created_at: str,
    ) -> sqlite3.Cursor:
        return self._connection.execute(
            """
            INSERT INTO activity(work_id, workspace_id, kind, label, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (work_id, workspace_id, kind, label, created_at),
        )

    @staticmethod
    def _receipt(row: sqlite3.Row) -> WorkReceipt:
        presentation = (
            FinalPresentation(speech=row["speech"], inline=row["inline"])
            if row["speech"] is not None
            else None
        )
        return WorkReceipt(
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            idempotency_key=row["idempotency_key"],
            objective=row["objective"],
            state=row["state"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            final_presentation=presentation,
            error=row["error"],
            delivery_agent_id=row["delivery_agent_id"],
            delivery_state=row["delivery_state"],
        )

    @staticmethod
    def _activity(row: sqlite3.Row) -> SafeActivity:
        return SafeActivity(
            event_id=int(row["event_id"]),
            work_id=row["work_id"],
            workspace_id=row["workspace_id"],
            kind=row["kind"],
            label=row["label"],
            created_at=row["created_at"],
        )
