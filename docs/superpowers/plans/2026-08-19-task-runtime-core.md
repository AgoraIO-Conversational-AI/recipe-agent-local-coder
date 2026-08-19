# Task Runtime Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the durable, offline-testable core that accepts Work, executes one ACP prompt at a time, persists safe progress and results, correlates current-operation permissions, and confirms cancellation.

**Architecture:** Add a backend-neutral `task_runtime` package beside `acp_runtime`. SQLite owns authoritative Work state; one asynchronous coordinator owns FIFO execution and delegates prompts to the existing persistent `AcpClientPort`. ACP-specific messages are projected into bounded domain events at the adapter boundary, while MCP ingress, SSE/UI, Agora Speak delivery, and ngrok remain later plans.

**Tech Stack:** Python 3.10+, stdlib `sqlite3` and `asyncio`, `agent-client-protocol>=0.11,<0.12`, pytest + AnyIO, existing FastAPI composition.

**Design:** [`docs/superpowers/specs/2026-08-15-agora-voice-acp-local-design.md`](../specs/2026-08-15-agora-voice-acp-local-design.md)

## Global Constraints

- macOS Apple Silicon remains the only Certified v0.1 platform.
- Source, tests, logs, UI copy, and documentation are English-only.
- Keep one persistent ACP session for the selected Workspace Scope and execute one prompt at a time.
- `start_work` must persist before returning and must never await ACP completion.
- Work states are `queued`, `starting`, `running`, `awaiting_permission`, `cancelling`, `completed`, `cancelled`, and `failed`.
- A Pending Permission blocks new Work acceptance; merely running Work does not.
- Voice permission choices are only `allow` and `reject`; never select `allow_always` or `reject_always`.
- Project Folder is ACP session context, not a filesystem sandbox.
- Never persist raw reasoning, complete command output, environment values, authentication material, or unredacted exception text.
- No fixed queue-count limit is introduced in v0.1.
- No new network route is added in this plan. Authenticated MCP, SSE, UI, Agora Speak, ngrok, and live conversation tests are deferred.
- All verification in this plan must use fake ACP components and consume zero Agora minutes.

---

### Task 1: Define Work and activity domain types

**Files:**
- Create: `server/src/task_runtime/__init__.py`
- Create: `server/src/task_runtime/models.py`
- Create: `server/tests/task_runtime/__init__.py`
- Create: `server/tests/task_runtime/test_models.py`

**Interfaces:**
- Consumes: `WorkspaceScope.id` as the stable local scope identifier.
- Produces: `WorkState`, `DeliveryState`, `PermissionDecision`, `PermissionOption`, `PendingPermission`, `SafeActivity`, `FinalPresentation`, `WorkReceipt`, `TERMINAL_STATES`, `NONTERMINAL_STATES`, and `ensure_transition(current, target)`.

- [ ] **Step 1: Write failing state-machine and validation tests**

```python
from dataclasses import replace

import pytest

from task_runtime.models import (
    FinalPresentation,
    WorkReceipt,
    ensure_transition,
)


def test_work_state_machine_accepts_only_public_lifecycle_edges():
    allowed = {
        ("queued", "starting"),
        ("queued", "cancelled"),
        ("starting", "running"),
        ("starting", "failed"),
        ("running", "awaiting_permission"),
        ("awaiting_permission", "running"),
        ("running", "cancelling"),
        ("awaiting_permission", "cancelling"),
        ("running", "completed"),
        ("running", "failed"),
        ("cancelling", "cancelled"),
        ("cancelling", "failed"),
    }
    for current, target in allowed:
        ensure_transition(current, target)

    with pytest.raises(ValueError, match="Illegal Work transition"):
        ensure_transition("completed", "running")


def test_final_presentation_requires_bounded_speech_and_safe_optional_inline():
    result = FinalPresentation(speech="Tests passed.", inline="`pytest` passed")
    assert result.speech == "Tests passed."

    with pytest.raises(ValueError, match="speech is required"):
        FinalPresentation(speech="   ")


def test_terminal_receipt_is_immutable_by_transition_policy(work_receipt: WorkReceipt):
    completed = replace(work_receipt, state="completed")
    with pytest.raises(ValueError, match="Illegal Work transition"):
        ensure_transition(completed.state, "queued")
```

Define `work_receipt` in the same test module as:

