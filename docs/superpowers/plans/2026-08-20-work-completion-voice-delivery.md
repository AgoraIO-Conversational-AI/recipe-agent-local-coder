# Work Completion Voice Delivery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proactively speak completed and failed local Work results through the exact originating active Agora Agent session without duplicate or cross-session delivery.

**Architecture:** Persist the originating Agora Agent ID on each Work receipt, emit a non-blocking terminal callback after authoritative state commits, and let one thin Managed-ingress delivery coordinator claim and speak pending results. Reuse `Agent` as the sole session owner and the existing delivery-state vocabulary; do not add another registry, second LLM turn, retry loop, browser surface, or cross-session replay.

**Tech Stack:** Python 3.10+, asyncio, sqlite3, FastAPI lifespan composition, Agora Agent SDK `AsyncAgentSession.say`, pytest with fake ACP/Agora boundaries.

## Global Constraints

- Announce `completed` and `failed`; never announce `cancelled`.
- Deliver only to the persisted originating `agora_agent_id` while that exact Work-capable session remains active and the current Workspace ID still matches.
- Use `priority="APPEND"` and `interruptable=True`.
- `accepted` means the Agora Speak request returned successfully, not that playback completed.
- Do not automatically retry `delivery_unknown`.
- Do not scan or replay historical `pending_delivery` receipts on startup.
- Do not add routes, MCP tools, SSE, UI, environment variables, model changes, prompt changes, or Workspace-path exposure.
- Keep all automated checks offline; no Agora conversation, ngrok tunnel, or real ACP child may start.
- Use `apply_patch` for edits and conventional commits without AI attribution.

---

## File Structure

- Modify `server/src/task_runtime/models.py`: add private receipt target field.
- Modify `server/src/task_runtime/store.py`: migrate schema, persist the target, and own compare-and-set delivery transitions.
- Modify `server/src/task_runtime/runtime.py`: accept the target and emit non-blocking terminal notifications after commits.
- Create `server/src/managed_ingress/delivery.py`: one queue-based delivery coordinator and narrow session/workspace ports.
- Modify `server/src/agent.py`: expose exact Work-session availability and speech without duplicating session ownership.
- Modify `server/src/managed_ingress/tools.py`: pass the authenticated Agent ID into Task Runtime.
- Modify `server/src/server.py`: compose and lifecycle-manage the coordinator.
- Modify `server/src/managed_ingress/__init__.py`: export the delivery coordinator if package conventions require it.
- Modify `server/tests/task_runtime/test_store.py`: migration, private target, and delivery CAS coverage.
- Modify `server/tests/task_runtime/test_runtime.py`: terminal callback timing and state coverage.
- Modify `server/tests/managed_ingress/test_tools.py`: authenticated target propagation and public projection privacy.
- Modify `server/tests/managed_ingress/test_agent_bridge.py`: exact active-session speech behavior.
- Create `server/tests/managed_ingress/test_delivery.py`: coordinator success, failure, mismatch, duplicate, and shutdown behavior.
- Modify `server/tests/managed_ingress/test_server_composition.py`: local composition and lifecycle coverage.
- Update `README.md`, `ARCHITECTURE.md`, `AGENTS.md`, `docs/ai/L0_repo_card.md`, `docs/ai/L1/02_architecture.md`, `docs/ai/L1/05_workflows.md`, `docs/ai/L1/06_interfaces.md`, `docs/ai/L1/07_gotchas.md`, and `docs/ai/L1/L2/acp_runtime.md`: replace the deferred proactive-delivery claim with the implemented active-session boundary.

---

### Task 1: Persist the private delivery target and atomic delivery states

**Files:**
- Modify: `server/src/task_runtime/models.py`
- Modify: `server/src/task_runtime/store.py`
- Test: `server/tests/task_runtime/test_store.py`

**Interfaces:**
- Produces: `WorkReceipt.delivery_agent_id: str | None`.
- Produces: `WorkStore.create_or_get(workspace_id, idempotency_key, objective, delivery_agent_id=None)`.
- Produces: `claim_delivery`, `release_delivery`, `mark_delivery_accepted`, and `mark_delivery_unknown`, each accepting `work_id: str` and returning `WorkReceipt | None`.
- Preserves: an idempotent duplicate keeps the original `delivery_agent_id` and never retargets existing Work.

- [ ] **Step 1: Write failing store tests for target persistence and idempotency**

