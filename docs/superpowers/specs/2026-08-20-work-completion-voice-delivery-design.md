# Work Completion Voice Delivery Design

**Date:** 2026-08-20  
**Status:** Approved for implementation planning

## Problem

The local Task Runtime durably completes or fails Work and stores a safe final
result, but the active voice conversation receives no proactive notification.
The receipt remains `pending_delivery` until the user explicitly asks the
Managed Voice LLM to call `get_work_status`.

The first live Work confirmed this gap: the receipt reached `completed`, its
final presentation was stored, and its delivery state stayed
`pending_delivery`.

## Decision

Add the smallest active-session-only delivery path. After Task Runtime commits
a terminal `completed` or `failed` receipt, an in-process callback wakes a thin
delivery coordinator. The coordinator speaks the safe stored result through
the exact originating Agora Agent session with
`session.say(..., priority="APPEND", interruptable=True)`.

This design copies Qwen Audio Agent's durable pending-notification and exact
session-delivery principles. It does not copy Qwen's second Realtime LLM turn,
browser playback receipts, batching, renewable claims, or cross-session
recovery.

## Scope

- Proactively announce both completed and failed Work.
- Do not announce cancelled Work; cancellation was explicitly initiated by the
  user.
- Deliver only while the exact originating Agora Agent session is still
  locally active and the Workspace still matches.
- Keep `get_work_status` as the durable fallback.
- Keep the implementation offline-testable without starting Agora, ngrok, or a
  real ACP child.

## Data Model

Add one nullable internal `delivery_agent_id` field to each Work receipt and
SQLite row. `ManagedWorkTools.start_work()` derives it from the authenticated
`CapabilityBinding.agora_agent_id` and passes it into
`TaskRuntime.start_work()`.

The existing `workspace_id` remains the Workspace target. No Workspace path is
stored or exposed. No Workspace generation is persisted for delivery: exact
Agent ID plus the existing Workspace ID and a current Workspace check are
sufficient for this session-bound version.

Existing delivery states retain these meanings:

- `not_ready`: no terminal result is available;
- `pending_delivery`: a completed or failed result is stored but not submitted;
- `sending`: one coordinator invocation has claimed the result for submission;
- `accepted`: the Agora Speak request returned successfully;
- `delivery_unknown`: submission began but did not return a reliable outcome.

`accepted` means the Agora API accepted the request. It does not prove the user
heard the full audio.

## Components

### Task Runtime terminal callback

Task Runtime gains one optional, backend-neutral terminal callback. It invokes
the callback only after the authoritative receipt is committed:

- `completed`: after `FinalPresentation` is saved and state becomes
  `completed`;
- `failed`: after the bounded safe error and `pending_delivery` are committed;
- `cancelled`: no callback.

The callback carries only `work_id`. It does not perform delivery inline and
must not block the FIFO ACP worker.

### Work store delivery operations

`WorkStore` owns compare-and-set delivery transitions:

- `claim_delivery(work_id)` changes `pending_delivery` to `sending` and returns
  the updated receipt; every other source state returns no claim;
- `mark_delivery_accepted(work_id)` changes `sending` to `accepted`;
- `release_delivery(work_id)` changes `sending` back to `pending_delivery`
  only when the coordinator proves that submission never began;
- `mark_delivery_unknown(work_id)` changes `sending` to `delivery_unknown`.

The compare-and-set boundary prevents a duplicate terminal callback from
creating a second announcement.

### Work delivery coordinator

`WorkDeliveryCoordinator` owns one in-process queue and worker. `notify(work_id)`
enqueues the identifier without waiting for speech. For each item the worker:

1. reloads the receipt from `WorkStore`;
2. ignores cancelled, nonterminal, already accepted, unknown, or untargeted
   receipts;
3. verifies that the current Workspace ID still equals the receipt Workspace;
4. resolves only `Agent._sessions[delivery_agent_id]` through a narrow Agent
   method; it never selects the latest session;
5. leaves the receipt `pending_delivery` if either exact check fails;
6. claims `pending_delivery -> sending`;
7. revalidates the exact session immediately before submission and releases
   the claim back to `pending_delivery` if the session disappeared;
8. speaks `FinalPresentation.speech` for completed Work or the stored safe
   error for failed Work with `APPEND` and `interruptable=True`;