```python
@pytest.fixture
def work_receipt() -> WorkReceipt:
    return WorkReceipt(
        work_id="work-a",
        workspace_id="scope-a",
        idempotency_key="turn-a",
        objective="Run the tests",
        state="queued",
        created_at="2026-08-19T00:00:00Z",
        updated_at="2026-08-19T00:00:00Z",
    )
```

- [ ] **Step 2: Run the tests and verify RED**

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_models.py -q
```

Expected: collection fails because `task_runtime.models` does not exist.

- [ ] **Step 3: Implement the domain module**

Use frozen dataclasses and these exact public shapes:

```python
WorkState = Literal[
    "queued", "starting", "running", "awaiting_permission",
    "cancelling", "completed", "cancelled", "failed",
]
DeliveryState = Literal[
    "not_ready", "pending_delivery", "sending", "accepted", "delivery_unknown",
]
PermissionDecision = Literal["allow", "reject"]
PermissionKind = Literal[
    "allow_once", "allow_always", "reject_once", "reject_always",
]

@dataclass(frozen=True)
class PermissionOption:
    option_id: str
    name: str
    kind: PermissionKind

@dataclass(frozen=True)
class PendingPermission:
    work_id: str
    authorization_id: str
    operation: str
    options: tuple[PermissionOption, ...]

@dataclass(frozen=True)
class SafeActivity:
    event_id: int | None
    work_id: str
    workspace_id: str
    kind: str
    label: str
    created_at: str

@dataclass(frozen=True)
class FinalPresentation:
    speech: str
    inline: str | None = None

@dataclass(frozen=True)
class WorkReceipt:
    work_id: str
    workspace_id: str
    idempotency_key: str
    objective: str
    state: WorkState
    created_at: str
    updated_at: str
    final_presentation: FinalPresentation | None = None
    error: str | None = None
    delivery_state: DeliveryState = "not_ready"
```

`FinalPresentation.__post_init__` must normalize surrounding whitespace, reject empty `speech`, bound `speech` to 16 KiB and `inline` to 256 KiB by UTF-8 bytes, and reject NUL characters. `ensure_transition` must use one explicit adjacency map; terminal states have no outgoing edges.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run the Task 1 command. Expected: all tests pass.

- [ ] **Step 5: Commit the domain slice**

```bash
git add server/src/task_runtime server/tests/task_runtime
git commit -m "feat(server): define Work runtime domain"
```

---

### Task 2: Add the SQLite Work Store

**Files:**
- Create: `server/src/task_runtime/store.py`
- Create: `server/tests/task_runtime/test_store.py`
- Modify: `server/src/task_runtime/__init__.py`

**Interfaces:**
- Consumes: Task 1 domain dataclasses and `WorkspaceScope.id`.
- Produces: `WorkStore.default()`, `create_or_get(workspace_id: str, idempotency_key: str, objective: str) -> tuple[WorkReceipt, bool]`, `get(work_id: str) -> WorkReceipt`, `resolve(workspace_id: str, work_id: str | None = None) -> WorkReceipt`, `transition(work_id: str, target: WorkState, error: str | None = None) -> WorkReceipt`, `append_activity(work_id: str, kind: str, label: str) -> SafeActivity`, `list_activity(workspace_id: str, after_event_id: int | None = None) -> list[SafeActivity]`, `save_permission(permission: PendingPermission) -> None`, `pending_permission(workspace_id: str) -> PendingPermission | None`, `clear_permission(work_id: str) -> None`, `save_final(work_id: str, presentation: FinalPresentation) -> WorkReceipt`, `recover_nonterminal(error: str) -> list[WorkReceipt]`, `has_nonterminal(workspace_id: str) -> bool`, and `queue_depth(workspace_id: str) -> int`.

- [ ] **Step 1: Write failing persistence tests**

Cover these public behaviors in `test_store.py`:

```python
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


def test_same_idempotency_key_is_independent_across_workspaces(store):
    first, _ = store.create_or_get("scope-a", "turn-1", "Inspect A")
    second, _ = store.create_or_get("scope-b", "turn-1", "Inspect B")
    assert first.work_id != second.work_id


def test_restart_marks_every_nonterminal_work_failed(store):
    receipts = [store.create_or_get("scope-a", f"key-{n}", "Work")[0] for n in range(5)]
    store.transition(receipts[0].work_id, "starting")
    store.transition(receipts[0].work_id, "running")
    store.transition(receipts[1].work_id, "starting")
    store.transition(receipts[1].work_id, "running")
    store.transition(receipts[1].work_id, "awaiting_permission")
    store.transition(receipts[2].work_id, "cancelled")

    recovered = store.recover_nonterminal("Local Runner restarted before Work completed.")

    assert {item.state for item in recovered} == {"failed"}
    assert store.get(receipts[2].work_id).state == "cancelled"