Add tests that create targeted Work, reopen the database, and prove the private target survives. Add a duplicate call with the same Workspace/idempotency key but a different Agent ID and assert the original target remains:

```python
receipt, created = store.create_or_get(
    "scope-a", "turn-1", "Inspect", delivery_agent_id="agent-a"
)
duplicate, duplicate_created = store.create_or_get(
    "scope-a", "turn-1", "Different", delivery_agent_id="agent-b"
)

assert created is True
assert duplicate_created is False
assert receipt.delivery_agent_id == "agent-a"
assert duplicate.delivery_agent_id == "agent-a"
```

- [ ] **Step 2: Write failing schema-upgrade test**

Create a version-`1.0` SQLite fixture with the preceding `works` columns, open
it through `WorkStore`, and assert `delivery_agent_id` exists while metadata
remains `1.0` and the existing receipt is preserved. Use SQLite
`PRAGMA table_info(works)` and an insert containing only the old column list to
prove the preceding artifact can still write after rollback.

- [ ] **Step 3: Write failing compare-and-set tests**

Drive one receipt to `pending_delivery`, then assert:

```python
claimed = store.claim_delivery(receipt.work_id)
assert claimed.delivery_state == "sending"
assert store.claim_delivery(receipt.work_id) is None
assert store.release_delivery(receipt.work_id).delivery_state == "pending_delivery"
assert store.claim_delivery(receipt.work_id).delivery_state == "sending"
assert store.mark_delivery_accepted(receipt.work_id).delivery_state == "accepted"
assert store.mark_delivery_unknown(receipt.work_id) is None
```

Use a second receipt to prove `sending -> delivery_unknown`; prove operations from every invalid source state return `None` and never mutate the row.

- [ ] **Step 4: Run the store tests and confirm RED**

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/task_runtime/test_store.py
```

Expected: failures for the absent target column, migration, and delivery methods.

- [ ] **Step 5: Implement the receipt field and schema migration**

Add the dataclass field:

```python
@dataclass(frozen=True)
class WorkReceipt:
    # existing fields
    delivery_agent_id: str | None = None
    delivery_state: DeliveryState = "not_ready"
```

Keep `_SCHEMA_VERSION` at `"1.0"` and add the nullable column exactly once when
absent. This additive migration lets the preceding `1.0` artifact ignore the
column during rollback. Reject every unsupported metadata version. New
databases create the column directly.

Normalize a non-null target with `_bounded(..., name="delivery_agent_id", max_bytes=128)`. Insert it only for new Work. Include it in `_receipt()`; never include it in activity or public projections.

- [ ] **Step 6: Implement atomic delivery transitions**

Use conditional SQL updates and `cursor.rowcount`, not read-then-write state mutation:

```python
def _change_delivery(
    self, work_id: str, source: DeliveryState, target: DeliveryState
) -> WorkReceipt | None:
    with self._connection:
        cursor = self._connection.execute(
            """
            UPDATE works SET delivery_state = ?, updated_at = ?
            WHERE work_id = ? AND delivery_state = ?
            """,
            (target, _now(), work_id, source),
        )
    return self.get(work_id) if cursor.rowcount == 1 else None
```

Expose the four named methods with the source/target pairs from the approved design.

When `transition(..., target="failed")` stores a safe error for targeted Work, set `delivery_state='pending_delivery'` in the same transaction. Untargeted failure remains `not_ready`; cancellation never becomes pending.

- [ ] **Step 7: Run the store tests and confirm GREEN**

Run the Step 4 command. Expected: all store tests pass.

- [ ] **Step 8: Commit Task 1**

```bash
git add server/src/task_runtime/models.py server/src/task_runtime/store.py server/tests/task_runtime/test_store.py
git commit -m "feat(server): persist Work delivery state"
```

---

### Task 2: Emit terminal Work notifications after authoritative commits

**Files:**
- Modify: `server/src/task_runtime/runtime.py`
- Test: `server/tests/task_runtime/test_runtime.py`

**Interfaces:**
- Consumes: targeted `WorkStore.create_or_get(...)` from Task 1.
- Produces: `TerminalWorkCallback = Callable[[str], None]`.
- Produces: `TaskRuntime.set_terminal_callback(callback: TerminalWorkCallback | None) -> None`.
- Changes: `TaskRuntime.start_work(objective, idempotency_key, delivery_agent_id=None)`.

- [ ] **Step 1: Write a failing completed-Work callback test**

Install a recording callback before `runtime.start()`, start targeted Work, complete fake ACP, and assert the callback observes exactly one ID only after the store reports both `completed` and `pending_delivery`:

```python
observed = []

