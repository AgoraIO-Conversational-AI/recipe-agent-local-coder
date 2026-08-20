# MCP Pending Handshake Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let Agora complete side-effect-free MCP discovery while its capability is pending, without allowing any Work tool call before the real Agent ID is bound.

**Architecture:** `CapabilityRegistry` will authenticate a bearer into an explicit invalid, pending, or active result. `McpIngressMiddleware` will retain bearer-before-body ordering, inspect bounded pending JSON-RPC requests, and forward only the handshake whitelist; active calls keep the existing FastMCP path.

**Tech Stack:** Python 3.10+, FastAPI/ASGI, FastMCP Streamable HTTP, pytest, existing fake Agent/ngrok/ACP boundaries.

## Global Constraints

- Pending capability methods are exactly `initialize`, `notifications/initialized`, `tools/list`, and `ping`.
- Pending `tools/call`, unknown methods, mixed batches, GET, DELETE, and malformed JSON return HTTP 503 `runtime_unavailable`.
- Invalid or revoked credentials return HTTP 401 before the request body is read.
- Only `activate(lease_id, agora_agent_id)` creates a `CapabilityBinding` with the real Agora Agent ID.
- No public route, tool, dependency, provisional Agent ID, credential log, or Workspace authority is added.
- Automated verification must not start Agora or ngrok.

---

### Task 1: Model Pending Capability Authentication

**Files:**
- Modify: `server/src/managed_ingress/capabilities.py`
- Test: `server/tests/managed_ingress/test_capabilities.py`

**Interfaces:**
- Produces: `CapabilityAccess(state: Literal["pending", "active"], binding: CapabilityBinding | None)`
- Produces: `CapabilityRegistry.authenticate(bearer: str) -> CapabilityAccess | None`
- Preserves: `CapabilityRegistry.resolve(bearer: str) -> CapabilityBinding | None`

- [ ] **Step 1: Write the failing pending/authentication-state test**

```python
def test_authenticate_distinguishes_pending_active_and_revoked_capabilities():
    registry = CapabilityRegistry(
        token_factory=lambda: "secret-bearer",
        id_factory=lambda: "credential-a",
    )
    lease = registry.prepare("scope-a", 1)
    pending = registry.authenticate(lease.bearer)
    assert pending.state == "pending"
    assert pending.binding is None
    assert registry.resolve(lease.bearer) is None

    binding = registry.activate(lease.lease_id, "agent-a")
    active = registry.authenticate(lease.bearer)
    assert active.state == "active"
    assert active.binding == binding

    registry.revoke(lease.lease_id)
    assert registry.authenticate(lease.bearer) is None
```

- [ ] **Step 2: Run the test and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_capabilities.py::test_authenticate_distinguishes_pending_active_and_revoked_capabilities -q
```

Expected: FAIL because `authenticate` does not exist.

- [ ] **Step 3: Implement the explicit access result**

```python
from typing import Literal

@dataclass(frozen=True)
class CapabilityAccess:
    state: Literal["pending", "active"]
    binding: CapabilityBinding | None

def authenticate(self, bearer: str) -> CapabilityAccess | None:
    record = self._record
    if record is None or record.revoked or not bearer:
        return None
    if not hmac.compare_digest(record.bearer_digest, _digest(bearer)):
        return None
    return CapabilityAccess(
        state="active" if record.binding is not None else "pending",
        binding=record.binding,
    )

def resolve(self, bearer: str) -> CapabilityBinding | None:
    access = self.authenticate(bearer)
    return access.binding if access is not None and access.state == "active" else None
```

- [ ] **Step 4: Run the capability suite and verify GREEN**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_capabilities.py -q
```

Expected: all capability tests pass.

- [ ] **Step 5: Commit the capability state**

```bash
git add server/src/managed_ingress/capabilities.py server/tests/managed_ingress/test_capabilities.py
git commit -m "fix(server): distinguish pending MCP capabilities"
```

---

### Task 2: Permit Only Pending MCP Discovery

**Files:**
- Modify: `server/src/managed_ingress/http_policy.py`
- Test: `server/tests/managed_ingress/test_public_server.py`