```

Also test transactionally persisted activity, permission option identifiers, final presentation, queue depth, current-or-recent resolution, database reopen, and `0600` database permissions.

- [ ] **Step 2: Run the store tests and verify RED**

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_store.py -q
```

Expected: import fails because `task_runtime.store` does not exist.

- [ ] **Step 3: Implement the schema and transaction boundary**

Create a schema-version table and these tables:

```sql
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

CREATE TABLE activity (
  event_id INTEGER PRIMARY KEY AUTOINCREMENT,
  work_id TEXT NOT NULL REFERENCES works(work_id) ON DELETE CASCADE,
  workspace_id TEXT NOT NULL,
  kind TEXT NOT NULL,
  label TEXT NOT NULL,
  created_at TEXT NOT NULL
);

CREATE TABLE permissions (
  work_id TEXT PRIMARY KEY REFERENCES works(work_id) ON DELETE CASCADE,
  authorization_id TEXT NOT NULL,
  operation TEXT NOT NULL,
  options_json TEXT NOT NULL,
  created_at TEXT NOT NULL
);
```

`WorkStore.default()` must use `VOICE_ACP_STATE_DIR/work.sqlite3` or the same `~/Library/Application Support/Agora Voice ACP/` parent as `WorkspaceConfigStore`. Open with foreign keys enabled, create the parent with `0700`, enforce database mode `0600`, and use explicit transactions for every state-plus-event update. Use UUID4 hex Work IDs and UTC ISO-8601 timestamps ending in `Z`.

`transition()` must read the current state, call `ensure_transition`, update the receipt, and append the matching safe activity within one transaction. It must never accept raw exception text; callers pass a fixed safe error string.

- [ ] **Step 4: Run store and domain tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_models.py tests/task_runtime/test_store.py -q
```

Expected: all tests pass.

- [ ] **Step 5: Commit the durable store**

```bash
git add server/src/task_runtime server/tests/task_runtime
git commit -m "feat(server): persist durable Work receipts"
```

---

### Task 3: Extend the ACP port from readiness to prompt execution

**Files:**
- Modify: `server/src/acp_runtime/acp_client.py`
- Modify: `server/src/acp_runtime/codex.py`
- Modify: `server/tests/acp_runtime/fake_acp_agent.py`
- Modify: `server/tests/acp_runtime/test_acp_client.py`

**Interfaces:**
- Consumes: the existing open ACP session and Task 1 permission option kinds.
- Produces: `AcpPromptObserver`, `AcpPromptResult`, `AcpPermissionOutcome`, plus `AcpClientPort.prompt(objective, observer)` and `AcpClientPort.cancel()`.

- [ ] **Step 1: Write failing ACP prompt contract tests**

Add tests proving:

```python
@pytest.mark.anyio
async def test_prompt_streams_only_safe_updates_and_returns_final_text(project):
    observer = RecordingPromptObserver()
    connection = FakeConnection(
        updates=[
            acp.ToolCallStart(
                sessionUpdate="tool_call",
                toolCallId="tool-1",
                title="Run tests with SECRET=value",
                kind="execute",
            ),
            acp.AgentThoughtChunk(
                sessionUpdate="agent_thought_chunk",
                content=acp.TextContentBlock(type="text", text="private reasoning"),
            ),
            acp.AgentMessageChunk(
                sessionUpdate="agent_message_chunk",
                content=acp.TextContentBlock(type="text", text="All tests passed."),
            ),
        ],
        stop_reason="end_turn",
    )
    client = opened_client(monkeypatch, connection, project)

    result = await client.prompt("Run the tests", observer)

    assert result.stop_reason == "end_turn"
    assert result.final_text == "All tests passed."
    assert [event.kind for event in observer.events] == ["execute"]
    assert "private reasoning" not in repr(observer.events)


@pytest.mark.anyio
async def test_cancel_notifies_the_active_session(opened_client):
    await opened_client.cancel()
    assert opened_client.connection.cancelled == ["fake-session"]
