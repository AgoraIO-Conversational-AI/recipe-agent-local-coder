# Managed MCP and ngrok Ingress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `subagent-driven-development` (recommended) or inline TDD to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the existing local Task Runtime callable by Agora's Managed Voice LLM through a launcher-owned, authenticated ngrok MCP ingress.

**Architecture:** Add a production-only `managed_ingress` package containing capability, tool, HTTP/MCP, tunnel, and lifecycle modules. The local FastAPI app owns the package and injects a narrow bridge into `Agent`; the stable public quickstart path and the synthetic architecture-validation harness remain independent. ngrok exposes only a dedicated loopback MCP listener, while ACP remains local stdio.

**Tech Stack:** Python 3.10+, FastAPI/ASGI, FastMCP Streamable HTTP, SQLite-backed `TaskRuntime`, `httpx`, ngrok CLI subprocess, pytest/AnyIO, Bun launcher verification.

## Global Constraints

- macOS Apple Silicon first; one active Work-capable Agora Agent and one selected Workspace.
- Keep Agora Managed Voice LLM; do not add Custom LLM or another model credential.
- Expose exactly `start_work`, `get_work_status`, `cancel_work`, and `respond_permission`.
- Use `Authorization: Bearer <per-Agent-capability>` on fixed `/mcp/`; never put the bearer in a URL, log, browser payload, `.env`, or SQLite.
- ngrok exposes only the dedicated MCP listener. It must never expose quickstart, local-control, validation, database, SSE, diagnostics, or LLM callback routes.
- Do not expose Workspace paths, ACP identifiers/options, exception text, command output, reasoning, or process data through MCP.
- Preserve same-key idempotency only. Do not claim exactly-once across independently generated model retries until Agora tool-call identity is verified live.
- No live Agora, ngrok, browser login, microphone, or real ACP calls in automated verification.
- A running Work survives voice-session or ngrok loss; voice barge-in never cancels Work.
- Keep all code, tests, UI copy, comments, and maintained project documentation in English.

---

### Task 1: Per-Agent Capability Registry and Budgets

**Files:**
- Create: `server/src/managed_ingress/__init__.py`
- Create: `server/src/managed_ingress/models.py`
- Create: `server/src/managed_ingress/capabilities.py`
- Create: `server/tests/managed_ingress/__init__.py`
- Create: `server/tests/managed_ingress/test_capabilities.py`

**Interfaces:**
- Produces: `CapabilityRegistry.prepare(workspace_id, workspace_generation) -> CapabilityLease`
- Produces: `CapabilityRegistry.activate(lease_id, agora_agent_id) -> CapabilityBinding`
- Produces: `CapabilityRegistry.resolve(bearer) -> CapabilityBinding | None`
- Produces: `CapabilityRegistry.revoke(lease_id)`, `revoke_active()`, and `active_binding()`
- Produces: `CapabilityRateLimiter.consume(credential_id, operation, now) -> None`

- [ ] **Step 1: Write failing capability tests**

Cover pending credentials, activation, constant-time bearer resolution, one active/reserved Agent, revocation, Workspace generation mismatch, and separate rate budgets:

```python
def test_pending_lease_is_not_authorized_until_exact_agent_activation():
    registry = CapabilityRegistry(token_factory=lambda: "secret-bearer")
    lease = registry.prepare("scope-a", 3)
    assert registry.resolve("secret-bearer") is None

    binding = registry.activate(lease.lease_id, "agora-agent-a")
    assert registry.resolve("secret-bearer") == binding
    assert binding.workspace_id == "scope-a"
    assert binding.workspace_generation == 3
    assert binding.agora_agent_id == "agora-agent-a"

    registry.revoke(lease.lease_id)
    assert registry.resolve("secret-bearer") is None
```