**Interfaces:**
- Consumes: `CapabilityRegistry.authenticate(bearer) -> CapabilityAccess | None`
- Produces: `_pending_handshake_only(body: bytes) -> bool`
- Preserves: active request buffering, HTTP 429 conversion, Host/Origin checks, 64 KiB body limit, and `current_binding()`.

- [ ] **Step 1: Write a failing production-order test**

Create one pending lease and send valid JSON-RPC requests with the existing MCP `Accept` header. Assert:

```python
initialize = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {
        "protocolVersion": "2025-06-18",
        "capabilities": {},
        "clientInfo": {"name": "agora", "version": "test"},
    },
}
tool_call = {
    "jsonrpc": "2.0",
    "id": 2,
    "method": "tools/call",
    "params": {
        "name": "start_work",
        "arguments": {"objective": "inspect", "idempotency_key": "turn-a"},
    },
}

assert client.post("/mcp/", headers=headers, json=initialize).status_code == 200
assert client.post("/mcp/", headers=headers, json=tool_call).status_code == 503
assert fake_tools.start_calls == 0

registry.activate(lease.lease_id, "agent-a")
assert client.post("/mcp/", headers=headers, json=tool_call).status_code == 200
assert fake_tools.start_calls == 1

registry.revoke(lease.lease_id)
assert client.post("/mcp/", headers=headers, json=initialize).status_code == 401
```

Add parameterized pending tests for `notifications/initialized`, `tools/list`,
and `ping`. Add fail-closed cases for unknown methods, malformed JSON, mixed
batches, GET, and DELETE.

- [ ] **Step 2: Run the public-server test and verify RED**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_public_server.py -q
```

Expected: pending `initialize` receives 401.

- [ ] **Step 3: Implement bounded pending-method inspection**

After bearer, Host, Origin, content-type, and body-size validation, inspect the
already-buffered body:

```python
_PENDING_METHODS = {
    "initialize",
    "notifications/initialized",
    "tools/list",
    "ping",
}

def _pending_handshake_only(body: bytes) -> bool:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False
    messages = payload if isinstance(payload, list) else [payload]
    return bool(messages) and all(
        isinstance(message, dict)
        and message.get("method") in _PENDING_METHODS
        for message in messages
    )
```

Use `registry.authenticate()` before body reading. Invalid access remains 401.
Pending access rejects non-POST requests immediately with 503, then rejects a
buffered body unless `_pending_handshake_only(body)` is true. Set
`_current_binding` only when `access.binding` is not `None`; handshake handlers
do not require a Work binding.

- [ ] **Step 4: Run focused suites and verify GREEN**

```bash
cd server
source venv/bin/activate
PYTHONPATH=src pytest tests/managed_ingress/test_capabilities.py tests/managed_ingress/test_public_server.py tests/managed_ingress/test_agent_bridge.py -q
```

Expected: all focused tests pass without outbound calls.

- [ ] **Step 5: Run the full offline release verification**

```bash
bun test
bun run verify:backend
bun run verify:launcher
bun run verify:local
bun run verify:web
```

Expected: all commands pass. Any existing dependency deprecation warnings remain warnings only. No Agora conversation or ngrok tunnel starts.

- [ ] **Step 6: Update maintained runtime/security documentation**

Update these files in English:

- `README.md`: state that MCP discovery may authenticate while the capability is pending, but Work calls require exact Agent activation.
- `docs/ai/L1/02_architecture.md`: record the prepare → pending handshake → Agent ID → active tools order.
- `docs/ai/L1/08_security.md`: record the pending handshake whitelist and 503 failure contract.
- `docs/ai/L1/L2/acp_runtime.md`: add the startup-race behavior.
- `docs/ai/L0_repo_card.md`: keep `Last Reviewed` as the current calendar date and update the derivative summary to reflect the reviewed handshake boundary.

- [ ] **Step 7: Commit the vertical fix**

```bash
git add README.md docs/ai server/src/managed_ingress/http_policy.py server/tests/managed_ingress/test_public_server.py
git commit -m "fix(server): allow pending MCP discovery"
```

- [ ] **Step 8: Perform one separately authorized live acceptance**

Restart `bun run dev:codex`, start one short Agora conversation, submit one
read-only coding objective, and ask for its status. Confirm ngrok records
successful MCP discovery and `work.sqlite3` contains one Work receipt. This is
not part of automated verification and consumes Agora minutes.