```

Also prove a second concurrent `prompt()` fails closed, prompting without an open session fails, non-text agent content is ignored, and malformed/empty completion returns a fixed failure rather than exposing protocol content.

- [ ] **Step 2: Run the focused ACP tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/acp_runtime/test_acp_client.py -q
```

Expected: fails because `prompt` and `cancel` are absent.

- [ ] **Step 3: Add backend-neutral ACP execution types**

Define these exact shapes in `acp_client.py`:

```python
@dataclass(frozen=True)
class AcpPermissionOption:
    option_id: str
    name: str
    kind: Literal["allow_once", "allow_always", "reject_once", "reject_always"]

@dataclass(frozen=True)
class AcpPermissionRequest:
    authorization_id: str
    operation: str
    options: tuple[AcpPermissionOption, ...]

@dataclass(frozen=True)
class AcpPermissionOutcome:
    option_id: str | None

@dataclass(frozen=True)
class AcpPromptResult:
    stop_reason: Literal["end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"]
    final_text: str

class AcpPromptObserver(Protocol):
    async def on_event(self, event: AcpSessionEvent) -> None:
        raise NotImplementedError

    async def request_permission(self, request: AcpPermissionRequest) -> AcpPermissionOutcome:
        raise NotImplementedError
```

Extend `AcpClientPort` with the two methods. `AcpSessionEvent` must contain only `kind` and bounded `label`; it must never contain ACP raw input/output or thought text.

- [ ] **Step 4: Implement Codex prompt, update, permission, and cancel mapping**

Keep one `_active_observer` and one `asyncio.Lock` in `CodexAcpClient`. `prompt()` must call:

```python
response = await self._connection.prompt(
    self._session_id,
    [acp.TextContentBlock(type="text", text=objective)],
)
```

The callback must:

- map `ToolCallStart` and `ToolCallProgress` kinds to bounded labels and ignore `rawInput`, `rawOutput`, content blocks, locations, and thought chunks;
- concatenate only `AgentMessageChunk` text into the final response buffer;
- generate a random internal authorization ID for each permission request;
- forward option IDs and kinds to the observer;
- return `AllowedOutcome(outcome="selected", optionId=outcome.option_id)` only for an option ID returned by the observer, otherwise `DeniedOutcome(outcome="cancelled")`;
- clear the observer and message buffer in `finally`.

`cancel()` must call `connection.cancel(session_id)` and must not mark Work cancelled itself. The runtime waits for the active prompt result.

- [ ] **Step 5: Extend the fake process and rerun ACP tests**

Add deterministic fake modes for prompt completion, update emission, permission request, cancellation, and process exit. Record `session/prompt`, `session/cancel`, and the selected permission outcome without recording objective bodies or secrets.

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/acp_runtime -q
```

Expected: all ACP runtime tests pass.

- [ ] **Step 6: Commit the executable ACP boundary**

```bash
git add server/src/acp_runtime server/tests/acp_runtime
git commit -m "feat(server): execute Work through ACP prompts"
```

---

### Task 4: Implement current-operation Permission Broker

**Files:**
- Create: `server/src/task_runtime/permissions.py`
- Create: `server/tests/task_runtime/test_permissions.py`
- Modify: `server/src/task_runtime/__init__.py`

**Interfaces:**
- Consumes: `WorkStore`, `AcpPermissionRequest`, `AcpPermissionOutcome`, and Task 1 `PermissionDecision`.
- Produces: internal `PermissionResolution(authorization_id: str, decision: PermissionDecision, selected_option_id: str | None)`, `PermissionBroker.request(work_id, workspace_id, request)`, `respond(workspace_id, decision) -> PermissionResolution`, `cancel(work_id)`, and `has_pending(workspace_id)`.

- [ ] **Step 1: Write failing broker tests**

```python
@pytest.mark.anyio
async def test_allow_selects_only_allow_once(store):
    broker = PermissionBroker(store)
    pending = asyncio.create_task(
        broker.request(
            work_id="work-a",
            workspace_id="scope-a",
            request=AcpPermissionRequest(
                authorization_id="auth-a",
                operation="Run tests",
                options=(
                    AcpPermissionOption("always", "Always allow", "allow_always"),
                    AcpPermissionOption("once", "Allow once", "allow_once"),
                ),
            ),
        )
    )
    await wait_until(lambda: broker.has_pending("scope-a"))

    resolved = await broker.respond("scope-a", "allow")

    assert resolved.authorization_id == "auth-a"
    assert resolved.selected_option_id == "once"
    assert (await pending).option_id == "once"