```python
def test_rate_limiter_uses_separate_public_budgets():
    limiter = CapabilityRateLimiter()
    for _ in range(10):
        limiter.consume("credential-a", "start_work", now=100.0)
    with pytest.raises(CapabilityLimitError, match="rate_limited"):
        limiter.consume("credential-a", "start_work", now=100.0)
    limiter.consume("credential-a", "get_work_status", now=100.0)
```

- [ ] **Step 2: Run tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_capabilities.py -q
```

Expected: collection fails because `managed_ingress` does not exist.

- [ ] **Step 3: Implement immutable leases and active bindings**

Use explicit types and keep the bearer only on the lease/private registry entry:

```python
@dataclass(frozen=True)
class CapabilityLease:
    lease_id: str
    bearer: str
    workspace_id: str
    workspace_generation: int
    issued_at: float


@dataclass(frozen=True)
class CapabilityBinding:
    credential_id: str
    workspace_id: str
    workspace_generation: int
    agora_agent_id: str
    issued_at: float
```

Generate the default bearer with `secrets.token_urlsafe(32)`. Compare bearer
digests with `hmac.compare_digest`; do not key a public/debug representation by
the plaintext token. Reject a second prepare while a lease or binding exists
with fixed error `voice_agent_already_active`.

Implement sliding one-minute counters with exact limits:

```python
RATE_LIMITS = {
    "start_work": 10,
    "get_work_status": 60,
    "cancel_work": 20,
    "respond_permission": 20,
}
```

- [ ] **Step 4: Run capability tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_capabilities.py -q
```

Expected: all capability tests pass.

- [ ] **Step 5: Commit**

```bash
git add server/src/managed_ingress server/tests/managed_ingress
git commit -m "feat(server): bind managed MCP capabilities"
```

---

### Task 2: Public Task Runtime Tool Adapter and Queue Budget

**Files:**
- Create: `server/src/managed_ingress/tools.py`
- Create: `server/tests/managed_ingress/test_tools.py`
- Modify: `server/src/task_runtime/store.py`
- Modify: `server/src/task_runtime/runtime.py`
- Modify: `server/tests/task_runtime/test_store.py`
- Modify: `server/tests/task_runtime/test_runtime.py`

**Interfaces:**
- Consumes: active `CapabilityBinding`, `CapabilityRateLimiter`, `TaskRuntime`, `WorkStore`
- Produces: `ManagedWorkTools` with four async methods named after the MCP tools
- Produces: `WorkStore.find_by_idempotency(workspace_id, idempotency_key) -> WorkReceipt | None`
- Produces: `WorkStore.queued_objective_bytes(workspace_id) -> int`
- Produces: Task Runtime fixed error `work_queue_budget_exceeded`

- [ ] **Step 1: Write failing Task Runtime budget tests**

Set `TaskRuntime(max_queued_objective_bytes=32)` and prove the first queued
objective is durable while a second over-budget objective creates no receipt:

```python
with pytest.raises(TaskRuntimeError, match="work_queue_budget_exceeded"):
    await runtime.start_work("x" * 32, "turn-over-budget")
assert store.queue_depth(workspace.id) == 1
```

Also test `queued_objective_bytes` decreases after a Work leaves `queued`.

