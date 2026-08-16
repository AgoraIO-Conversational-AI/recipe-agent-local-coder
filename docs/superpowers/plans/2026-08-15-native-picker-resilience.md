# Native Project Folder Picker Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the macOS Project Folder picker resilient to long user interaction, render bounded infrastructure errors, and close an already-disconnected ACP session without a traceback.

**Architecture:** Replace the long-running browse request with one in-memory loopback operation: POST starts the native picker and returns an opaque ID, while GET polls its terminal state. Preserve `browseWorkspace(): Promise<WorkspaceStatus>` by hiding polling inside the browser API client. Treat only a transport-level `ConnectionError` during `session/close` as an already-completed close and always exit the ACP child-process context.

**Tech Stack:** Python 3.10+, FastAPI, asyncio, Pydantic, ACP Python SDK 0.11.x, Next.js 16, React 19, Bun tests, pytest.

## Global Constraints

- Keep source, UI copy, tests, logs, configuration, and documentation in English.
- Keep `GET /api/get_config`, `POST /api/startAgent`, and `POST /api/stopAgent` unchanged.
- Keep all `/local/*` routes loopback-only and behind the explicit non-production local-runtime opt-in.
- Project Folder remains ACP session context, not a filesystem sandbox.
- Only one native picker operation may be active; retain only the current operation in memory.
- Never expose raw picker, proxy, ACP, authentication, command, environment, path, or private identifier errors.
- No test opens a real native picker, starts real Codex, authenticates, runs ngrok, starts an Agora agent, joins RTC/RTM, or consumes Agora minutes.

---

### Task 1: Asynchronous native picker operation

**Files:**

- Create: `server/src/acp_runtime/browse.py`
- Modify: `server/src/acp_runtime/routes.py`
- Modify: `server/src/server.py`
- Modify: `server/tests/acp_runtime/test_workspace_routes.py`
- Create: `server/tests/acp_runtime/test_browse.py`

**Interfaces:**

- Produces `BrowseOperationStatus(operation_id, state, workspace, error)` with states `picking`, `ready`, `cancelled`, and `failed`.
- Produces `WorkspaceBrowseCoordinator.start() -> BrowseOperationStatus` and `status(operation_id: str) -> BrowseOperationStatus`.
- Consumes a `DirectoryPicker` and an async `select_workspace(path: str) -> WorkspaceStatus` callback.
- `POST /local/workspace/browse` returns HTTP 202 immediately; `GET /local/workspace/browse/{operation_id}` returns the current status.

- [ ] **Step 1: Write the red coordinator test**

```python
@pytest.mark.anyio
async def test_start_returns_while_picker_is_still_waiting(project):
    picker = BlockingPicker()
    coordinator = WorkspaceBrowseCoordinator(picker, select_ready)

    started = coordinator.start()

    assert started.state == "picking"
    assert coordinator.status(started.operation_id).state == "picking"
    picker.complete(str(project))
    await coordinator.wait_for_test_completion()
    assert coordinator.status(started.operation_id).state == "ready"
```

The test fake uses an `asyncio.Event`; no sleep, native UI, subprocess, or network is allowed. Add parallel tests for cancellation, selection failure with a fixed message, unknown operation ID, and a second active start.

- [ ] **Step 2: Run the focused test and verify RED**

Run:

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/acp_runtime/test_browse.py -q
```

Expected: collection fails because `acp_runtime.browse` does not exist.

- [ ] **Step 3: Implement the minimal coordinator**

```python
@dataclass(frozen=True)
class BrowseOperationStatus:
    operation_id: str
    state: Literal["picking", "ready", "cancelled", "failed"]
    workspace: WorkspaceStatus | None = None
    error: str | None = None

class WorkspaceBrowseCoordinator:
    def start(self) -> BrowseOperationStatus:
        if self._task is not None and not self._task.done():
            raise BrowseAlreadyActive("A Project Folder picker is already open")
        operation_id = secrets.token_urlsafe(18)
        self._status = BrowseOperationStatus(operation_id, "picking")
        self._task = asyncio.create_task(self._run(operation_id))
        return self._status
```

`_run` awaits the picker callback, maps `None` to `cancelled`, calls the injected selection callback, and stores only bounded fixed failure messages. A result from an obsolete operation ID must not overwrite the current status.

- [ ] **Step 4: Convert the browse routes and keep manual PUT synchronous**

`build_workspace_router` constructs or receives the coordinator. POST returns `_data_envelope(asdict(operation))` with status 202. GET validates the opaque ID and returns the same envelope. The selection callback reuses the current switch guard, persistence, activation, and rollback behavior; it returns `WorkspaceStatus`, not an HTTP envelope.

Add route tests proving POST completes before a blocked picker, GET transitions to ready, remote peers receive 403 on both endpoints, cancellation is a terminal operation state, and manual PUT behavior is unchanged.

- [ ] **Step 5: Run backend tests and commit**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/acp_runtime/test_browse.py tests/acp_runtime/test_workspace_routes.py -q
cd ..
git add server/src/acp_runtime server/src/server.py server/tests/acp_runtime
git commit -m "fix: decouple native picker request"
```

---

### Task 2: Browser polling and bounded response parsing

**Files:**

- Modify: `web/src/services/api.ts`
- Modify: `web/src/services/api.test.ts`
- Modify: `web/next.config.ts`
- Modify: `web/next.config.test.ts`
- Modify: `web/scripts/verify-api-contracts.ts`
- Modify: `web/scripts/verify-local-proxy.ts`
- Modify: `web/scripts/verify-local-fastapi.ts`

**Interfaces:**