@pytest.mark.anyio
async def test_reject_without_reject_once_returns_cancelled(store):
    broker = PermissionBroker(store)
    pending = asyncio.create_task(
        broker.request(
            work_id="work-a",
            workspace_id="scope-a",
            request=AcpPermissionRequest(
                authorization_id="auth-a",
                operation="Delete generated output",
                options=(
                    AcpPermissionOption(
                        "reject-always", "Always reject", "reject_always"
                    ),
                ),
            ),
        )
    )
    await wait_until(lambda: broker.has_pending("scope-a"))

    resolved = await broker.respond("scope-a", "reject")

    assert resolved.authorization_id == "auth-a"
    assert resolved.selected_option_id is None
    assert (await pending).option_id is None
```

Also test no TTL, stale authorization rejection, exactly one Pending Permission globally, cancellation resolving the waiter, and permission persistence across voice disconnect (modeled as elapsed time without calling `respond`).

- [ ] **Step 2: Run permission tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_permissions.py -q
```

Expected: import fails because `task_runtime.permissions` does not exist.

- [ ] **Step 3: Implement the broker**

Use one `asyncio.Lock`, one current pending record, and one `asyncio.Future[AcpPermissionOutcome]`. `request()` must persist the permission before exposing it and must wait without a timeout. `respond()` must select only the first matching `allow_once` or `reject_once`; reject falls back to `AcpPermissionOutcome(option_id=None)`. `cancel()` resolves the current future with `None`. Every terminal path clears both SQLite permission state and the in-memory future exactly once.

Use fixed public errors:

```text
permission_decision_required
permission_not_found
permission_authorization_mismatch
permission_option_unavailable
```

Do not return option IDs or authorization IDs from any future public projection; they remain internal correlation values.

- [ ] **Step 4: Run broker, store, and model tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime -q
```

Expected: all current Task Runtime tests pass.

- [ ] **Step 5: Commit the permission broker**

```bash
git add server/src/task_runtime server/tests/task_runtime
git commit -m "feat(server): broker current-operation permissions"
```

---

### Task 5: Build the serial Task Runtime coordinator

**Files:**
- Create: `server/src/task_runtime/runtime.py`
- Create: `server/tests/task_runtime/test_runtime.py`
- Modify: `server/src/task_runtime/__init__.py`
- Modify: `server/src/acp_runtime/routes.py`
- Modify: `server/tests/acp_runtime/test_workspace_routes.py`

**Interfaces:**
- Consumes: `WorkspaceService`, `LocalRuntimeCoordinator.status()`, Task 2 `WorkStore`, Task 3 `AcpClientPort`, and Task 4 `PermissionBroker`.
- Produces: `TaskRuntime.start()`, `close()`, `start_work(objective, idempotency_key)`, `get_work_status(work_id=None)`, `cancel_work(work_id=None)`, `respond_permission(decision)`, `queue_depth()`, and `TaskRuntimeWorkspaceSwitchGuard.check(previous, change)`.

- [ ] **Step 1: Write the failing tracer-bullet test**

```python
@pytest.mark.anyio
async def test_start_work_returns_after_persistence_and_completes_in_background(runtime):
    runtime.acp.block_prompts()

    accepted = await runtime.start_work("Run the tests", "turn-1")

    assert accepted.state == "queued"
    assert runtime.store.get(accepted.work_id).state == "queued"
    assert runtime.acp.prompt_started is False

    await runtime.acp.release_prompts(final_text="All tests passed.")
    completed = await runtime.wait_for_terminal(accepted.work_id)

    assert completed.state == "completed"
    assert completed.final_presentation == FinalPresentation(
        speech="All tests passed.",
        inline="All tests passed.",
    )
```

The test fixture must call `await runtime.start()` and `await runtime.close()`; `wait_for_terminal` is test-only fixture logic and not a production API.

- [ ] **Step 2: Add the complete coordinator matrix**

Before implementation, add tests for:

- six queued Work receipts accepted without a count cap and executed FIFO;
- at most one concurrent ACP prompt;
- duplicate idempotency returns the original receipt;
- missing/invalid/mismatched Workspace rejects before receipt creation;
- Permission Gate rejects new Work while status, permission response, and cancellation remain available;
- `get_work_status(None)` selects active Work, otherwise the most recent Work;
- ambiguous or unknown Work reference returns a bounded error without mutation;
- queued cancellation becomes `cancelled` without ACP cancel;
- running cancellation enters `cancelling`, sends ACP cancel once, and becomes `cancelled` only after prompt confirmation;
- ACP refusal/process/transport failure becomes `failed` with one fixed safe error;
- a follow-up creates a new receipt and reuses the same open ACP session;
- local restart recovery fails every nonterminal receipt;
- workspace replacement and clear return `409` while any Work or permission is nonterminal.

- [ ] **Step 3: Run the runtime tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_runtime.py tests/acp_runtime/test_workspace_routes.py -q
```

