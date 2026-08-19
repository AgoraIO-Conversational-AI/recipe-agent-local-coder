# Managed MCP and ngrok Ingress Design

**Status:** Approved

**Date:** 2026-08-19

**Parent design:** [Agora Voice-to-ACP Local v0.1](2026-08-15-agora-voice-acp-local-design.md)

## 1. Goal

Connect Agora's Managed Voice LLM to the existing local Task Runtime through a
temporary, authenticated ngrok bridge. One launcher command owns the local MCP
listener, its per-Agent capability, the ngrok tunnel, and the matching Agora
Agent lifecycle.

This slice makes the four production Work tools callable from a real Managed
Voice LLM session. It does not add SSE, the Activity Panel, result Speak,
automatic result recovery, or production remote access.

## 2. Architecture

```text
Agora Managed Voice LLM
  -> HTTPS through launcher-owned ngrok
  -> dedicated loopback MCP listener
  -> per-Agent capability binding
  -> four production MCP tools
  -> Task Runtime
  -> codex-acp over local stdio
```

ACP never crosses ngrok. The tunnel exposes only the dedicated MCP ASGI app;
it never exposes the quickstart routes, Workspace controls, validation admin
routes, SQLite, SSE, diagnostics, or an LLM callback.

The production ingress is separate from `architecture_validation`. The
validation harness remains synthetic and must not become the production state
store or tool implementation.

## 3. Owned Components

### 3.1 Capability Registry

Each active Agora Agent receives a random 256-bit bearer. Its in-memory binding
contains:

```text
credential_id
workspace_id
workspace_generation
agora_agent_id
issued_at
revoked_at
```

The bearer is a credential, not the Work principal. Workspace identity remains
stable when a voice session is replaced. Every tool resolves the bearer and
then confirms that its Workspace generation and Agora Agent ID are still
current. Starting, replacing, or stopping an Agent and issuing or revoking its
capability is one serialized lifecycle operation.

There is at most one Work-capable Agora Agent in v0.1. The backend enforces this
invariant instead of relying on the browser UI.

### 3.2 Production MCP App

The dedicated stateless Streamable HTTP MCP app mounts only `/mcp/` and exposes:

- `start_work(objective, idempotency_key)`
- `get_work_status(work_id=None)`
- `cancel_work(work_id=None)`
- `respond_permission(decision)`

Authentication uses `Authorization: Bearer <capability>`. The token never
appears in the URL, logs, browser, `.env`, or SQLite. It expires when its Agent
stops or the launcher exits.

The app rejects an invalid bearer before parsing an MCP body. It validates
method, content type, Host, Origin when present, and a 64 KiB request-body
limit. Only the active ngrok host plus loopback test hosts are accepted.

### 3.3 Production Tool Adapter

The adapter is stateless. It maps the authenticated binding to the existing
Task Runtime and returns only public projections. It never returns Workspace
paths, capability values, ACP authorization or option IDs, raw activity, child
process details, exception text, or database information.

`start_work` commits a Work receipt before returning and never waits for ACP.
The existing 16 KiB Objective and 256-byte idempotency-key limits apply. Until
Agora provides a verified stable tool-call identity, v0.1 guarantees only that
requests carrying the same idempotency key return the same receipt. It does not
claim that independently generated duplicate model calls are exactly-once.

`get_work_status` resolves only the active Workspace's current or named Work.
`cancel_work` preserves the Task Runtime's confirmed-cancellation semantics.
`respond_permission` accepts only `allow` or `reject`; all ACP correlation
identifiers remain internal.

### 3.4 ngrok Owner

The launcher starts ngrok only after ACP and the MCP listener are ready. It
obtains the assigned HTTPS URL from ngrok's local API, validates its host, and
passes the endpoint plus bearer header into the Managed Voice LLM MCP config.

The initial implementation treats a changed public URL as a new Agent
generation. The old capability is revoked and Work acceptance remains closed
until the old Agora Agent is stopped and a replacement is created with the new
URL. Already-running local Work continues.

