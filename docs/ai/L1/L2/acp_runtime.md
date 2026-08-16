# ACP Runtime

> Local-only foundation for persisted Project Folder context, one ACP
> child-process session, and safe readiness before an Agora conversation starts.

## Scope and Non-Scope

This foundation adds Project Folder selection, durable Workspace Scope state,
the Codex ACP client boundary, and local readiness. It deliberately does not
implement Work receipts, prompt/update mapping, a Permission Broker, cancellation,
authenticated MCP work tools, SSE activity, result delivery, or history.

Project Folder is the user-facing primary directory for ACP session context and
relative paths. It is not a filesystem sandbox, access-control system, or
guarantee that an ACP child process cannot access other files.

## Start and Persist State

Run `bun run dev:codex`. The launcher runs dependency checks, starts FastAPI on
`127.0.0.1:8000` and Next on `127.0.0.1:3000`, and terminates the sibling when
either child exits. It starts neither an Agora conversation nor ngrok by itself.
Before readiness it validates macOS Apple Silicon, Bun/Node/Python, and usable
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
| `POST /api/local/workspace/browse` | `POST /local/workspace/browse` | Run native picker and activate result. |
| `GET /api/local/runtime` | `GET /local/runtime` | Read `LocalRuntimeStatus`; never starts ACP. |
| `POST /api/local/runtime` | `POST /local/runtime` | Explicitly activate ACP for a valid saved Workspace. |

Non-loopback callers receive `403`. Invalid folder selection receives `400`.
Picker cancellation receives `409`. A replacement that cannot make ACP ready
returns `503` and restores the prior persisted folder selection.

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
All paths preserve agent mode and never log child environments. Permission
requests are captured in bounded safe summaries and cancelled by default; an
interactive Permission Broker belongs to the next plan.

## Verification Boundary

`server/tests/acp_runtime/` uses fake ACP clients/processes. Root verification
also uses fake FastAPI and proxy targets. These checks are offline-safe and
verify contracts, lifecycle sequencing, persistence, loopback guards, and UI
build/type behavior.

They do not establish that the real pinned `npx` package installs or runs, that
browser ChatGPT authentication succeeds, that the native picker works on a
developer machine, or that Agora conversation start/ngrok succeeds. Perform
those only as separately authorized live/manual checks.