Expected: fails because `TaskRuntime` is not implemented and the existing switch guard always allows changes.

- [ ] **Step 4: Implement the runtime worker**

Use one `asyncio.Queue[str]`, one worker task, and one lifecycle lock. `start()` must call `store.recover_nonterminal(...)` before creating the worker. `start_work()` must:

1. validate a ready Workspace whose ID matches the active ACP session;
2. reject an empty objective or an objective over 16 KiB UTF-8;
3. reject while `PermissionBroker.has_pending(...)` is true;
4. call `store.create_or_get(...)` and return an existing duplicate immediately;
5. enqueue only a newly created Work ID;
6. return the persisted queued receipt without yielding to ACP execution.

The worker must transition `queued -> starting -> running`, install an observer tied to the Work ID, await `acp.prompt`, and then:

- map `end_turn` with nonempty final text to `completed` and store `FinalPresentation(speech=text, inline=text)` plus `pending_delivery`;
- map confirmed `cancelled` to `cancelled` when state is `cancelling`;
- map refusal, malformed completion, or adapter failure to `failed` with `The coding Agent could not complete this Work.`;
- append only bounded activity emitted by the observer;
- continue to the next queued Work after every terminal result.

`close()` must stop acceptance, resolve a Pending Permission as cancelled, send ACP cancel for the active prompt, and wait up to two seconds for prompt confirmation. If confirmation does not arrive, cancel the worker task and transactionally mark every remaining nonterminal receipt `failed` with `Local Runner stopped before Work completed.`. It must never leave a receipt in `starting`, `running`, `awaiting_permission`, or `cancelling`.

The observer must transition `running -> awaiting_permission`, delegate to the Permission Broker, then transition back to `running` only after a decision or directly into `cancelling` when Work cancellation resolves the permission.

- [ ] **Step 5: Wire the live Workspace switch guard**

Implement:

```python
class TaskRuntimeWorkspaceSwitchGuard:
    def __init__(self, store: WorkStore, permissions: PermissionBroker) -> None:
        self._store = store
        self._permissions = permissions

    def check(self, previous: WorkspaceStatus, change: WorkspaceChange) -> str | None:
        if previous.workspace is None:
            return None
        if self._store.has_nonterminal(previous.workspace.id) or self._permissions.has_pending(previous.workspace.id):
            return "Wait for the current Work or permission decision before changing Project Folder."
        return None
```

Inject this guard into `build_workspace_router`; do not add task controls to the Settings UI.

- [ ] **Step 6: Run all core and ACP tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime tests/acp_runtime -q
```

Expected: all tests pass with fake ACP only.

- [ ] **Step 7: Commit the serial runtime**

```bash
git add server/src/task_runtime server/tests/task_runtime server/src/acp_runtime/routes.py server/tests/acp_runtime/test_workspace_routes.py
git commit -m "feat(server): coordinate serial background Work"
```

---

### Task 6: Compose lifecycle, verification, and maintained docs

**Files:**
- Modify: `server/src/server.py`
- Modify: `server/tests/acp_runtime/test_server_startup.py`
- Modify: `server/tests/conftest.py`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `AGENTS.md`
- Modify: `CONTEXT.md`
- Modify: `docs/ai/L0_repo_card.md`
- Modify: `docs/ai/L1/02_architecture.md`
- Modify: `docs/ai/L1/03_code_map.md`
- Modify: `docs/ai/L1/04_conventions.md`
- Modify: `docs/ai/L1/05_workflows.md`
- Modify: `docs/ai/L1/06_interfaces.md`
- Modify: `docs/ai/L1/07_gotchas.md`
- Modify: `docs/ai/L1/08_security.md`
- Modify: `docs/ai/L1/L2/acp_runtime.md`
- Modify: `docs/ai/L1/L2/verification_scripts.md`

**Interfaces:**
- Consumes: the completed Task Runtime Core and existing local-only app composition.
- Produces: one local lifecycle owner, a canonical offline verification command, and documentation that accurately distinguishes implemented core behavior from deferred MCP/UI/Speak behavior.

- [ ] **Step 1: Write failing composition tests**

Add tests proving:

```python
def test_public_app_does_not_construct_or_start_task_runtime(fake_env):
    app = create_app(enable_local_routes=False)
    assert all(route.path != "/local/work" for route in app.routes)