- [ ] **Step 2: Run focused Task Runtime tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime/test_store.py tests/task_runtime/test_runtime.py -q
```

Expected: failures for missing queue-byte interface and constructor argument.

- [ ] **Step 3: Implement the 1 MiB default queue-byte guard**

Add one indexed lookup and one SQL aggregation over queued Work. Resolve an
existing same-key receipt first; only a new key checks the UTF-8 Objective size
before `create_or_get`. An existing receipt is therefore returned even if the
queue is currently full.

```python
MAX_QUEUED_OBJECTIVE_BYTES = 1024 * 1024
```

- [ ] **Step 4: Write failing production tool tests**

Use a real `TaskRuntime` with fake ACP and assert exact safe projections:

```python
result = await tools.start_work(
    binding=binding,
    objective="Run tests",
    idempotency_key="turn-1",
)
assert result == {
    "code": "work_accepted",
    "work_id": result["work_id"],
    "state": "queued",
}
assert "workspace_id" not in result
```

Cover duplicate keys, current/named status, bounded final presentation,
cancellation, allow/reject, missing permission, stale Workspace generation, and
mapping every `TaskRuntimeError`/`PermissionBrokerError` to fixed public codes.
Assert authorization IDs and option IDs never occur in serialized responses.

- [ ] **Step 5: Implement `ManagedWorkTools`**

Before every operation, consume the named per-capability rate budget and compare
the binding with the active Workspace and
generation supplied by a small `WorkspaceGenerationPort` protocol. Keep the
adapter stateless and do not import `architecture_validation`.

Use these response codes:

```text
work_accepted
work_already_accepted
work_found
work_not_found
work_cancelling
work_cancelled
permission_resolved
permission_not_found
permission_option_unavailable
permission_decision_required
workspace_not_ready
work_queue_budget_exceeded
runtime_unavailable
```

Limit serialized status output to 256 KiB by truncating only safe `inline`
content at UTF-8 boundaries and appending `Result shortened for voice status.`.

- [ ] **Step 6: Run adapter and Task Runtime tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/task_runtime tests/managed_ingress/test_tools.py -q
```

Expected: all tests pass with no Agora/ngrok/real ACP calls.

- [ ] **Step 7: Commit**

```bash
git add server/src/task_runtime server/src/managed_ingress/tools.py server/tests/task_runtime server/tests/managed_ingress/test_tools.py
git commit -m "feat(server): expose safe managed Work tools"
```

---

### Task 3: Isolated Authenticated MCP Application

**Files:**
- Create: `server/src/managed_ingress/http_policy.py`
- Create: `server/src/managed_ingress/mcp_app.py`
- Create: `server/src/managed_ingress/public_server.py`
- Create: `server/tests/managed_ingress/test_public_server.py`

**Interfaces:**
- Consumes: `CapabilityRegistry`, `CapabilityRateLimiter`, `ManagedWorkTools`
- Produces: `IngressHostPolicy.activate(public_host)`, `deactivate()`
- Produces: `create_public_app(...) -> FastAPI`
- Produces: `current_binding() -> CapabilityBinding`

- [ ] **Step 1: Write failing route-isolation and authentication tests**

Create the app with fake tools and test:

```python
for method, route in [
    ("GET", "/get_config"),
    ("POST", "/startAgent"),
    ("GET", "/local/workspace"),
    ("GET", "/events"),
    ("GET", "/docs"),
]:
    assert client.request(method, route).status_code == 404

assert client.post("/mcp/", content=b"{" * (64 * 1024 + 1)).status_code == 401
```

Then activate a lease/host and prove missing, invalid, pending, revoked, and
stale credentials return `401` before the request body receive callable is
consumed. Prove invalid Host/Origin returns `421`/`403`, non-MCP paths return
`404`, unsupported content type returns `415`, oversized/chunked bodies return
`413`, and rate exhaustion returns `429`.

- [ ] **Step 2: Run public-server tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_public_server.py -q
```

Expected: imports fail because the public ingress modules do not exist.

- [ ] **Step 3: Implement the outer ASGI policy**

The outer middleware order is route/method → bearer → Host/Origin → content
type → body limit → FastMCP. It must authenticate before reading a body. For
chunked bodies, wrap `receive` and stop once accumulated bytes exceed
`64 * 1024`. Named per-tool rate limits remain in `ManagedWorkTools`, after
FastMCP validates the tool shape but before Task Runtime is called.

Use a mutable host policy so the app can start on loopback before ngrok assigns
its host. Configure FastMCP's built-in DNS-rebinding layer off only because the
outer middleware performs the stricter dynamic check; document this ownership
in code.

- [ ] **Step 4: Register exactly four FastMCP tools**

```python
@mcp.tool()
async def start_work(objective: str, idempotency_key: str) -> dict[str, object]:
    return await tools.start_work(
        binding=current_binding(),
        objective=objective,
        idempotency_key=idempotency_key,
    )
