# Native Project Folder Picker Resilience Design

## Goal

Keep the macOS Project Folder picker usable even when the user leaves it open longer than the Next.js proxy connection survives. The browser must eventually show the backend's real Workspace and Runtime state, and shutting down after a completed switch must not emit an ACP connection traceback.

This repair does not change the three stable Agora quickstart routes and does not start an Agora conversation.

## Observed failure

The real local acceptance flow reproduced this sequence:

1. `POST /api/local/workspace/browse` remained open while the native picker waited for user input.
2. Next.js closed the proxied connection before the user completed the picker.
3. FastAPI still completed the Workspace switch and opened the new ACP session.
4. The browser received a plain-text proxy error, tried to parse it as JSON, retained the old path, and displayed a JSON syntax error.
5. A later page reload reconciled the correct Workspace and Runtime state.
6. Shutdown attempted `session/close` on an already closed ACP connection and printed a traceback, although all child processes were eventually removed.

## Considered approaches

### Extend the proxy timeout

Rejected. Native user interaction has no meaningful upper bound, and a larger timeout only moves the failure.

### Call FastAPI directly from the browser

Rejected for v0.1. It introduces a second browser API origin and CORS/security contract while still keeping one HTTP request open for an unbounded period.

### Asynchronous picker operation with polling

Selected. Starting the native picker becomes a short request. The backend owns the long-running operation and the browser polls a bounded, loopback-only status resource.

## Backend design

Add a focused `WorkspaceBrowseCoordinator` owned by the local Workspace router.

- `POST /local/workspace/browse` starts one native picker operation and returns immediately with HTTP 202 and an opaque `operation_id`.
- Only one picker may be active. A second start while one is pending returns HTTP 409.
- `GET /local/workspace/browse/{operation_id}` returns one of:
  - `picking`
  - `ready`, with the selected `WorkspaceStatus`
  - `cancelled`, with the existing stable cancellation message
  - `failed`, with a bounded local setup message
- The operation becomes `ready` only after Workspace validation, the switch guard, persistence, ACP replacement, and readiness all succeed.
- An activation failure restores the previous persisted Workspace exactly as the current synchronous path does.
- Completed operation data contains no ACP session identifiers, command environment, authentication data, or raw exception text.
- Operation IDs are random opaque values and only the current operation is retained in memory. This remains a single-user loopback runtime, not a general job system.

Manual-path `PUT /local/workspace` remains synchronous because it contains no human-blocking native interaction.

## Browser design

`browseWorkspace()` keeps its existing public result type, `Promise<WorkspaceStatus>`:

1. POST the start request.
2. Poll the returned operation URL while its state is `picking`.
3. Return the Workspace on `ready`.
4. Raise the stable cancellation or failure message for terminal error states.

The Settings component therefore keeps one selection path and continues to invalidate Runtime readiness before a switch and refresh it afterward.

All local response parsing first reads response text and safely attempts JSON decoding. A non-JSON proxy response produces a bounded `HTTP <status>` error, never a JavaScript JSON parser message or raw proxy body.

## ACP shutdown design

`CodexAcpClient.close()` remains idempotent and always exits the child-process context. If `session/close` finds that the ACP transport is already closed, that specific `ConnectionError` is treated as an already-completed close. Other protocol and process-context failures continue to surface.

## Confirmed test seams

Tests use public owned boundaries only:

1. FastAPI router seam: a blocked fake picker proves POST returns before picker completion; status polling transitions from `picking` to `ready`; cancellation and activation rollback are terminal states.
2. Browser API seam: start/poll responses resolve to `WorkspaceStatus`; a plain-text HTTP 500 produces a stable `HTTP 500` error rather than `Unexpected token`.
3. ACP client seam: a fake connection whose `close_session` raises `ConnectionError` still exits its process context exactly once; repeated close remains a no-op.
4. Local proxy verification: the new start and status routes remain available only under the explicit loopback local-runtime opt-in.

No test opens a native picker, starts real Codex, authenticates, starts an Agora agent, joins RTC/RTM, or consumes Agora minutes.

## Acceptance

- Leaving the native picker open cannot hold a Next.js proxy request open.
- Completing the picker updates the Settings view without a reload.
- Cancellation leaves the prior Workspace and ACP session unchanged.
- Non-JSON infrastructure errors display a bounded actionable message.
- Ctrl-C after a real Workspace switch cleans up without an ACP `Connection closed` traceback.