def terminal(work_id: str) -> None:
    receipt = context.store.get(work_id)
    observed.append((work_id, receipt.state, receipt.delivery_state))

context.runtime.set_terminal_callback(terminal)
accepted = await context.runtime.start_work(
    "Run tests", "turn-1", delivery_agent_id="agent-a"
)
context.acp.complete("Passed")

await wait_until(lambda: len(observed) == 1, "terminal callback")
assert observed == [(accepted.work_id, "completed", "pending_delivery")]
```

- [ ] **Step 2: Write failing failure/cancellation/duplicate tests**

Prove a targeted ACP failure emits once after safe error persistence, cancellation emits zero times, and an idempotent duplicate submission does not install another target or terminal callback.

- [ ] **Step 3: Run focused runtime tests and confirm RED**

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/task_runtime/test_runtime.py
```

Expected: failures for missing callback/target parameters and failed delivery state.

- [ ] **Step 4: Implement the callback seam**

Add the optional callback field and setter. Pass `delivery_agent_id` into `create_or_get`. Invoke a private non-awaiting helper only after the final state transaction returns:

```python
def _notify_terminal(self, receipt: WorkReceipt) -> None:
    if self._terminal_callback is not None:
        self._terminal_callback(receipt.work_id)
```

For completion, call it after `save_final` and `transition(..., "completed")`. Refactor `_fail_work()` to retain the returned failed receipt and notify only when this invocation performed the terminal transition. Do not call it for terminal no-ops, cancellation, restart recovery, or runtime shutdown recovery.

- [ ] **Step 5: Run runtime and store tests and confirm GREEN**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/task_runtime/test_runtime.py tests/task_runtime/test_store.py
```

- [ ] **Step 6: Commit Task 2**

```bash
git add server/src/task_runtime/runtime.py server/tests/task_runtime/test_runtime.py
git commit -m "feat(server): publish terminal Work events"
```

---

### Task 3: Add the exact Agent-owned speech seam and authenticated target propagation

**Files:**
- Modify: `server/src/agent.py`
- Modify: `server/src/managed_ingress/tools.py`
- Test: `server/tests/managed_ingress/test_agent_bridge.py`
- Test: `server/tests/managed_ingress/test_tools.py`

**Interfaces:**
- Consumes: `CapabilityBinding.agora_agent_id` and Task 2's targeted `start_work`.
- Produces: `Agent.has_work_session(agent_id: str) -> bool`.
- Produces: `Agent.say_work_result(agent_id: str, text: str) -> bool`, where `False` proves no Work-capable session was present before submission and an exception means submission outcome is unknown.

- [ ] **Step 1: Write failing Agent speech tests**

Extend the fake Managed Agent session with a recording `say()` method. After normal Work-mode Agent startup, assert:

```python
assert instance.has_work_session("agent-a") is True
submitted = asyncio.run(instance.say_work_result("agent-a", "Tests passed"))
assert submitted is True
assert session.say_calls == [
    ("Tests passed", "APPEND", True),
]
```

After `instance.stop("agent-a")`, assert `has_work_session` is false and `say_work_result` returns false without touching the stopped session. Also prove a baseline/evidence session without `_work_leases[agent_id]` is never eligible.

- [ ] **Step 2: Write failing ManagedWorkTools target/privacy test**

Update the fake runtime to record its `delivery_agent_id` argument. Call `start_work` with a binding for `agent-a`, assert the runtime receives `agent-a`, and assert the returned MCP projection contains no `delivery_agent_id` or Agora Agent identifier.

- [ ] **Step 3: Run focused Managed-ingress tests and confirm RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q \
  tests/managed_ingress/test_agent_bridge.py \
  tests/managed_ingress/test_tools.py
```

- [ ] **Step 4: Implement exact session speech**

Add methods that require both the live session and its Work lease:

```python
def has_work_session(self, agent_id: str) -> bool:
    return agent_id in self._sessions and agent_id in self._work_leases

async def say_work_result(self, agent_id: str, text: str) -> bool:
    session = self._sessions.get(agent_id)
    if session is None or agent_id not in self._work_leases:
        return False
    await session.say(text, priority="APPEND", interruptable=True)
    return True
```

Do not log the text or Agent ID as part of the delivery content. Existing detach/revoke order remains unchanged.

- [ ] **Step 5: Pass the authenticated target into Task Runtime**

Change only the internal call:

```python
receipt = await self._runtime.start_work(
    objective,
    idempotency_key,
    delivery_agent_id=binding.agora_agent_id,
)
```

Do not add the ID to any MCP result.

- [ ] **Step 6: Run focused tests and confirm GREEN**

Run the Step 3 command.

- [ ] **Step 7: Commit Task 3**

```bash
git add server/src/agent.py server/src/managed_ingress/tools.py \
  server/tests/managed_ingress/test_agent_bridge.py \
  server/tests/managed_ingress/test_tools.py
git commit -m "feat(server): bind Work to its voice session"
```

---

### Task 4: Deliver terminal results through one thin coordinator

**Files:**
- Create: `server/src/managed_ingress/delivery.py`
- Modify: `server/src/managed_ingress/__init__.py`
- Create: `server/tests/managed_ingress/test_delivery.py`

**Interfaces:**
- Consumes: WorkStore CAS methods from Task 1, terminal IDs from Task 2, and Agent speech methods from Task 3.
- Produces: `WorkDeliveryCoordinator(store, sessions, workspace)`.
- Produces: async `start()`, sync `notify(work_id)`, and async `close()`.

- [ ] **Step 1: Write the failing success test**

Create fakes with `has_work_session`, `say_work_result`, and
`current_workspace_identity`. Persist one targeted completed receipt, start the
coordinator, call `notify`, and await `accepted`:

```python
coordinator.notify(receipt.work_id)
await wait_until(
    lambda: store.get(receipt.work_id).delivery_state == "accepted",
    "delivery accepted",
)
assert sessions.say_calls == [
    ("agent-a", "Tests passed"),
]
```

The fake session method itself records that the production caller requested
APPEND/interruptable behavior in Task 3; this test focuses on coordinator
selection and state.

- [ ] **Step 2: Write failing failure-result and guard tests**

Cover:

- failed targeted receipt speaks the bounded stored error and reaches
  `accepted`;
- cancelled receipt never speaks;
- absent exact session leaves `pending_delivery`;
- Workspace ID mismatch leaves `pending_delivery`;
- duplicate `notify()` calls produce one speech call;
- `say_work_result()` returns `False` after claim, causing
  `release_delivery()` back to `pending_delivery`;
- `say_work_result()` raises after submission begins, causing
  `delivery_unknown` and no retry;
- already `accepted` or `delivery_unknown` receipts are ignored.

- [ ] **Step 3: Write failing lifecycle test**

Block fake `say_work_result`, call `close()`, and assert the claimed receipt ends
as `delivery_unknown`, the worker ends, and later `notify()` calls are ignored.
Also prove `notify()` before `start()` is ignored rather than accumulating an
implicit startup replay.

- [ ] **Step 4: Run the new tests and confirm RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/managed_ingress/test_delivery.py
```

- [ ] **Step 5: Implement narrow protocols and coordinator lifecycle**

Define:

```python
class DeliverySessionPort(Protocol):
    def has_work_session(self, agent_id: str) -> bool: ...
    async def say_work_result(self, agent_id: str, text: str) -> bool: ...

class DeliveryWorkspacePort(Protocol):
    def current_workspace_identity(self) -> tuple[str, int] | None: ...
```

The coordinator owns `asyncio.Queue[str]`, one worker task, `_accepting`, and
`_active_work_id`. `notify()` uses `put_nowait` only while accepting. `start()`
does not scan the store.

- [ ] **Step 6: Implement guarded delivery**

Choose speech deterministically:

```python
if receipt.state == "completed" and receipt.final_presentation is not None:
    speech = receipt.final_presentation.speech
elif receipt.state == "failed" and receipt.error:
    speech = receipt.error
else:
    return
```

Check Workspace and `has_work_session` before claim. After claim, recheck both;
if either is false, release to pending. Await `say_work_result`; `False` releases
to pending, normal return marks accepted, and any exception marks unknown while
logging only `error_type` and `work_id`-free fixed context.

In a worker-cancellation `finally`, mark the active `sending` receipt unknown.
Never enqueue a retry.

- [ ] **Step 7: Run coordinator plus all Managed-ingress tests and confirm GREEN**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/managed_ingress
```

- [ ] **Step 8: Commit Task 4**

```bash
git add server/src/managed_ingress/delivery.py \
  server/src/managed_ingress/__init__.py \
  server/tests/managed_ingress/test_delivery.py
git commit -m "feat(server): announce terminal Work results"
```

---