```

Repeat explicitly for the other three tools. Use `stateless_http=True`,
`json_response=True`, `streamable_http_path="/"`, no docs/OpenAPI routes, and
an MCP session-manager lifespan.

- [ ] **Step 5: Run public ingress and existing validation isolation tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_public_server.py tests/architecture_validation/test_route_isolation.py -q
```

Expected: both production and synthetic apps pass independently.

- [ ] **Step 6: Commit**

```bash
git add server/src/managed_ingress server/tests/managed_ingress/test_public_server.py
git commit -m "feat(server): add isolated managed MCP ingress"
```

---

### Task 4: ngrok Process Boundary and Tunnel Health

**Files:**
- Create: `server/src/managed_ingress/ngrok.py`
- Create: `server/tests/managed_ingress/test_ngrok.py`
- Modify: `server/requirements.txt`

**Interfaces:**
- Produces: `TunnelPort.start(local_url) -> TunnelStatus`
- Produces: `TunnelPort.status() -> TunnelStatus`
- Produces: `TunnelPort.close() -> None`
- Produces: `NgrokCliTunnel(command, api_base_url, process_factory, http_client)`

- [ ] **Step 1: Write failing fake-process tunnel tests**

Inject a harmless fake process and mock `GET /api/tunnels`. Cover HTTPS URL
selection, rejection of HTTP/credentialed/query/fragment URLs, startup timeout,
process exit, health loss, URL change, secret-free diagnostics, idempotent
close, SIGTERM grace, and SIGKILL escalation.

```python
status = await tunnel.start("http://127.0.0.1:8001")
assert status.state == "ready"
assert status.public_base_url == "https://example.ngrok.app"
assert "authtoken" not in repr(status)
```

- [ ] **Step 2: Run tunnel tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_ngrok.py -q
```

Expected: import fails for missing `managed_ingress.ngrok`.

- [ ] **Step 3: Implement the CLI driver**

Launch without a shell:

```python
argv = [
    "ngrok",
    "http",
    local_url,
    "--log",
    "stdout",
    "--log-format",
    "json",
    "--web-addr",
    "127.0.0.1:4041",
]
```

Poll `http://127.0.0.1:${VOICE_ACP_NGROK_API_PORT:-4041}/api/tunnels` with bounded `httpx.AsyncClient`
timeouts until one HTTPS `public_url` points to the requested local address.
Never log subprocess output or the full API response. Close the process with a
two-second TERM grace followed by KILL. Add explicit `httpx>=0.27,<1` because
production code now imports it directly rather than relying on transitive deps.

- [ ] **Step 4: Run tunnel tests and dependency check**

```bash
cd server
source venv/bin/activate
python -m pip install -q -r requirements.txt
python -m pip check
PYTHONPATH=src pytest tests/managed_ingress/test_ngrok.py -q
```

Expected: all tests and dependency checks pass without starting ngrok.

- [ ] **Step 5: Commit**

```bash
git add server/src/managed_ingress/ngrok.py server/tests/managed_ingress/test_ngrok.py server/requirements.txt
git commit -m "feat(server): own the local ngrok tunnel"
```

---

### Task 5: Managed Ingress Coordinator and Drain Ordering

**Files:**
- Create: `server/src/managed_ingress/runtime.py`
- Create: `server/tests/managed_ingress/test_runtime.py`

**Interfaces:**
- Consumes: Workspace/readiness services, public app, `TunnelPort`, capability registry
- Produces: `ManagedIngressCoordinator.start()`, `quiesce()`, `close()`
- Produces: `prepare_agent() -> VoiceMcpLease`
- Produces: `activate_agent(lease_id, agora_agent_id)`, `revoke_agent(lease_id)`
- Produces: `VoiceMcpLease(endpoint, authorization, lease_id)`