@pytest.mark.anyio
async def test_local_lifespan_recovers_work_before_acceptance(local_app, work_store):
    # Seed a running receipt before lifespan starts.
    receipt, _ = work_store.create_or_get("scope-a", "turn-a", "Run tests")
    work_store.transition(receipt.work_id, "starting")
    work_store.transition(receipt.work_id, "running")

    async with local_app.router.lifespan_context(local_app):
        assert work_store.get(receipt.work_id).state == "failed"
```

No HTTP Work routes are expected in this plan; the test protects against accidentally exposing an unauthenticated local or public control surface.

- [ ] **Step 2: Compose Task Runtime only for local mode**

Construct `WorkStore`, `PermissionBroker`, and `TaskRuntime` in a local composition object injected into `create_app(enable_local_routes=True)`. Its lifespan order must be:

1. `task_runtime.start()` to recover durable nonterminal receipts and start the idle worker;
2. serve requests;
3. `task_runtime.close()` to stop acceptance, cancel/settle the worker, and persist safe terminal state;
4. `local_runtime.close()` to close the ACP session and child process;
5. close the SQLite connection.

`create_app(enable_local_routes=False)` must not mount routes, start a worker, open SQLite, or construct public MCP state.

- [ ] **Step 3: Add the canonical verification entry**

Extend `verify:backend` to include `tests/task_runtime`:

```json
"verify:backend": "cd server && source venv/bin/activate && python -m compileall -q src && PYTHONPATH=src pytest tests/architecture_validation tests/acp_runtime tests/task_runtime -q"
```

Do not add live ACP, Codex, Agora, browser login, ngrok, or native picker execution to CI.

- [ ] **Step 4: Update maintained documentation**

Document exactly:

- Task Runtime Core is implemented and offline-tested;
- it persists Work, serializes ACP prompts, correlates current-operation permission, confirms cancellation, and stores safe completion text;
- no MCP Work ingress, SSE Activity Panel, Agora Speak delivery, or ngrok launcher integration exists yet;
- pressing **Start conversation** still does not make the ordinary managed Agent delegate real coding Work until the next MCP plan is complete;
- Project Folder remains context, never a sandbox;
- `Last Reviewed` becomes `2026-08-19`.

Add these domain terms to `CONTEXT.md`: `Work`, `Work Receipt`, `Pending Permission`, `Final Presentation`, and `Task Runtime`.

- [ ] **Step 5: Run the complete offline release suite**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q
cd ../web
bun test
cd ..
bun run verify:launcher
bun run verify:local
bun run verify:web
git diff --check
```

Expected: all suites, proxy smoke checks, launcher checks, lint, and production builds pass without real ACP, Agora, ngrok, or conversation minutes.

- [ ] **Step 6: Commit composition and docs**

```bash
git add server/src/server.py server/tests package.json README.md ARCHITECTURE.md AGENTS.md CONTEXT.md docs/ai
git commit -m "feat(server): compose local Task Runtime core"
```

---

## Deferred Follow-On Plans

1. **Authenticated MCP and Managed Voice wiring:** production capability registry, four Streamable HTTP tools, public ingress isolation, dynamic permission context, and current agent-session binding.
2. **Read-only activity experience:** Workspace-scoped history query, SSE replay, safe Markdown projection, and the collapsible non-mutating panel.
3. **Result delivery:** deterministic 512-byte Speech Projection, Announcement Window, batching, Agora Speak calls, retry/unknown states, and delivery deduplication.
4. **Launcher and live qualification:** ngrok readiness/auth, public route allowlist, one-command orchestration, routing corpus, and explicitly authorized macOS live E2E.

This plan is complete when fake ACP proves durable acceptance, FIFO background execution, safe activity, explicit current-operation permission, confirmed cancellation, completion persistence, restart reconciliation, and Workspace switch blocking. It does not claim end-to-end Voice-to-ACP completion.
