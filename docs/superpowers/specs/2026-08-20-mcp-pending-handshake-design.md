# MCP Pending Handshake Design

**Date:** 2026-08-20  
**Status:** Approved for implementation

## Problem

Agora starts MCP discovery while `AgentSession.start()` is still waiting for
the cloud service to return the real Agora Agent ID. The local capability is
already present in the Agent configuration, but the registry intentionally
does not create an active `CapabilityBinding` until that real ID is known.
Consequently, the current middleware rejects the initial MCP `initialize`
request with HTTP 401. Agora never discovers the Work tools, and Codex is not
triggered during the conversation.

Live evidence from ngrok showed two authenticated `POST /mcp/` requests. Both
were JSON-RPC `initialize` calls and both received HTTP 401. No Work receipt was
created.

## Decision

Distinguish a valid pending capability from an active capability without
creating a provisional Agent binding.

A bearer for the one current, unrevoked pending lease may authenticate only
these side-effect-free MCP protocol methods:

- `initialize`
- `notifications/initialized`
- `tools/list`
- `ping`

The pending bearer must not authorize `tools/call`, GET streams, DELETE
requests, unknown methods, or mixed JSON-RPC batches. Those requests return a
fixed retriable HTTP 503 response and never reach FastMCP tool execution.

After `AgentSession.start()` returns the real Agora Agent ID, the existing
activation path creates the exact `CapabilityBinding`. The same bearer then
uses the normal active request path and can invoke the four Work tools. After
revocation, both handshake and tool requests return HTTP 401.

## Components

`CapabilityRegistry` will expose an authentication result that distinguishes
`invalid`, `pending`, and `active`. It will continue to expose an active
`CapabilityBinding` only for the active state.

`McpIngressMiddleware` will preserve the current ordering: validate bearer
before reading the body, then validate Host, Origin, content type, and size.
For a pending POST, it will inspect only the bounded JSON-RPC envelope and
forward the request when every message is on the handshake whitelist. Active
requests retain the existing FastMCP schema validation, rate limiting, and
response handling.

No provisional Agora Agent ID, Workspace override, browser route, new public
endpoint, or additional MCP tool is introduced.

## Failure Contract

- Invalid or revoked bearer: HTTP 401 `invalid_or_expired_capability`.
- Valid pending bearer with a non-handshake request: HTTP 503
  `runtime_unavailable`.
- Malformed pending JSON: HTTP 503 `runtime_unavailable`.
- Active bearer: current MCP behavior.

No credential, Workspace path, request body, or Agent identifier is logged in
these failures.

## Verification

Credential-free tests will reproduce the production ordering:

1. prepare a lease without activating it;
2. prove `initialize`, `notifications/initialized`, `tools/list`, and `ping`
   reach the MCP server;
3. prove pending `tools/call`, unknown methods, mixed batches, GET, and DELETE
   return 503 without calling a fake tool;
4. activate the lease with a real-shaped Agent ID and prove `tools/call`
   succeeds;
5. revoke the lease and prove subsequent handshake and tool calls return 401;
6. keep the existing invalid-bearer-before-body-read assertion.

The automated suite remains offline. One later user-authorized conversation is
required to confirm Agora performs successful discovery and invokes Codex.