- [ ] **Step 1: Write failing coordinator lifecycle tests**

Use fake listener and tunnel ports. Prove local listener starts without ngrok,
`prepare_agent` rejects unready ACP, ngrok starts only after readiness, the
endpoint is `/mcp/`, only one reservation exists, activation binds the exact
Agent ID, a changed URL revokes the old lease, and tunnel loss does not call
Task Runtime cancellation.

```python
lease = await coordinator.prepare_agent()
assert lease.endpoint == "https://example.ngrok.app/mcp/"
assert lease.authorization.startswith("Bearer ")
await coordinator.activate_agent(lease.lease_id, "agent-a")
```

Test coordinator shutdown phases exactly:

```python
assert events == [
    "capability.revoked",
    "handlers.drained",
    "tunnel.closed",
    "listener.closed",
]
```

`quiesce()` owns the first two events; `close()` owns the last two and rejects a
call made before quiescence. Also hold a fake authenticated handler open beyond
five seconds and prove it is cancelled after the deadline without reopening
ingress.

- [ ] **Step 2: Run coordinator tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_runtime.py -q
```

Expected: import fails for missing coordinator.

- [ ] **Step 3: Implement listener, tunnel, generation, and drain ownership**

Keep a monotonically increasing in-memory Workspace generation. Increment it
whenever the selected Workspace ID changes or the public ngrok URL changes.
Set the dynamic public Host only after the tunnel URL validates. Track entered
authenticated handlers with an `asyncio.Condition`; revocation closes entry,
then `close()` waits up to five seconds for the count to reach zero.

The coordinator owns one signal-free `uvicorn.Server` on
`127.0.0.1:${VOICE_ACP_MCP_PORT:-8001}`. It never installs signal handlers;
the existing launcher supervisor remains the only terminal-signal owner.

- [ ] **Step 4: Run all managed-ingress tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress -q
```

Expected: all tests pass offline.

- [ ] **Step 5: Commit**

```bash
git add server/src/managed_ingress/runtime.py server/tests/managed_ingress/test_runtime.py
git commit -m "feat(server): coordinate managed ingress lifecycle"
```

---

### Task 6: Inject Production MCP into the Managed Agora Agent

**Files:**
- Modify: `server/src/agent.py`
- Modify: `server/tests/test_agent.py`
- Create: `server/tests/managed_ingress/test_agent_bridge.py`

**Interfaces:**
- Consumes: `ManagedIngressCoordinator.prepare_agent/activate_agent/revoke_agent`
- Produces: `Agent(work_bridge: ManagedIngressCoordinator | None = None)` and `Agent.close()`
- Preserves: `Agent(evidence_config=...)` synthetic validation behavior
- Preserves: default `Agent()` managed quickstart with no MCP

- [ ] **Step 1: Write failing three-mode Agent construction tests**

Prove default, validation, and production Work modes are mutually exclusive.
The production mode must build managed OpenAI with exactly four allowed tools,
the lease endpoint, bearer header, and `timeout_ms: 5000`:

```python
assert captured["llm"]["params"]["mcp_servers"] == [{
    "name": "acplocal",
    "endpoint": "https://example.ngrok.app/mcp/",
    "transport": "streamable_http",
    "headers": {"Authorization": "Bearer test-secret"},
    "allowed_tools": [
        "start_work",
        "get_work_status",
        "cancel_work",
        "respond_permission",
    ],
    "timeout_ms": 5000,
}]
```

Assert the bearer is absent from logger records and result bodies.

- [ ] **Step 2: Write failing activation/revocation tests**

Cover reservation before `session.start`, activation only after the returned
Agent ID, revocation on start failure, revocation before `session.stop`, fallback
stop, and rejection of a second Work-capable Agent.