ngrok authentication is a necessary first-run interaction. Secrets are handled
by ngrok's normal local configuration and are never requested in chat or
printed by the launcher.

## 4. Startup and Shutdown

Startup proceeds in this order:

1. validate the local platform, Agora configuration, and ngrok availability;
2. start the loopback backend and web application;
3. select and validate Project Folder;
4. open and authenticate ACP for that Workspace;
5. start Task Runtime and the dedicated MCP listener;
6. start ngrok and verify the public MCP route;
7. report local Work readiness;
8. create the Agora Agent only when the user starts a conversation, issuing its
   capability and injecting the current public MCP endpoint atomically.

Shutdown or Agent replacement proceeds in this order:

1. revoke the capability and stop accepting new public Work calls;
2. drain already-authenticated MCP handlers for at most five seconds;
3. stop the active Agora Agent;
4. stop ngrok and the MCP listener;
5. stop Task Runtime, ACP, backend, and web through the existing supervisor.

Work committed before capability revocation remains authoritative. A running
Work is not cancelled merely because ngrok or the voice session disconnects.

## 5. Limits and Failure Contract

- MCP configuration uses `timeout_ms: 5000`; acceptance and status handlers
  must normally complete within one second locally.
- Request body maximum is 64 KiB.
- `start_work` is limited to 10 calls per minute per capability.
- status reads are limited to 60 calls per minute per capability.
- cancellation and permission responses share a 20-call-per-minute mutation
  budget.
- Queued Objectives may consume at most 1 MiB per Workspace. There remains no
  fixed Work-count cap.
- Public status responses are bounded to 256 KiB.

Failures use fixed safe codes. Invalid or expired credentials are unauthorized.
Stale Workspace or Agent generations, unavailable ACP, an unhealthy tunnel,
and a changed public URL are retriable unavailable states and create no Work.
Invalid arguments and exceeded size limits create no Work. Rate limiting
returns a retriable response without exposing counters or bindings.

Voice barge-in and speech interruption never call `cancel_work`. Only an
explicit Work-cancellation tool call cancels ACP execution.

## 6. Deferred Correlation Qualification

Agora's documented MCP configuration includes endpoint, headers, allowed tools,
and timeout, but does not currently promise a stable turn or tool-call identity
to the MCP server. Live qualification must inspect original calls and retries.

If a stable trusted identifier exists, a later revision derives the receipt key
from it and rejects tool calls from superseded voice turns. If it does not, the
documented same-key idempotency boundary remains, and the project must not claim
stronger exactly-once semantics.

## 7. Offline Acceptance

Credential-free tests use fake Agora, ngrok, and ACP boundaries and prove:

1. only `/mcp/` is public and invalid bearers fail before body parsing;
2. bearer rotation preserves Workspace identity but rejects stopped Agent IDs;
3. the four tool schemas and public projections call the real Task Runtime;
4. duplicate same-key submission creates one receipt;
5. permission decisions never expose or select permanent authorization;
6. an unhealthy tunnel, changed URL, stale Agent, or unready ACP creates no Work;
7. request size, rate, response, and queued-byte budgets fail closed;
8. shutdown revokes ingress before draining handlers and stopping local owners;
9. ngrok loss does not cancel already-running Work;
10. voice interruption remains independent from Work cancellation.

One separately authorized live acceptance uses a disposable repository and a
real Agora project, ngrok, and Codex login. It consumes Agora minutes and is not
part of automated implementation verification.

## 8. Qwen Comparison Decisions

The design retains Qwen Audio Agent's useful patterns: durable nonblocking Work,
stable backend identity behind reconnecting voice sessions, one serial ACP
prompt, explicit cancellation, permission correlation, and bounded safe
progress. The detailed comparison is recorded in
[`research/qwen-audio-agent-mcp-gap-review.md`](../../../research/qwen-audio-agent-mcp-gap-review.md).

It deliberately does not copy Qwen's permanent approval mode, exposure of ACP
authorization IDs, local Realtime-model proxy, result injection through another
LLM turn, multi-backend selection, memory, reminders, or mutable task UI.
