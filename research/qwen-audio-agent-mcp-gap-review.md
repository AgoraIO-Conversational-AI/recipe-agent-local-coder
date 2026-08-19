# Qwen Audio Agent gap review for Agora Managed Voice LLM → MCP → local ACP

Date: 2026-08-19  
Upstream reviewed: `QwenAudio/qwen-audio-agent` at [`a087a5ee35a730ae195444d08738a6f351017a1b`](https://github.com/QwenAudio/qwen-audio-agent/tree/a087a5ee35a730ae195444d08738a6f351017a1b)  
Local baseline: [approved v0.1 design](../docs/superpowers/specs/2026-08-15-agora-voice-acp-local-design.md)

## Executive conclusion

The four proposed MCP tools are sufficient. The design already covers Qwen's important high-level patterns: immediate durable acceptance, one serial ACP session, permission gating, confirmed cancellation, safe progress projection, restart-fails-active-work semantics, and proactive result delivery through Agora Speak.

The remaining gaps are mainly correlation and lifecycle details at the managed-cloud-to-local seam. Before implementation, add: a trusted turn/idempotency source; stale-turn fencing; a stable principal behind rotating bearer credentials; transactional permission delivery with paused prompt timeouts; reconnect rehydration; exact Agora `agent_id` fencing for Speak; late ACP-event fencing; and explicit transport/queue budgets.

## Required design additions

### P0 — Trusted turn correlation and stale-call fencing

`idempotency_key` must not be generated freely by the Voice LLM and then treated as proof of one voice turn. Qwen derives its submission key from server-held `sessionId + turnId/callId`, remembers processed call IDs, and returns the existing Work for a duplicate turn ([submission and deduplication](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/tools/tool-call-handler.mjs#L533-L590)). It also rejects a tool call whose turn generation has been superseded by a newer user turn ([stale-call guard](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/tools/tool-call-handler.mjs#L93-L98), [application before submission](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/tools/tool-call-handler.mjs#L341-L369)).

Agora's current Join reference documents MCP `endpoint`, `headers`, `allowed_tools`, and `timeout_ms`, but does not document a stable voice-turn identifier delivered to the MCP server ([official Join reference, `mcp_servers`](https://docs-md.agora.io/en/conversational-ai/rest-api/agent/join.md)). Therefore this is an integration unknown, not an implementation detail.

Add a release gate that proves what stable metadata Agora sends on original calls and retries. Derive the receipt key locally from that trusted value. If no stable turn/call identity is available, do not pretend a model-authored UUID is exactly-once: define a bounded fallback deduplication policy and state its limitation. Also reject a tool call that belongs to a superseded/interrupted model turn if it has not yet durably created Work.

Qwen separately preserves final ASR as `originalRequest` while accepting immediately from the model-provided objective ([nonblocking transcript capture](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/tools/tool-call-handler.mjs#L510-L590)). If Agora exposes correlatable final ASR, store it separately from the interpreted Objective; otherwise explicitly declare the Objective to be the only managed-MCP input and test semantic fidelity live.

### P0 — Rotating bearer credentials need a stable principal and exact Agent binding

A bearer is a short-lived credential, not the business identity of Work. Qwen keeps one backend Session under a stable `owner + backend` key, independent of voice-browser session and Work IDs, and persists the native ACP session ID with its `cwd` ([session identity](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/docs/architecture.md#L140-L159), [resume-or-create implementation](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-backend-adapter.mjs#L343-L395)).

Define an in-memory capability record such as `{credential_id, workspace_id, runtime_generation, agora_agent_id, issued_at, revoked_at}`. Every new bearer must resolve to the same stable Workspace principal when reconnecting, while also being accepted only for the exact currently active Agora Agent session. Starting/stopping/replacing an Agent and rotating/revoking its bearer must be one atomic lifecycle operation. Enforce the design's “one active voice session” assumption rather than relying on the browser UI; Qwen explicitly arbitrates one active voice client and evicts stale holders ([active-client arbitration](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/realtime-gateway.mjs#L294-L349)).

### P0 — Permission uniqueness, delivery state, and timeout suspension

Keeping `respond_permission(decision)` free of ACP authorization IDs is safe only if the runtime transactionally enforces **at most one presented, pending permission per capability/Workspace**. Qwen binds a permission to owner, Session, permission scope, and Work, and rejects decisions for a different owner or a resolved request ([permission record](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/permission-broker.mjs#L51-L81), [owner-scoped response and deduplication](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/permission-broker.mjs#L100-L141)). Preserve the simpler public schema, but enforce a database uniqueness invariant and compare-and-swap states such as `pending → delivering → resolved`; duplicate decisions return the same terminal receipt, and failed/unknown ACP delivery leaves the permission pending for re-announcement.

The approved design says a permission has no TTL, but it does not say that the surrounding ACP prompt timeout pauses. Qwen pauses the active prompt watchdog while `session/request_permission` waits and resumes it after a decision ([permission pause boundary](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L273-L286), [watchdog implementation](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L451-L489)). Add the same invariant or the “no TTL” promise is false in practice.

### P0 — Reconnect must rehydrate an authoritative pending set

“The new bearer can query old Work” is not enough. On a new Agora Agent session, rebind the credential to the stable Workspace principal and restore three classes before declaring voice Work-ready: active Work, the one pending permission, and undelivered/unknown results. Qwen explicitly re-announces pending permission and claims pending completion notifications after Realtime reconnect ([reconnect recovery](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/realtime-gateway.mjs#L1485-L1522)).

Define precedence: permission prompt first, then completion announcements, while status remains queryable. If ngrok restarts with a different public URL, the old Managed Agent configuration is stale; rotate the bearer and recreate/update the Agora Agent before reopening Work acceptance. Reconnect should use bounded exponential backoff with jitter rather than a tight loop; Qwen's current backoff is 500 ms to 10 s with jitter ([backoff](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/reconnect-backoff.mjs#L1-L29)).

### P0 — Fence result delivery to the intended live Agora Agent

The approved Agora Speak path already solves the “MCP cannot push a result” problem; no second MCP tool is needed. However, Speak targets the exact `agentId` returned by Join, accepts at most 512 bytes, and `APPEND` waits for the current interaction ([official Speak reference](https://docs-md.agora.io/en/conversational-ai/rest-api/agent/speak.md)). Store the intended `agent_id`/Workspace generation with each delivery attempt and re-check both immediately before submission. A result recovered into a replacement Agent must be deliberately rebound, never accidentally sent through a stale ID.

Keep the existing `pending_delivery / sending / accepted / delivery_unknown` contract. Agora documents HTTP 200 as “starts to broadcast,” not as client playback completion ([official Speak response semantics](https://docs-md.agora.io/en/conversational-ai/rest-api/agent/speak.md)); the design is correct not to claim exactly-once playback. Qwen can wait for a client playback-start receipt because it owns the Realtime client and announcement channel ([playback acknowledgement](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/announcement/announcement-manager.mjs#L273-L321)); that guarantee is not automatically available to the Managed Agent + Speak architecture.

### P1 — Separate barge-in, Work cancellation, and late ACP events

Add an explicit invariant and test: voice barge-in may interrupt current/queued speech, but never calls `cancel_work`. Qwen's interrupt handler cancels only the Realtime response path ([voice interrupt](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/realtime-gateway.mjs#L1998-L2005)); ACP cancellation is a separate `session/cancel` route ([ACP cancel](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L480-L518)). Agora likewise exposes Agent speech/thought interruption as an Agent endpoint, distinct from local Work cancellation ([official Interrupt reference](https://docs-md.agora.io/en/conversational-ai/rest-api/agent/interrupt.md)).

Also assign a local prompt generation to every ACP Work. Accept `session/update`, permission requests, and final text only while that generation is current; discard late events after cancel/terminal transition so they cannot attach to the next Work sharing the persistent ACP Session. Qwen keeps exactly one active prompt per ACP Session and removes its update collector in `finally` ([active-prompt fence](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L436-L511)).

### P1 — Make backpressure and shutdown drain measurable

Agora can stop waiting when MCP `timeout_ms` expires ([official Join reference](https://docs-md.agora.io/en/conversational-ai/rest-api/agent/join.md)). Specify an acceptance SLA comfortably below that timeout, including SQLite commit, and test a response lost after commit. Add exact maximum sizes for Objective, IDs, MCP body, public activity, stored result, and status response; a per-capability call rate; a status-poll rate; and a bounded total queued byte budget. The approved “no fixed Work-count cap” can remain, but it cannot mean unbounded memory/disk consumption.

Retain both scheduler serialization and an ACP single-active-prompt assertion. Qwen rejects a second concurrent prompt on the same Session ([single-prompt guard](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L436-L479)) and serializes coordinator turns separately ([owner serialization](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-backend-adapter.mjs#L1202-L1231)).

On shutdown, first revoke ingress and stop accepting new MCP calls, then drain already-committed handlers to a deadline, cancel active prompts, and terminate the full ACP process group. Qwen launches ACP detached and escalates its process tree from `SIGTERM` to `SIGKILL` after a grace period ([process launch](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L147-L182), [tree cleanup](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/acp-process-client.mjs#L619-L642)). The repo's existing single-supervisor work is compatible with this; the missing piece is an explicit MCP drain deadline and committed-call recovery test.

## Qwen-specific choices not to copy

- **Do not copy session-wide auto-approval.** Current Qwen exposes `always`, which can select `allow_once` or `allow_always` and enables automatic approval later in the frontend session ([tool schema](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/voice/frontend-tools.mjs#L158-L179), [option selection](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/server/src/agent/permission-broker.mjs#L19-L27)). Keep this recipe's current-operation-only `allow/reject` mapping.
- **Do not expose ACP authorization IDs to the Voice LLM.** Qwen does so because its frontend owns the complete permission exchange. The single-pending-permission invariant lets this recipe keep protocol IDs private.
- **Do not proxy the realtime model locally.** Qwen owns provider WebSockets, audio buffering, and provider reconnect. Agora Managed Voice LLM owns that layer here; only MCP crosses ngrok.
- **Do not inject arbitrary backend results into a second LLM turn.** Qwen uses Realtime to adapt result material ([result contract](https://github.com/QwenAudio/qwen-audio-agent/blob/a087a5ee35a730ae195444d08738a6f351017a1b/docs/architecture.md#L205-L231)). Keep deterministic bounded Agora Speak plus the read-only panel and grounded status lookup.
- **Do not copy multi-backend Session delegation, persistent memory, reminders, or UI task control.** They solve a broader desktop-assistant product and are outside v0.1.

## Acceptance tests to add

1. Original MCP call, duplicate transport retry, and duplicate model call produce one receipt without trusting a model-authored random key.
2. A late tool call from an interrupted/superseded voice turn creates no Work.
3. Permission waiting longer than the normal ACP prompt timeout remains pending; allow/reject resumes the same prompt exactly once.
4. Permission decision delivery failure rolls back to pending and re-announces after reconnect.
5. Bearer rotation preserves the Workspace principal but rejects calls from the stopped/replaced Agora Agent.
6. Reconnect restores active Work, pending permission, and unresolved results in the defined priority order.
7. Speak is never sent to a stale `agent_id`; unknown delivery is not retried automatically.
8. Barge-in interrupts speech only; explicit `cancel_work` is required to cancel ACP Work.
9. Late ACP updates after cancel/completion cannot mutate the next Work.
10. MCP timeout, body/field limits, call-rate limits, queued-byte budget, drain deadline, and ACP descendant cleanup are exercised with fake Agora/ngrok/ACP components.