```python
result = await agent.start(...)
assert bridge.events == ["prepare", "activate:test-agent-id"]
await agent.stop("test-agent-id")
assert bridge.events[-2:] == ["revoke", "session.stop"]
```

- [ ] **Step 3: Run Agent tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/test_agent.py tests/managed_ingress/test_agent_bridge.py -q
```

Expected: failures for missing bridge constructor and Work-mode LLM config.

- [ ] **Step 4: Implement the Work-mode prompt and lifecycle**

Add a dedicated English system message that instructs the Managed Voice LLM to:

- call `start_work` once for a complete executable coding objective;
- ask one clarification before submitting an incomplete objective;
- treat tool state as authoritative;
- call status before answering about prior Work;
- cancel only after an explicit Work cancellation;
- use permission response only for an explicit current-operation allow/reject;
- never treat barge-in, silence, or unrelated agreement as cancellation or permission.

Prepare the lease before constructing the LLM, activate after `session.start`,
and revoke before any stop attempt. `Agent.close()` stops every locally owned
session without falling back to unknown stateless IDs and is idempotent. Keep evidence configuration isolated and
raise `ValueError` if evidence and production bridges are both supplied.

- [ ] **Step 5: Run Agent, validation, and tool tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/test_agent.py tests/architecture_validation/test_agent_construction.py tests/managed_ingress -q
```

Expected: all modes pass without an Agora call.

- [ ] **Step 6: Commit**

```bash
git add server/src/agent.py server/tests/test_agent.py server/tests/managed_ingress/test_agent_bridge.py
git commit -m "feat(server): connect managed voice to Work"
```

---

### Task 7: Compose Local App Ownership Without Changing Stable Routes

**Files:**
- Modify: `server/src/server.py`
- Modify: `server/tests/conftest.py`
- Modify: `server/tests/test_server.py`
- Modify: `server/tests/acp_runtime/test_server_startup.py`
- Create: `server/tests/managed_ingress/test_server_composition.py`
- Modify: `server/scripts/run_fake_server.py`

**Interfaces:**
- Produces: app-local `application.state.agent`, `managed_ingress`, `task_runtime`, and `work_store`
- Preserves: module-global `agent` replacement for the isolated validation runner
- Preserves: `/get_config`, `/startAgent`, `/stopAgent` request/response shapes

- [ ] **Step 1: Write failing composition tests**

Prove the default public app constructs no Task Runtime, ingress, ngrok, or
production MCP Agent. Prove the opted-in local app owns all four local objects,
starts ingress after Task Runtime, and closes ingress before Task Runtime/ACP.

Prove route handlers resolve the app-local Agent in local mode while the public
app and validation runner retain the replaceable module-global Agent. Exercise
the three stable routes with `FakeAgent` and assert unchanged JSON.

- [ ] **Step 2: Run composition tests and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/test_server.py tests/acp_runtime/test_server_startup.py tests/managed_ingress/test_server_composition.py -q
```

Expected: failures because the app has no managed-ingress state or app-local
Agent provider.

- [ ] **Step 3: Refactor router construction around an Agent provider**

Replace direct route reads of the module global with one private accessor:

```python
def build_api_router(get_agent: Callable[[], Agent | None]) -> APIRouter:
    router = APIRouter()
    # Route bodies call resolved_agent = get_agent().
    return router
```

For public/validation composition use `lambda: agent` so the validation runner
can still replace it. For opted-in local composition, construct
`Agent(work_bridge=managed_ingress)` and capture that app-local instance. Do not
mount the production MCP app into the lifecycle FastAPI app.

- [ ] **Step 4: Compose lifespan ownership**

Start Task Runtime, then the loopback MCP listener. On shutdown call ingress
`quiesce()` to revoke/drain, then `Agent.close()`, then close the ingress
transport, Task Runtime, ACP readiness, and Work Store.
Expose only non-secret objects under `application.state` for tests; do not add a
debug route.

- [ ] **Step 5: Run full backend tests**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest -q
```

