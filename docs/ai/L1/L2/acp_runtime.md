# ACP Runtime

> Local-only Project Folder, ACP session, Task Runtime, and authenticated
> Managed Voice LLM ingress.

## Scope and Non-Scope

The local runtime adds Project Folder selection, durable Workspace Scope state,
the Codex ACP client boundary, local readiness, and an offline-tested Task
Runtime Core. The core implements durable Work receipts, serial ACP prompts,
safe update/result mapping, one current-operation Permission Broker,
cancellation, and restart recovery.

It exposes authenticated MCP Work tools only through a dedicated public ASGI
listener. It deliberately does not expose HTTP Work routes, SSE activity, an
Activity Panel, proactive voice result delivery, or transcript/history
projection. The Managed Voice LLM can delegate Work to ACP and poll status.

Project Folder is the user-facing primary directory for ACP session context and
relative paths. It is not a filesystem sandbox, access-control system, or
guarantee that an ACP child process cannot access other files.

## Start and Persist State

Run `bun run dev:codex`. The launcher runs dependency checks, starts FastAPI on
`127.0.0.1:8000` and Next on `127.0.0.1:3000`, and terminates the sibling when
either child exits. It starts neither an Agora conversation nor ngrok until the
user starts a conversation. Before readiness it validates macOS Apple Silicon,
Bun/Node/Python/ngrok, and usable
Agora configuration without printing secret values.

The browser loads Workspace status before a conversation can start. If no valid
folder is saved, Project Folder Settings is a blocking gate. The backend owns a
native macOS picker, with manual path entry available in the UI. The resolved
scope is atomically persisted at:

```text
~/Library/Application Support/Agora Voice ACP/workspace.json
```

Set `VOICE_ACP_STATE_DIR` to use a different parent state directory. The v0.1
Codex Agent Profile requires one primary directory and supports no additional
directories.

## HTTP Contract

Next exposes rewrite routes under `/api/local/*` only when the launcher opts in,
the backend URL is loopback, and Next is not in production mode. FastAPI
implements the matching loopback-only `/local/*` routes. All use the usual
success envelope.

| Browser route | Backend route | Behavior |
| --- | --- | --- |
| `GET /api/local/workspace` | `GET /local/workspace` | Read `WorkspaceStatus`. |
| `PUT /api/local/workspace` | `PUT /local/workspace` | Validate, save, and activate `{ path }`. |
| `DELETE /api/local/workspace` | `DELETE /local/workspace` | Close ACP and clear saved scope. |
| `POST /api/local/workspace/browse` | `POST /local/workspace/browse` | Start the native picker and return `202` plus an opaque operation ID. |
| `GET /api/local/workspace/browse/:operationId` | `GET /local/workspace/browse/{operation_id}` | Poll `picking` to `ready`, `cancelled`, or `failed`; `ready` includes `WorkspaceStatus`. |
| `GET /api/local/runtime` | `GET /local/runtime` | Read `LocalRuntimeStatus`; never starts ACP. |
| `POST /api/local/runtime` | `POST /local/runtime` | Explicitly activate ACP for a valid saved Workspace. |

Non-loopback callers receive `403`. Invalid folder selection receives `400`.
Picker cancellation and activation failures are terminal operation states, so
the start request never stays open behind the Next proxy. A replacement that
cannot make ACP ready restores the prior persisted folder selection.

`WorkspaceStatus.state` is `unconfigured`, `ready`, or `invalid`.
`LocalRuntimeStatus.state` is `configuration_required`, `starting`,
`authentication_required`, `ready`, or `failed`.

## ACP Boundary

`LocalRuntimeCoordinator` serializes starts, replacements, and close operations
so one `AcpClientPort` session is active at most once. It opens only a ready
workspace, closes the old session before opening a replacement, and converts
authentication failures into the user-safe ChatGPT sign-in instruction. Other
failures use one fixed safe message and never include exception text. Ordinary
FastAPI startup invokes only shutdown cleanup; the local browser flow explicitly
starts a saved Workspace.

`CodexAcpClient.close()` is idempotent. It treats only a transport-level
`ConnectionError` from `session/close` as an already completed close and still
exits the child-process context; other failures remain visible.