### Task 5: Compose lifecycle, update maintained docs, and verify offline

**Files:**
- Modify: `server/src/server.py`
- Modify: `server/tests/managed_ingress/test_server_composition.py`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `AGENTS.md`
- Modify: `docs/ai/L0_repo_card.md`
- Modify: `docs/ai/L1/02_architecture.md`
- Modify: `docs/ai/L1/05_workflows.md`
- Modify: `docs/ai/L1/06_interfaces.md`
- Modify: `docs/ai/L1/07_gotchas.md`
- Modify: `docs/ai/L1/L2/acp_runtime.md`

**Interfaces:**
- Consumes: `WorkDeliveryCoordinator` and `TaskRuntime.set_terminal_callback`.
- Produces: local-app-only coordinator lifecycle; default/public app behavior remains unchanged.

- [ ] **Step 1: Extend the app-factory test seam**

In `server/tests/managed_ingress/test_server_composition.py`, extend the fake
lifecycle events and add failing assertions that:

- default `create_app(enable_local_routes=False)` has no delivery coordinator;
- local Managed mode constructs one coordinator;
- lifespan starts coordinator before Task Runtime accepts Work;
- shutdown closes delivery before Agent sessions and the Work store;
- local fake startup performs no `say()` and no historical pending replay.

- [ ] **Step 2: Run the app-factory test and confirm RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q tests/managed_ingress/test_server_composition.py
```

- [ ] **Step 3: Compose the coordinator**

In `create_app`, after constructing `managed_agent`, create:

```python
work_delivery = WorkDeliveryCoordinator(
    store=work_store,
    sessions=managed_agent,
    workspace=managed_ingress,
)
task_runtime.set_terminal_callback(work_delivery.notify)
```

Store it only as an internal app-state diagnostic if tests need lifecycle
access; do not expose a route. In lifespan, start delivery before Task Runtime.
During shutdown, quiesce Managed ingress, close delivery, then retain the
existing inside-out Agent/ingress/Task Runtime/ACP/store cleanup order.

- [ ] **Step 4: Run the app-factory and full backend suites**

```bash
bun run verify:backend
bun run verify:local:fastapi
```

Expected: all offline Python and fake FastAPI tests pass; no live service is
contacted.

- [ ] **Step 5: Update maintained documentation**

Document precisely:

- active exact-session completed/failed speech is implemented;
- `accepted` is API acceptance, not playback proof;
- stopped session or Workspace mismatch retains `pending_delivery`;
- `delivery_unknown` is not retried;
- status lookup remains the fallback;
- cross-session replay, UI/SSE, playback receipt, batching, and proactive
  permission remain deferred.

Keep `Last Reviewed` in `docs/ai/L0_repo_card.md` as the plain date
`2026-08-20`, while updating its summary text.

- [ ] **Step 6: Run repository-wide offline verification**

```bash
git diff --check
bun run verify:local
bun run verify:launcher
```

Expected: backend tests, fake FastAPI, proxy checks, Next production build, and
launcher cleanup checks pass without starting an Agora conversation.

- [ ] **Step 7: Inspect the final diff for forbidden scope**

```bash
git diff --name-only 7c0dfc2..HEAD
rg -n "delivery_agent_id" web server/src/managed_ingress/tools.py
git status --short
```

Confirm there is no new browser route/UI, fifth MCP tool, model/prompt change,
Workspace path projection, automatic retry, or live-evidence claim.

- [ ] **Step 8: Commit Task 5**

```bash
git add server/src/server.py server/tests README.md ARCHITECTURE.md AGENTS.md \
  docs/ai/L0_repo_card.md docs/ai/L1/02_architecture.md \
  docs/ai/L1/05_workflows.md \
  docs/ai/L1/06_interfaces.md docs/ai/L1/07_gotchas.md \
  docs/ai/L1/L2/acp_runtime.md
git commit -m "docs: document Work completion delivery"
```

- [ ] **Step 9: Run the required two-axis review**

Use the `code-review` skill against fixed point `7c0dfc2`,
with the approved design at
`docs/superpowers/specs/2026-08-20-work-completion-voice-delivery-design.md` as
the Spec source. Resolve every actionable Standards or Spec finding, rerun the
affected focused tests, and commit follow-up fixes conventionally.

- [ ] **Step 10: Report the live acceptance boundary**

State that offline implementation is complete. Do not claim Agora Speak works
live until the user separately authorizes one minute-consuming conversation
that completes targeted Work and receives one proactive spoken result.