- Consumes the Task 1 start/status routes.
- Preserves `browseWorkspace(options?) -> Promise<WorkspaceStatus>`.
- Adds `BrowseWorkspaceOptions { pollIntervalMs?: number; signal?: AbortSignal }` so tests use zero delay and callers may cancel polling.
- `readLocalResponse<T>` accepts JSON success/error envelopes and produces bounded fallback errors for non-JSON responses.

- [ ] **Step 1: Write the red public API tests**

```typescript
test('browseWorkspace polls a background picker operation', async () => {
  mockFetchSequence(
    jsonResponse(202, { code: 0, data: { operation_id: 'op-a', state: 'picking' } }),
    jsonResponse(200, { code: 0, data: { operation_id: 'op-a', state: 'picking' } }),
    jsonResponse(200, { code: 0, data: { operation_id: 'op-a', state: 'ready', workspace: READY_WORKSPACE } }),
  )
  expect(await browseWorkspace({ pollIntervalMs: 0 })).toEqual(READY_WORKSPACE)
})

test('local helpers bound a plain-text proxy failure', async () => {
  mockRawFetch(500, 'Internal Server Error', 'text/plain')
  await expect(getWorkspace()).rejects.toThrow('HTTP 500')
  await expect(getWorkspace()).rejects.not.toThrow('Unexpected token')
})
```

Also cover `cancelled`, `failed`, and `AbortSignal` without real timers or network.

- [ ] **Step 2: Run and verify RED**

Run: `cd web && bun test src/services/api.test.ts`

Expected: polling test sees the old one-request implementation and the plain-text test throws a JSON parser error.

- [ ] **Step 3: Implement safe parsing and internal polling**

```typescript
async function readLocalPayload(response: Response, fallback: string) {
  const text = await response.text()
  let payload: LocalEnvelope | null = null
  try { payload = JSON.parse(text) } catch { /* bounded below */ }
  if (!response.ok) throw new Error(payload?.detail || `HTTP ${response.status}`)
  if (!payload?.data || payload.code !== 0) throw new Error(payload?.msg || fallback)
  return payload.data
}
```

POST once, poll `/api/local/workspace/browse/${encodeURIComponent(operationId)}`, return the terminal Workspace, and translate cancellation/failure into their bounded status error. Use an abort-aware delay helper.

- [ ] **Step 4: Add the dynamic local rewrite and contract checks**

Add `/api/local/workspace/browse/:operationId` only under the same loopback, explicit-opt-in, non-production conditions as the existing local rewrites. Verify exact start/status request shapes, terminal transitions, non-JSON failure handling, and the fake FastAPI start/poll path.

- [ ] **Step 5: Run web verification and commit**

```bash
cd web
bun test
bun run verify:api
bun run build
cd ..
bun run verify:web:proxy
git add web
git commit -m "fix: poll native picker completion"
```

---

### Task 3: Idempotent ACP close on a disconnected transport

**Files:**

- Modify: `server/src/acp_runtime/codex.py`
- Modify: `server/tests/acp_runtime/fake_acp_agent.py`
- Modify: `server/tests/acp_runtime/test_acp_client.py`

**Interfaces:**

- Preserves `CodexAcpClient.close() -> None`.
- Treats only `ConnectionError` raised by `connection.close_session` as an already-completed session close.
- Always invokes the process context's `__aexit__` exactly once; repeated calls remain no-ops.

- [ ] **Step 1: Write the failing transport regression**

Extend the repository fake ACP agent with a mode that creates a session, records completion, and closes its transport before the client calls `close()`.

```python
@pytest.mark.anyio
async def test_close_cleans_process_when_session_transport_already_closed(fake_agent, project):
    client = CodexAcpClient(command=fake_agent.command_closing_after_session)
    await client.open(str(project))
    await fake_agent.wait_until_transport_closed()

    await client.close()
    await client.close()

    assert fake_agent.process_exited
```

- [ ] **Step 2: Run and verify RED**

Run: `cd server && source venv/bin/activate && PYTHONPATH=src pytest tests/acp_runtime/test_acp_client.py -q`

Expected: `client.close()` raises `ConnectionError("Connection closed")`.

- [ ] **Step 3: Apply the narrow idempotency rule**

```python
try:
    if connection is not None and session_id is not None:
        try:
            await connection.close_session(session_id)
        except ConnectionError:
            pass
finally:
    await process_context.__aexit__(None, None, None)
```

Do not catch ACP request errors, process-context failures, or arbitrary exceptions.

- [ ] **Step 4: Run backend and full offline regression**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/acp_runtime/test_acp_client.py -q
PYTHONPATH=src pytest -q
cd ..
bun test --cwd web
bun run verify:local
git diff --check
```

- [ ] **Step 5: Update maintained contracts and commit**

Update `README.md`, `ARCHITECTURE.md`, `docs/ai/L1/06_interfaces.md`, `docs/ai/L1/L2/acp_runtime.md`, and verification documentation for the asynchronous picker start/status contract. Clearly retain real picker and Agora checks as manual/live boundaries.

```bash
git add server README.md ARCHITECTURE.md docs/ai
git commit -m "fix: close disconnected acp sessions cleanly"
```

## Plan self-review

- Spec coverage: Task 1 removes the unbounded proxied request, Task 2 prevents raw JSON parser failures and keeps the UI contract stable, and Task 3 removes the observed shutdown traceback without hiding unrelated failures.
- Placeholder scan: no unresolved markers or unspecified implementation steps remain.
- Type consistency: `BrowseOperationStatus`, `operation_id`, `WorkspaceStatus`, and `BrowseWorkspaceOptions` are consistent between route and browser tasks.
- Scope: native picker resilience only; no Task Runtime, Agora conversation, permission UI, multi-operation history, SSE, WebSocket, or public deployment behavior is added.