9. stores `accepted` on a normal return, or `delivery_unknown` on any exception
   after submission begins.

There is no automatic retry. Retrying an ambiguous `say()` outcome could
duplicate speech.

### Agent session boundary

`Agent` remains the sole owner of live Managed Agent sessions. It exposes one
narrow asynchronous delivery method that looks up the exact `agent_id` and
calls that session's `say()` method. Missing or detached sessions are reported
as unavailable before submission.

Agent stop continues to detach local session ownership and revoke the MCP
capability before stopping the remote session. A delivery that has not claimed
the receipt then leaves it pending. A session loss during `say()` produces
`delivery_unknown`.

No second session registry is introduced.

## Lifecycle and Composition

The local application constructs the delivery coordinator only when Managed
ingress and Task Runtime are enabled. It wires the coordinator as Task
Runtime's terminal callback before the FastAPI lifespan starts.

Lifespan starts Task Runtime and the delivery worker before accepting Work. On
shutdown it stops new delivery notifications, drains or cancels the delivery
worker, then follows the existing Agent, ingress, Task Runtime, ACP, and store
cleanup order. Shutdown must not reset `sending` to `pending_delivery`; an
interrupted submission is conservatively `delivery_unknown`.

Startup does not scan or replay older `pending_delivery` receipts. A new Agora
Agent must never receive a prior session's result automatically.

## Error Handling

- Missing exact Agent session before claim: keep `pending_delivery`.
- Workspace mismatch before claim: keep `pending_delivery`.
- Exact session disappears after claim but before submission: release back to
  `pending_delivery`.
- Duplicate callback: compare-and-set returns no claim; do not speak.
- Normal `say()` return: mark `accepted`.
- Any exception after `say()` is invoked: mark `delivery_unknown`, log only a
  safe error type, and do not retry.
- Store failure before `say()`: do not speak without a successful claim.
- Failed Work: speak only the bounded stored error; never exception details,
  paths, credentials, ACP frames, or child environment values.

## Public Surface

No browser route, MCP tool, SSE endpoint, environment variable, or UI component
is added. Existing four-tool MCP shape remains unchanged. The status projection
continues to expose the safe delivery state and final presentation.

`delivery_agent_id` is a private Work-receipt field and must create no new
exposure through MCP or Work browser projections, Activity data, or delivery
logs. The existing `/startAgent` lifecycle response and lifecycle diagnostics
retain their established Agent ID contract.

## Testing

Offline tests cover these seams:

- WorkStore schema upgrade and exact delivery compare-and-set transitions;
- Managed `start_work` persists the authenticated originating Agent ID without
  projecting it publicly;
- completed Work enqueues one delivery only after final persistence;
- failed Work enqueues and speaks its bounded safe error;
- cancelled Work never enqueues;
- exact active session receives one
  `say(text, priority="APPEND", interruptable=True)` call;
- missing session or changed Workspace leaves `pending_delivery`;
- duplicate notification causes no second call;
- `say()` exception produces `delivery_unknown` and no retry;
- Agent stop versus delivery cannot redirect speech to another session;
- existing MCP, Task Runtime, Agent lifecycle, launcher, proxy, and web build
  suites remain green.

Automated verification does not establish live Agora Speak acceptance. One
separately authorized, minute-consuming voice check remains required after the
offline suite passes.

## Non-Goals

- No second LLM turn or dynamic result injection.
- No playback-start or playback-complete acknowledgement.
- No delivery retry, batching, lease renewal, or multi-client claim protocol.
- No cross-session or post-restart automatic replay.
- No Activity Panel, SSE, browser polling, or RTM-owned delivery.
- No proactive permission delivery in this slice.
- No model, STT, TTS, VAD, prompt, or MCP tool-shape change.

## Acceptance Criteria

1. A completed Work from an active exact Agent produces one APPEND speech call
   and stores `accepted`.
2. A failed Work from an active exact Agent produces one safe APPEND speech
   call and stores `accepted`.
3. Cancelled Work produces no speech.
4. Missing/stopped Agent or Workspace mismatch produces no speech and preserves
   `pending_delivery`.
5. Duplicate completion signals cannot produce duplicate speech.
6. An ambiguous Speak failure stores `delivery_unknown` and is not retried.
7. Status lookup still returns the authoritative result and delivery state.
8. All offline verification passes without starting a live Agora conversation.
