# Agora Voice-to-ACP Local Recipe v0.1 Design

Date: 2026-08-15

Status: Approved

## 1. Purpose

Build an Agora developer recipe that lets a user speak to an Agora Conversational AI agent and delegate long-running coding work to Codex in a local macOS Project Folder through ACP.

The recipe demonstrates an Agora-native integration. It does not fork `qwen-audio-agent`, implement the ACP protocol, or become a desktop product. It uses the official Agora Python quickstart as its engineering baseline and the official ACP Python SDK as its protocol implementation.

The defining user experience is:

1. The developer starts the cloned Recipe with one command and selects the target Project Folder in Settings when required.
2. The user speaks normally with the Agora agent.
3. Work that requires code execution is accepted immediately and continues in the background.
4. The user can continue talking, ask for status, answer permission requests, or cancel the work by voice.
5. A small read-only activity panel shows safe progress.
6. The result is submitted back to the voice session with local deduplication.

## 2. Product decisions

- Repository form: an Agora official-style developer recipe named `recipe-agent-acp-local`.
- Engineering baseline: [`agent-quickstart-python`](https://github.com/AgoraIO-Conversational-AI/agent-quickstart-python).
- Voice pipeline: Agora-managed cascading STT, OpenAI LLM, and TTS. Managed Voice LLM is the only v0.1 path, as recorded in [ADR 0004](../../adr/0004-select-managed-voice-llm-path.md).
- Tool ingress: the Managed Voice LLM uses Agora MCP tools through a public Streamable HTTP endpoint, following [`recipe-agent-mcp`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-mcp).
- Coding backend: Codex through [`codex-acp`](https://github.com/agentclientprotocol/codex-acp).
- ACP implementation: the official [`agent-client-protocol` Python SDK](https://github.com/agentclientprotocol/python-sdk), stable ACP v1.
- Platform: macOS Apple Silicon is the only Certified platform in v0.1.
- UI: a small read-only task activity panel plus local configuration Settings; voice remains the only Work-control surface.
- Network bridge: ngrok for local development only.
- Permissions: the voice layer offers only allow or reject for the current operation. The Permission Broker maps that explicit current-turn decision to an ACP current-operation option and never creates session-level automatic approval.
- Distribution: v0.1 is repo-first; a versioned launcher package is a recorded post-POC improvement, not a release requirement.
- Work model: one Work type using backend-native permissions; v0.1 has no per-work read-only/change mode or frontend-defined permission policy.
- Routing: the Managed Voice LLM performs context-sensitive Semantic Routing constrained by prompts, hard guards, and a versioned Routing Evaluation corpus; v0.1 has no keyword intent classifier.
- Workspace model: Workspace Scope is an ACP-level abstraction rather than a Codex-specific concept. Agent Profiles declare whether a primary directory is required and whether additional directories are supported. The v0.1 Codex profile requires exactly one primary directory.
- Project language: source code, UI copy, documentation, examples, configuration, logs, tests, issues, and release materials are English-only. Users may still speak any language supported by the configured voice pipeline.
- Project Folder settings: the voice page owns one Settings modal. It opens automatically as a blocking Configuration Gate when the selected Agent Profile requires a primary directory and none is configured; otherwise it remains available without prompting.
- Filesystem boundary: Project Folder sets ACP session context and relative-path resolution; it is not presented or enforced as a filesystem sandbox. Codex-native sandbox and operation permissions remain authoritative.
- Task history: the read-only panel restores only the 20 most recent terminal Work receipts for the current Workspace Scope; v0.1 has no time TTL, global history, or cross-folder history. Records with unresolved result delivery are retained outside that cap until resolved.
- Agent selection: v0.1 fixes the user-facing backend to Codex and exposes no Agent selector. A selector enters product scope only after a second backend passes the Certified support suite.
- Queue capacity: v0.1 applies no fixed count limit to queued Work. FIFO serialization, idempotency, Permission Gate, and local queue-depth diagnostics provide the initial controls; a product cap requires evidence from the controlled trial.
- Result contract: completed Work stores a backend-neutral Final Presentation containing required `speech` and optional safe-Markdown `inline`; the Task Runtime does not parse Codex-specific changed-file or test-result structures.
- Speech projection: every result announcement is one deterministic Agora Speak payload of at most 512 UTF-8 bytes, sent with `priority: APPEND` and `interruptable: true`; projection performs no additional LLM call or multi-part broadcast.

## 3. Scope

### 3.1 Included

- One developer and one explicitly selected local Workspace Scope containing one primary directory.
- One active Agora voice-agent session.
- One persistent Codex ACP session for the Workspace Scope while the runner is alive.
- A serial work queue for that Workspace Scope.
- Voice tools for starting work, querying status, cancelling work, and responding to permissions.
- SQLite persistence for work receipts, safe activity events, permission summaries, results, and delivery state.
- Background execution after the originating MCP call returns.
- Read-only progress delivered to the local web client over SSE.
- Result delivery through the Agora Speak API when a live session is available.
- Custom ACP command support as an experimental Compatible path.
- Managed Voice LLM context updates and authenticated MCP ingress.

### 3.2 Excluded

- A Recipe-owned LLM callback or tool loop, persistent LLM conversation store, custom STT, custom LLM, or custom TTS.
- Windows, Linux, or Intel Mac certification.
- A desktop application, menu-bar application, installer, or background daemon.
- A published npm launcher package or automated package-release pipeline.
- A full task dashboard, editable task controls, raw terminal streaming, or diff viewer.
- Multiple users, tenants, Workspace Scopes, or simultaneous ACP sessions.
- Multi-agent routing, subagent topology, and backend-session delegation.
- Investigation/Change Work subtypes and per-work session-mode switching.
- Resuming in-flight Codex execution after Local Runner restart.
- Production remote access through ngrok.
- Cloud sandboxes, scheduled tasks, long-term memory, and provider marketplace UI.
- A Recipe-owned filesystem sandbox or claim that Project Folder is the only directory the ACP Agent can access.

## 4. Architecture

```text
Quickstart Web
  |-- Agora RTC: microphone and agent audio
  |-- Agora RTM: transcript, agent state, metrics, errors
  `-- Local SSE: read-only work activity
             |
             v
Agora Conversational AI
  |-- managed STT
  |-- Managed Voice LLM
  |-- MCP tools through Streamable HTTP
  `-- managed TTS
             |
             v
Local Public Ingress
  `-- MCP Gateway
             |
             v
Task Runtime
  |-- Work Store
  |-- Serial Queue
  |-- Permission Broker
  |-- Result Notifier
  `-- ACP Process Manager
             |
             | official ACP Python client over local stdio
             v
codex-acp -> Codex App Server -> Codex
```

The ngrok tunnel exposes only the authenticated MCP listener. Quickstart token endpoints, Agora agent lifecycle endpoints, local SSE, diagnostics, SQLite, and any LLM callback route remain unavailable publicly even if the upstream recipe mounts other routes in one FastAPI process.

ACP never traverses ngrok. The Local Runner starts `codex-acp` as a child process and communicates over stdio.

## 5. Component boundaries

### 5.1 Quickstart Web

The web application retains the quickstart's RTC and RTM responsibilities. It adds one collapsible, read-only activity panel connected to the local backend through the existing Next.js API proxy. The panel restores Scoped Work History: active Work plus at most the 20 most recent terminal Work receipts belonging to the active Workspace Scope, ordered newest first. Unresolved delivery records remain visible even when that makes the recovery set exceed 20.

It does not create, approve, reject, cancel, or retry work. Closing the panel or browser cannot cancel a task.

The same voice page has a persistent **Settings** entry for local configuration. For the Codex profile, Settings contains **Project Folder**, the resolved current path, and a **Browse...** action. If no valid Project Folder has been saved, or the saved directory no longer resolves, the modal opens automatically, cannot be dismissed into a Ready state, and explains that voice and coding start after a folder is selected.

Settings identifies Codex as the active coding Agent but provides no Agent selector, disabled provider cards, or roadmap options. The profile is selected by the v0.1 launcher rather than by an end-user control.

The browser never receives general filesystem access. **Browse...** calls an authenticated loopback control route, and the Local Runner opens the macOS native directory picker. Only the selected absolute directory is returned to the page. Manual path entry may be retained as an Advanced option.

Project Folder may change only when every Work is terminal and no Pending Permission exists. During the transition, Work Acceptance is disabled, the old ACP Session is closed, a new Workspace Scope is selected, and a new ACP Session is created. Normal voice conversation may remain connected, but it must describe the backend as temporarily unavailable until the new session is Ready. Historical Work remains bound to its original Workspace Scope and is not presented as activity for the newly selected folder. Manually selecting the original folder again restores that folder's Scoped Work History.

v0.1 persists exactly one current Project Folder. It provides no Recent Folders list, folder favorites, or folder-history store. Changing the folder replaces the saved selection after the new directory passes validation; failure leaves the previous valid selection unchanged.

The activity panel provides no global history page, cross-folder search, or folder switcher. Scoped Work History does not create a Recent Folders feature; Work records are retrieved only after the developer independently selects a matching Project Folder.

For completed Work, the panel renders `Final Presentation.inline` when present and otherwise renders `Final Presentation.speech`. Rendering permits sanitized Markdown, code blocks, and ordinary HTTPS links. It strips arbitrary HTML and does not fetch or embed remote images, audio, video, or other media in v0.1.

### 5.2 Agora agent and Voice LLM configuration

The backend configures one MCP server and enables tools. Its Voice LLM instructions distinguish normal conversation from work requiring files, commands, code, applications, current information, or multiple steps.

The Managed Voice LLM owns natural-language interpretation only. It does not plan or execute coding work.

Work Acceptance authorizes delegation of the bounded Objective, not every operation the ACP Agent may later propose. The Objective must preserve whether the user asked to investigate, explain, modify, create, run, or verify; the voice layer must not broaden one verb into another.

Semantic Routing chooses among five outcomes:

- answer from the current conversation without Work;
- accept Work when the request is complete and requires local project access or execution;
- ask one necessary clarification when the Objective is incomplete or its referent is ambiguous;
- query or cancel existing Work when the user refers to prior work;
- relay an explicit Operation Authorization when a permission request is pending.

No keyword list, regular expression, or imperative-verb classifier defines these outcomes. Programmatic guards reject an empty Objective, duplicate submission in the same turn, a missing, invalid, or inactive Workspace Scope, an invalid Work reference, or an uncorrelated permission response.

Permission Gate takes precedence over new Work Acceptance. While a Pending Permission exists, ordinary conversation, `get_work_status`, `respond_permission`, and `cancel_work` remain available, but `start_work` returns `permission_decision_required` and creates no receipt. The Voice LLM asks the user to allow, reject, or cancel the current Work before submitting another executable objective.

Work Grounding applies to every question or follow-up about a Work's status, result, failure, permission, or prior outcome. The Voice LLM must call `get_work_status` before answering, even when the result was recently spoken or appears in conversation history. Task Runtime state is authoritative; `/speak` output is only a notification.

A follow-up that introduces a new executable intent creates a new Work rather than reopening a completed receipt. Its Objective preserves the user's semantic reference to earlier Work, and the recent conversation plus persistent Codex ACP Session carries the execution context. v0.1 stores no `parent_work_id` or `related_work_id` between ordinary Work receipts. If the referent cannot be resolved reliably, Semantic Routing asks one clarification before Work Acceptance.

The Managed Voice LLM uses live agent instructions plus Agora speech delivery to place one Pending Permission into the next voice turn. One successful live Managed conversation established connectivity, while offline tests cover context replacement, permission correlation, MCP tool guards, capability isolation, and route isolation. The originally planned comparative live matrix was not completed because it would consume limited Agora project minutes; therefore the decision makes no comparative quality or latency claim. The Custom LLM endpoint pattern remains a future alternative and is not maintained as a v0.1 runtime path.

### 5.3 Local MCP Gateway

The gateway exposes four tools:

- `start_work(objective, idempotency_key)`
- `get_work_status(work_id?)`
- `cancel_work(work_id?)`
- `respond_permission(decision)` where `decision` is `allow` or `reject`

For the single-Workspace-Scope v0.1, omitted `work_id` means the current active work or, when no work is active, the most recent work. If the reference is ambiguous, the tool returns a clarification response without changing state.

The MCP gateway validates the per-run capability token, payload size, tool arguments, Workspace Scope binding, and idempotency before invoking the Task Runtime. It contains no ACP process or work-state logic.

### 5.4 Task Runtime

The Task Runtime is a small coordinator, not a general workflow engine. It owns:

- durable work receipts;
- a serial queue;
- the current work state;
- ACP session and child-process lifecycle;
- permission correlation;
- cancellation confirmation;
- safe activity projection;
- result delivery and deduplication.

It never mirrors the ACP agent's internal task graph, raw reasoning, subagent topology, or private identifiers.

### 5.5 ACP Process Manager

The process manager launches a pinned, tested `@agentclientprotocol/codex-acp` package with `npx -y`, negotiates ACP v1 capabilities, authenticates when required, creates a session for the resolved Workspace Scope, sends prompts, consumes session updates, returns permission choices, and cancels prompts.

`primary_directory` supplies the ACP session working directory and relative-path base. The Local Runner validates that it is a real selected directory and binds Work to that session, but does not intercept system calls or guarantee that the Agent cannot address paths outside it. UI and documentation must describe Project Folder as **where the Agent works**, never as **the only folder the Agent can access**. Codex's native sandbox, permission requests, and user configuration govern any operation beyond that context.

The published `codex-acp` package includes a compatible Codex dependency. A user-supplied `CODEX_PATH` remains an advanced override rather than a prerequisite.

The default Codex mode is the normal agent/native-approval mode. `agent-full-access` is never selected automatically.

The mode does not change per Work. An investigation objective remains bounded by its requested scope and the backend's native permission requests rather than by a frontend-selected read-only mode.

### 5.6 Work Store

SQLite stores:

- work identifier and idempotency key;
- bounded objective summary;
- Workspace Scope identity, stored as a local reference; the UI exposes only the safe Project Folder label and resolved primary path;
- timestamps and state transitions;
- redacted activity events;
- the current bounded permission request and ACP option identifiers;
- Final Presentation and safe error summary;
- result delivery state.

Work queries and SSE replay are always filtered by the active Workspace Scope. The activity panel receives active Work, the 20 most recent terminal receipts, and any additional records whose delivery state is unresolved. There is no time-based TTL. After any Work becomes both terminal and delivery-resolved, the store prunes the oldest delivery-resolved terminal records until no more than 20 remain for that Workspace Scope. `pending_delivery` and `delivery_unknown` records are never pruned by this cap and never enter another folder's visible history.

Secrets, raw reasoning, environment variables, complete terminal output, and authentication material are not stored.

## 6. Onboarding and developer experience

The developer clones the Recipe once. The default v0.1 command is run from the Recipe repository without requiring a Project Folder argument:

```bash
cd /path/to/recipe-agent-acp-local
bun run dev:codex
```

The command does not modify the target repository or require a global Codex or `codex-acp` installation. After the POC is validated, the same launcher behavior can be packaged so a developer can run a versioned `bunx` command directly from the target Project Folder.

The Local Runner first starts only the loopback control backend and web client. If the Codex profile has no saved Project Folder, the voice page enters Configuration Gate and automatically opens Project Folder Settings. The developer chooses a directory with the Local Runner's native macOS picker. The resolved selection becomes `primary_directory`, is stored locally, and is reused on later starts without prompting. Settings remains visible so the developer can change it later. An explicit `--workspace /path/to/project` remains an Advanced startup override that proposes the same value through the same selection and validation path.

The first run permits only the necessary interactions for the Managed Voice LLM path:

1. select and confirm the resolved Project Folder in Settings;
2. complete ChatGPT authentication in a browser if Codex is not already authenticated;
3. complete ngrok authentication if it is not configured;

After the Configuration Gate is cleared, the launcher:

1. validates macOS, Apple Silicon, Bun/Node, Python, Agora configuration, and ngrok;
2. provisions the recipe's locked Python environment in its user cache;
3. prepares an MCP listener that is not yet exposed;
4. starts `codex-acp` without requiring a global installation;
5. completes the ACP handshake, reuses existing Codex authentication when available, or selects the ACP-advertised ChatGPT method and opens its browser flow;
6. creates the ACP session for the resolved Workspace Scope;
7. starts ngrok and generates the public capability endpoint only after ACP is ready;
8. starts the Agora backend and quickstart web client; the voice Agent session starts when the client joins;
9. runs health checks across the local services;
10. reports a single Ready state.

Agora credentials, ngrok credentials, API keys, and other secrets are entered locally through environment files or provider login. They are never requested in chat, printed in full, or committed.

Default Codex Authentication exposes no method picker and requires no terminal login command. After successful browser authentication, startup resumes automatically and later runs reuse Codex's normal user-level authentication. `CODEX_API_KEY`, `OPENAI_API_KEY`, and custom gateway authentication remain documented Advanced paths.

Advanced overrides include `--workspace`, a Codex binary path, or a custom ACP command. They do not change the default one-command path or bypass Project Folder validation.

## 7. Agent support model

The product distinguishes protocol compatibility from tested support.

### 7.1 Support levels

- **Certified:** Agora has tested installation, authentication, session creation, streaming activity, permissions, cancellation, completion, failure handling, and the supported platform.
- **Compatible:** the user supplies an ACP v1 stdio command; the generic client connects based on negotiated capabilities, without an end-to-end product guarantee.
- **Detected:** handshake succeeds, but capabilities required for the expected voice workflow are missing.
- **Unsupported:** incompatible protocol, unsupported transport, or a missing critical capability prevents safe execution.

### 7.2 Rollout order

- v0.1 Certified: Codex on macOS Apple Silicon.
- First expansion candidates: Qwen Code and OpenCode.
- Later candidates: Claude Agent ACP and Gemini CLI.
- Any other ACP v1 stdio agent: Compatible custom-command path.

Agent differences belong in declarative profiles and negotiated capability policy. The runtime does not create a separate full adapter per agent. Local compatibility exceptions are allowed only when capability negotiation cannot represent a verified standards deviation.

Each Agent Profile declares `requires_workspace` and `supports_additional_directories`. The Codex v0.1 profile sets these to `true` and `false`, respectively. A future non-project ACP Agent may set `requires_workspace` to `false`; the UI then hides Project Folder and the Local Runner supplies an isolated internal working directory. MCP tools remain separate from Workspace Scope because their own server configuration defines their access.

Protocol compatibility alone does not make an Agent user-selectable. v0.1 always selects the Codex profile and has no product UI for switching backends. A visible Agent selector is deferred until at least two profiles are Certified, so every displayed option has a tested authentication, permission, cancellation, activity, and completion experience.

## 8. Work lifecycle

The public work state machine is:

```text
queued -> starting -> running <-> awaiting_permission
                       |                 |
                       |                 `-> cancelling -> cancelled | failed
                       `-> completed | cancelling -> cancelled | failed
```

Rules:

- `start_work` persists the receipt before returning and never waits for Codex completion.
- The Workspace Scope queue executes one work item at a time.
- The queue has no fixed v0.1 Work-count limit. Queue depth is exposed only through safe local diagnostics and test instrumentation, not as a user-configurable concurrency control.
- While a Work is `starting` or `running`, new executable requests may be durably accepted as separate queued Work receipts. They never create concurrent prompts in the Codex ACP Session.
- Normal voice conversation continues while work is queued or running.
- A duplicate idempotency key returns the existing receipt and never creates duplicate coding work.
- Cancellation remains `cancelling` until ACP confirms cancellation or returns a failure. The UI shows the bounded label "Cancelling" during this transition.
- Local Runner restart marks active work failed with an explicit restart reason. Completed results and undelivered results remain durable.
- A new executable follow-up creates a new Work; terminal Work is immutable and never reopened.
- Permission Gate is the only Work-state rule that temporarily prevents new Work Acceptance; a merely running Work does not.

## 9. Permission flow

ACP remains the authority for whether a current-operation permission choice exists. The voice contract intentionally normalizes the interaction to two actions: allow the current operation or reject the current operation. It never exposes or selects `allow_always`, creates a Gateway session policy, or treats a natural "yes" as authorization for later operations.

The flow is:

1. `codex-acp` sends an ACP permission request with a bounded operation summary and option list.
2. The Permission Broker redacts secret-like values, stores the request, and moves the work to `awaiting_permission`.
3. The result notifier naturally asks whether to allow the current operation; it does not read protocol options or require a fixed phrase.
4. The Managed Voice LLM calls `respond_permission(decision)` only when the current user utterance clearly allows or rejects that current operation.
5. For `allow`, the broker selects an ACP `allow_once` option. If none exists, it returns no authorization and explains that the backend does not offer a voice-safe current-operation grant.
6. For `reject`, the broker selects `reject_once` when available; otherwise it returns ACP `cancelled`. It never selects a permanent rejection option on the user's behalf.

There is at most one Pending Permission in v0.1. It has no TTL: elapsed time and unrelated conversation never approve, reject, cancel, or otherwise resolve it. It ends only through an explicit user selection, Work cancellation, ACP cancellation, or Local Runner exit. If the voice session disconnects, the Pending Permission remains stored and is presented again after reconnection. The user may cancel the Work by voice instead.

While it remains pending, Permission Gate prevents new Work Acceptance. The queue therefore cannot accumulate executable Work behind an unresolved authorization request.

The read-only UI does not approve, reject, cancel, or otherwise control the task.

## 10. Progress and task UI

ACP `session/update` notifications are mapped to a bounded public activity vocabulary, such as:

- accepted task;
- inspecting files;
- editing code;
- running tests;
- waiting for permission;
- organizing result;
- completed, failed, or cancelled.

The mapper excludes raw chain-of-thought, complete command output, internal IDs, unredacted paths, environment values, secrets, and subagent topology.

Safe events are appended to SQLite and streamed to the local web client through SSE. SSE reconnect uses the last event identifier to replay missed events without polling.

The collapsible panel shows:

- the current task's bounded summary;
- state and elapsed time;
- safe activity timeline;
- pending permission summary with an instruction to answer by voice;
- the Final Presentation's safe `inline` content, or its semantic result fallback;
- a small recent-work history.

The panel has no approval, rejection, cancellation, retry, or mutation controls.

## 11. Result delivery

The Task Runtime stores the Final Presentation before attempting delivery:

```json
{
  "speech": "Concise semantic result for the live conversation.",
  "inline": "Optional safe Markdown, code, or HTTPS links."
}
```

`speech` is required, ready-to-broadcast text. Agora Speak sends its `text` directly through TTS and does not perform another LLM rewrite. Each Speak request must therefore satisfy Agora's 512-byte text limit. Logs, diffs, and long code are not read aloud. `inline` is optional and backend-neutral. The Task Runtime stores and projects it without extracting changed-file lists, test-result fields, or other Codex-specific report structure.

When an Agora agent session is active, the Result Notifier waits for an Announcement Window in which neither the user nor the Voice Agent is speaking, then uses the Agora Speak API with `priority: APPEND` and `interruptable: true`.

Pending Permission questions have priority over completion notifications. Before submission, Speech Projection converts every deliverable result in the window into one payload no longer than 512 UTF-8 bytes:

- for one result already within the limit, use its `speech` unchanged;
- for one oversized result, keep complete sentences that fit and append `See the task panel for details.`;
- for multiple results, announce the count and include bounded per-Work summaries in completion order, shortening at character and sentence boundaries as needed;
- if even meaningful per-Work summaries cannot fit, announce the count and direct the user to the task panel.

Projection operates on stored text only. It makes no LLM or ACP call, never cuts through a UTF-8 character, and never splits one announcement into multiple Speak requests. Optional `inline` content remains complete in the read-only panel, and all results remain available through Work Grounding.

If no voice session is active, the result remains `pending_delivery`. On the next connection, the runtime attempts delivery.

Speaking a result does not make it authoritative model context. A later question such as "did the tests pass?" or "fix what you found" first resolves the referenced Work through `get_work_status`; the Voice LLM does not infer the answer from the prior announcement.

Delivery uses four local states: `pending_delivery`, `sending`, `accepted`, and `delivery_unknown`. A Speak API 200 response moves every Work included in that announcement to `accepted`, after which none is submitted again. Explicit 429 or 5xx responses prove that the request was not accepted and are retried up to three times with backoff. A timeout or connection loss after submission moves every included result to `delivery_unknown`; the runtime does not automatically retry because doing so could duplicate speech. The activity panel shows the uncertain delivery state, and a later user status query can retrieve each stored result. This provides local deduplication and at-most-once resubmission after API acceptance, not proof that audio playback completed exactly once.

The cascading STT-LLM-TTS pipeline is required because the Speak API is not supported for the MLLM configuration used by realtime recipes.

## 12. Local-development network security

The v0.1 ngrok integration is explicitly a temporary developer POC, not a production remote-access design.

Each active Agora Agent receives a high-entropy capability token. The launcher
publishes a fixed MCP endpoint and supplies the capability through the Agent's
MCP authorization header:

```text
https://<ephemeral-ngrok-domain>/mcp/
Authorization: Bearer <per-Agent-capability>
```

The MCP listener:

- accepts only an active bearer bound to the current Workspace generation and
  exact Agora Agent ID;
- rejects invalid capabilities before parsing MCP payloads;
- expires the capability when the launcher exits;
- redacts the token from logs;
- validates request size, content type, method, and Origin when present;
- applies per-capability rate limits;
- exposes no management, token, Agora lifecycle, SSE, database, or debug endpoint.

The ingress uses explicit route allowlisting and never exposes an LLM callback. Pointing ngrok directly at an application port that also serves unauthenticated lifecycle endpoints is not permitted.

The listener binds to loopback and is reached publicly only through the active
ngrok process. The capability is a development bearer credential, not full
identity authentication. Documentation must tell users to stop the launcher
when finished and must not recommend unattended or production operation. The
detailed lifecycle and failure contract is defined in
[Managed MCP and ngrok Ingress](2026-08-19-managed-mcp-ngrok-ingress-design.md).

A production evolution replaces ngrok with an authenticated hosted bridge to which the Local Runner creates an outbound connection. That change must not alter the Task Runtime or ACP client interfaces.

## 13. Failure behavior

| Failure | Required behavior |
|---|---|
| Codex unauthenticated | Open the supported login flow before enabling work submission. |
| ACP initialization failure | Fail startup with an actionable diagnostic; create no work. |
| ngrok disconnect | Continue already-running local work and reject new submissions with a retriable unavailable response until the tunnel is healthy. |
| Managed LLM or Agora model service unavailable | Return a bounded retriable voice failure; never reinterpret the failed turn as Work or permission approval. |
| Agora voice session disconnect | Continue work and retain results or permissions for the next connection. |
| `codex-acp` process exits | Fail the active work; restart only for subsequent work. |
| Local Runner restarts | Fail active work; retain completed results and delivery state. |
| Duplicate MCP request | Return the original receipt using the idempotency key. |
| Permission has no user decision | Stay pending; never infer or expand authorization. |
| Speak returns 429 or 5xx | Retry up to three times with backoff, then retain `pending_delivery`. |
| Speak outcome is unknown after submission | Mark `delivery_unknown`, do not auto-retry, and keep the result available through status. |
| Workspace Scope is missing, invalid, or does not match the active ACP Session | Reject before creating an ACP prompt. |

User-facing errors are short, safe, and actionable. Full local diagnostics do not enter speech or the public activity stream.

## 14. Testing strategy

### 14.1 Unit tests

- work state transitions and illegal transitions;
- serial queue ordering;
- acceptance beyond five queued Work without concurrent ACP prompts, plus queue-depth diagnostics;
- acceptance of queued Work during execution without concurrent ACP prompts;
- idempotent start and cancellation;
- Follow-up Work creates a new receipt while reusing the persistent ACP Session and stores no relation field;
- Voice Permission Decision mapping to ACP `allow_once`, `reject_once`, or `cancelled` without broader authorization;
- Pending Permission remains unresolved across elapsed time and voice reconnect until an explicit terminal event;
- Permission Gate rejects new Work creation while preserving conversation, status, permission response, and cancellation;
- activity and error redaction;
- Final Presentation validation, `speech` fallback behavior, safe Markdown rendering, HTTPS-link handling, and remote-media rejection;
- delivery deduplication and restart reconciliation;
- Announcement Window priority, batching, and per-Work delivery-state transitions;
- Speech Projection at UTF-8 boundaries for single and batched results, including the 512-byte invariant and panel fallback;
- Workspace Scope selection, validation, session binding, and path resolution without treating it as a sandbox.

### 14.2 ACP contract tests

A fake ACP v1 agent covers initialize, authentication-required responses, session creation, streaming session updates, permission requests with varied options, prompt completion, cancellation, malformed messages, and process exit.

### 14.3 Routing evaluations

A versioned evaluation corpus covers direct answers, clear executable requests, conversationally phrased questions requiring repository access, non-actionable statements, incomplete objectives, ambiguous references, status queries, cancellation, and permission replies. Each case includes relevant conversation context, pending Work or permission state, available tools, and the expected routing outcome. Release qualification runs the corpus against the Managed Voice LLM; routing behavior is not inferred from prompt inspection alone.

The corpus includes follow-ups immediately after a spoken completion, after unrelated conversation, after reconnect, and while a newer Work exists. Each must use Work Grounding and either resolve the intended Work or ask one clarification rather than relying on remembered speech.

Executable follow-up cases must create a new Work with a faithful Objective; informational follow-ups must not create Work.

When a Pending Permission exists, executable-request cases must return `permission_decision_required` without creating Work, including utterances that mix a new request with ambiguous permission language.

### 14.4 Managed Voice LLM evidence

Release qualification runs the permission and routing corpus against the Managed Voice LLM path. Offline tests cover deterministic context, correlation, tool, capability, and route behavior. Live checks require explicit authorization because they consume Agora conversation minutes. The v0.1 choice is cost-constrained and must not be described as the winner of an uncompleted Managed-versus-Custom benchmark. Revalidation follows the triggers in [ADR 0004](../../adr/0004-select-managed-voice-llm-path.md).

### 14.5 MCP integration tests

Tests exercise tool discovery and every tool through Streamable HTTP, including invalid capabilities, oversized payloads, ambiguous work references, duplicate idempotency keys, and unavailable runtime states.

### 14.6 Web tests

Tests cover SSE connection and replay, state rendering, safe timeline text, Final Presentation rendering without backend-specific field extraction, safe Markdown and code blocks, ordinary HTTPS links, remote-media and arbitrary-HTML rejection, Scoped Work History limited to the current folder's 20 most recent terminal receipts plus active and unresolved-delivery records, count-based pruning without time TTL, permission display, Codex identity without an Agent selector or disabled provider options, and the absence of Work-control elements and sensitive internal data. They also cover automatic Project Folder Settings display when unconfigured or invalid, saved-folder reuse, the persistent Settings entry, the absence of Recent Folders and cross-folder history, native-picker error handling, blocked switching with nonterminal Work or Pending Permission, atomic replacement after validation, successful idle switching without cross-folder activity leakage, and restoration when the original folder is selected again.

### 14.7 Offline system tests

The repository follows the quickstart pattern of fake Agora and fake ACP components so CI can verify startup, API contracts, process cleanup, and the web proxy without live credentials.

### 14.8 Live macOS E2E

Release qualification uses a real Agora project, ngrok, `codex-acp`, ChatGPT authentication, and an isolated disposable repository. It verifies:

- one-command startup after local configuration;
- first-run Project Folder selection through Settings and browser authentication;
- saved Project Folder reuse without prompting and later idle switching through Settings;
- automatic return to Project Folder Settings when the saved directory is missing or invalid, without retaining a recent-folder list;
- restoration of active Work, up to 20 recent terminal receipts, and every unresolved-delivery receipt for only the selected Project Folder, including after restart and after manually switching back;
- automatic reuse of existing Codex authentication and automatic startup continuation after browser login;
- voice work creation with immediate acknowledgment;
- representative Semantic Routing cases from the release corpus;
- continued conversation while Codex works;
- natural voice allow and reject decisions mapped only to current-operation ACP outcomes;
- voice status and cancellation;
- read-only progress updates;
- backend-neutral Final Presentation delivery through `speech` and safe optional `inline` rendering without remote media;
- successful file/test work from the selected Project Folder, with external-path operations governed by Codex-native permissions;
- deduplicated result delivery, including the uncertain-outcome path;
- batched result delivery after a safe Announcement Window without interrupting an active turn;
- one `APPEND`, interruptible Speak request per announcement, always within the 512-byte text limit, with no extra LLM turn;
- tunnel, voice-session, and process disconnect behavior.

Local or mocked tests do not count as proof of live Agora acceptance.

## 15. Acceptance criteria

v0.1 is complete when:

- a developer starts the cloned Recipe with `bun run dev:codex`, selects Project Folder in the voice-page Settings when required, and can later change it from the same entry while all Work is terminal;
- no separate global Codex or `codex-acp` installation is required;
- Codex is the only user-visible Agent and no Agent selector appears;
- the default Codex authentication path requires neither an authentication picker nor a terminal login command;
- the system fails fast before exposing MCP when ACP initialization or authentication is incomplete;
- `start_work` returns after durable acceptance and never waits for coding completion;
- Codex work continues independently of the originating voice turn;
- permissions are granted only through an explicit current-turn voice decision mapped to an ACP `allow_once` option;
- a Pending Permission prevents new Work Acceptance without blocking conversation, Work Grounding, or cancellation;
- voice status and cancellation operate on the correct active work;
- all Work status, result, failure, permission, and follow-up answers are grounded in a current Task Runtime lookup;
- the read-only panel accurately reflects durable work state and safe progress;
- completed Work uses the backend-neutral Final Presentation contract and does not require Codex-specific changed-file or test-result fields;
- the read-only panel shows active Work, at most 20 recent terminal receipts, and any unresolved-delivery receipts from the active Workspace Scope, and never mixes records from another folder;
- a result accepted by the Speak API is never resubmitted, while unavailable or uncertain delivery remains visible and retrievable without claiming playback exactly-once;
- every Speak payload is produced by deterministic Speech Projection, remains within 512 UTF-8 bytes, and is never divided into multiple broadcasts;
- duplicate MCP calls do not duplicate work;
- a process or runner failure cannot leave work permanently marked active;
- no secret, raw reasoning, internal ACP identifier, or unredacted diagnostic appears in speech or the task panel;
- the live macOS E2E suite passes in an isolated repository;
- ADR 0004 remains satisfied or is superseded by a new Voice LLM decision;
- the Managed Voice LLM passes the required Routing Evaluation corpus without a keyword classifier.

## 16. Reference implementations and sources

- [`agent-quickstart-python`](https://github.com/AgoraIO-Conversational-AI/agent-quickstart-python): repository structure, RTC/RTM lifecycle, server-owned credentials, tests, and CI.
- [`recipe-agent-mcp`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-mcp): Agora-managed LLM to public Streamable HTTP MCP.
- [`recipe-agent-custom-llm`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-custom-llm): future reference if provider ownership or a Recipe-owned model callback is reconsidered.
- [`recipe-agent-voice-todo`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-voice-todo): separation of tool handlers, persistent domain state, and independent visual status.
- [`recipe-agent-events`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-events): Agora transcript, state, metric, and error observation.
- [`recipe-agent-webhooks`](https://github.com/AgoraIO-Conversational-AI/recipe-agent-webhooks): append-only event storage, correlation labels, verification, and SSE patterns; Agora NCS events are not used as ACP task events.
- [`qwen-audio-agent` architecture](https://github.com/QwenAudio/qwen-audio-agent/blob/43754ba3023fb1d7f2ba85529e6f7f871d2b9b84/docs/architecture.md): nonblocking work submission, fixed ACP session, permission relay, confirmed cancellation, safe progress projection, and result-delivery semantics.
- [`codex-acp`](https://github.com/agentclientprotocol/codex-acp): Codex ACP server, authentication, capability mapping, and packaged compatible Codex dependency.
- [ACP Python SDK](https://github.com/agentclientprotocol/python-sdk): official ACP v1 client implementation.
- [MCP Streamable HTTP security guidance](https://github.com/modelcontextprotocol/modelcontextprotocol/blob/main/docs/specification/2026-07-28/basic/transports/streamable-http.mdx): loopback binding, Origin validation, and authentication requirements.
- [Agora Speak API](https://docs.agora.io/en/api-reference/api-ref/conversational-ai/speak): direct TTS result delivery for cascading pipelines, including the 512-byte text limit and `APPEND` priority.