Expected: all backend tests pass with no external process or network call.

- [ ] **Step 6: Commit**

```bash
git add server/src/server.py server/tests server/scripts/run_fake_server.py
git commit -m "feat(server): compose managed ingress locally"
```

---

### Task 8: Launcher Preflight, Verification, and Maintained Documentation

**Files:**
- Modify: `scripts/local-codex-preflight.ts`
- Modify: `scripts/local-codex-preflight.test.ts`
- Modify: `scripts/verify-local-launcher.ts`
- Modify: `scripts/run-local-codex.sh`
- Modify: `package.json`
- Modify: `README.md`
- Modify: `ARCHITECTURE.md`
- Modify: `AGENTS.md`
- Modify: `CONTEXT.md`
- Modify: `docs/ai/L0_repo_card.md`
- Modify: `docs/ai/L1/01_setup.md`
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
- Extends: `preflight:codex` with required `ngrok` command
- Extends: `verify:backend` with `tests/managed_ingress`
- Preserves: one terminal-signal owner and existing launcher exit codes

- [ ] **Step 1: Write failing preflight and launcher checks**

Add `ngrok` to the local required-command set and assert one bounded instruction
when absent:

```text
Missing required local runtime: ngrok. Install ngrok and run `ngrok config add-authtoken ...` once.
```

The test must use fake command sets and must not inspect a real token or ngrok
configuration. Extend launcher verification with a fake backend that spawns a
fake tunnel descendant; prove normal exit, SIGINT, SIGTERM, SIGHUP, and forced
shutdown leave no descendant.

- [ ] **Step 2: Run preflight and launcher tests and verify RED**

```bash
bun test scripts/local-codex-preflight.test.ts
bun run verify:launcher
```

Expected: preflight expectations fail until ngrok is required; launcher checks
fail until the new descendant fixture is handled.

- [ ] **Step 3: Update verification entry points**

Add `tests/managed_ingress` to `verify:backend`. Keep ngrok itself out of every
automated target. Ensure `run-local-codex.sh` exports the dedicated loopback MCP
port only to the backend and never prints the public URL or bearer.

- [ ] **Step 4: Update maintained documentation**

Document the actual state after implementation:

- `bun run dev:codex` requires installed/authenticated ngrok and starts it
  automatically only when a Work-capable voice Agent is prepared;
- only the dedicated MCP listener is tunneled;
- capabilities are per Agent and in memory;
- same-key idempotency is the current guarantee;
- real Agora/ngrok/Codex acceptance remains separately authorized and consumes
  minutes;
- SSE, Activity Panel, Speak, automatic reconnect rehydration, and production
  remote access remain deferred.

Set `Last Reviewed` in `docs/ai/L0_repo_card.md` to `2026-08-19` and add the
production ingress modules/tests to the code map and verification deep dive.

- [ ] **Step 5: Run the exact offline release suite**

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
git status --short
```

Expected: every command exits zero; tests use fake Agent/ngrok/ACP only. Record
dependency deprecation warnings separately rather than treating them as live
acceptance failures.

- [ ] **Step 6: Commit**

```bash
git add scripts package.json README.md ARCHITECTURE.md AGENTS.md CONTEXT.md docs/ai
git commit -m "docs: document managed MCP local flow"
```

---

## Plan Self-Review Checklist

- [ ] Every production MCP module is independent of `architecture_validation`.
- [ ] Every public handler authenticates before body parsing and maps to the real Task Runtime.
- [ ] Bearer, Workspace path, Agent/ACP correlation IDs, and exceptions are absent from public projections and logs.
- [ ] Agent start/stop and capability activation/revocation are serialized and failure-safe.
- [ ] Public quickstart behavior and validation harness behavior remain unchanged.
- [ ] ngrok and real Agora are absent from automated tests.
- [ ] No claim exceeds same-key idempotency or offline evidence.
- [ ] SSE/UI/Speak/reconnect work remains outside this plan.