`CodexAcpClient` validates the resolved absolute directory, owns the child
process, initializes ACP, and creates one session with `mcp_servers=[]`. The
default command is pinned:

```text
npx -y @agentclientprotocol/codex-acp@1.1.7
```

It adds `INITIAL_AGENT_MODE=agent`. When the ACP server advertises a `ChatGPT`
authentication method, the client still tries session creation with reusable
credentials first. Only typed authentication-required invokes that method and
one session-creation retry.

`bun run dev:codex -- --workspace /absolute/path` applies the same Workspace
validation as Settings. `CODEX_PATH`, `CODEX_API_KEY`, and `OPENAI_API_KEY` are
advanced child pass-through values. `--acp-command-json` supplies an
experimental Compatible command as a JSON argv array and never invokes a shell.
All paths preserve agent mode and never log child environments. ACP prompt
callbacks map only safe tool-kind labels, bounded agent text, and bounded
permission questions. Thought content, raw frames, private identifiers,
authentication data, and exception text are not retained.

## Task Runtime Core

`WorkStore` persists Workspace-scoped Work in SQLite before queueing it. It
owns state transitions, idempotency, safe activity, permission records, bounded
final results, and startup recovery. The database file is mode `0600` beneath a
mode-`0700` state directory.

`TaskRuntime` runs one background FIFO worker and at most one ACP prompt. It
accepts Work durably and immediately, executes queued Work serially, aggregates
safe ACP output, and stores a final presentation. There is no small v0.1 queue
cap. A Workspace replacement or clear is rejected while Work or a permission
is nonterminal.

`PermissionBroker` correlates exactly one pending request to its Workspace,
Work, and ACP request. An allow response selects only `allow_once`; a reject
response selects only `reject_once`; otherwise it cancels. There is no
permission timeout. Cancelling queued Work completes locally; cancelling
running or permission-blocked Work calls ACP cancellation and waits for its
completion before recording the terminal state.

The local FastAPI lifespan starts Task Runtime, marks leftover accepted,
queued, running, cancelling, or permission-blocked Work failed after a restart,
and stops Task Runtime before closing the ACP coordinator and SQLite store.
Public app construction creates none of these local objects.

## Managed MCP Ingress

After ACP is ready, Agent preparation starts a dedicated loopback MCP listener
and launcher-owned ngrok tunnel. The Managed LLM receives exactly four tools:
`start_work`, `get_work_status`, `cancel_work`, and `respond_permission`.
Authorization comes from one 256-bit, memory-only bearer bound to the actual
Agora Agent and current Workspace generation. The capability is activated only
after Agent creation succeeds and revoked before Agent or tunnel shutdown.

The Managed Work prompt presents the already-selected Project Folder and
registered tools as capabilities of the voice assistant. Workspace-dependent
requests are delegated as complete natural-language objectives through
`start_work`; the prompt and tool description intentionally contain no task
category list, examples, command requirement, or Workspace path.

Because Agora may initialize MCP before Agent creation returns, the prepared
bearer first enters a pending discovery phase. Only `initialize`,
`notifications/initialized`, `tools/list`, and `ping` are accepted then. Work
tools remain `503 runtime_unavailable` until activation binds the real Agent ID.

The public app contains no lifecycle, settings, admin, docs, or OpenAPI routes.
It authenticates before body reads, applies request-size limits, start/status
budgets, a shared mutation budget, and safe bounded projections. Rate
exhaustion returns HTTP `429`. A background health check closes Work acceptance
on tunnel loss and forces Agent restart when the public URL changes.
SSE/Activity Panel, Agora Speak, proactive announcements, and reconnect
rehydration remain deferred.

## Verification Boundary

`server/tests/acp_runtime/`, `server/tests/task_runtime/`, and
`server/tests/managed_ingress/` use fake ACP, Agent, listener, and ngrok
boundaries. Root verification also uses fake FastAPI and proxy targets.
These checks are offline-safe and verify contracts, prompt/update mapping,
SQLite persistence, FIFO execution, permissions, cancellation, restart
recovery, lifecycle sequencing, loopback guards, and UI build/type behavior.

They do not establish that the real pinned `npx` package installs or runs, that
browser ChatGPT authentication succeeds, that the native picker works on a
developer machine, or that Agora conversation start/ngrok succeeds. Perform
those only as separately authorized live/manual checks.
