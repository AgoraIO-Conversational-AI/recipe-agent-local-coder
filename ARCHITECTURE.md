# Agora Conversational AI Demo — Architecture

This quickstart keeps the web UI and backend responsibilities separate. The Next.js app owns the browser-facing `/api/*` URLs, and `next.config.ts` rewrites them to the Python FastAPI service that owns token generation and agent lifecycle.

## Python-Backed Request Flow

```
Browser
  ↓
Next.js app
  ↓
/api/* rewrites through AGENT_BACKEND_URL
  ↓
FastAPI service
  ↓
Agora Cloud Services
```

- `web` owns the browser UI and the `/api/*` entrypoints
- `server` owns the actual token generation and agent start/stop logic
- this is the mode used by `bun run dev`

## Local Codex Foundation

`bun run dev:codex` is a separate local-development entry point. It starts
FastAPI and Next on loopback interfaces and does not start an Agora agent until
the user presses **Start conversation**. It also does not start ngrok.

```text
Browser Settings gate
  -> Next /api/local/* rewrites
  -> loopback FastAPI /local/*
  -> WorkspaceService (durable one-folder scope)
  -> LocalRuntimeCoordinator
  -> one ACP child process + one ACP session
```

The browser opens Settings automatically when the Codex profile has no valid
Project Folder. The native macOS picker is invoked by the loopback backend, not
the browser. The selected resolved directory is persisted in
`~/Library/Application Support/Agora Voice ACP/workspace.json` by default (or
under `VOICE_ACP_STATE_DIR`). The Project Folder is session context, not a
filesystem sandbox.

`LocalRuntimeCoordinator` permits at most one session. It starts only after a
valid folder exists, closes an old session before opening a replacement, and
returns `configuration_required`, `starting`, `authentication_required`,
`ready`, or `failed` without exposing ACP protocol data.

`CodexAcpClient` owns the child-process boundary. Its default command is
`npx -y @agentclientprotocol/codex-acp@1.1.7` with `INITIAL_AGENT_MODE=agent`;
it initializes ACP, selects the advertised ChatGPT auth method only when one is
advertised, and creates one session with the resolved folder and `mcp_servers=[]`.
No API-key authentication mode is configured. Backend callers can inject a
`CodexCommand` or argv sequence for advanced use; `CODEX_PATH` is not an
implemented environment override in v0.1.

## Shared Conversation Flow

### 1. Connection

```
Frontend: GET /api/get_config
  → Generate Token007 config for a user UID, agent UID, and channel
  → Frontend joins RTC and logs into RTM
```

### 2. Agent Start

```
Frontend: POST /api/startAgent { channelName, rtcUid, userUid }
  → Build agent session
  → Scope remote_uids to the requesting user
  → Start session and return agent_id
```

### 3. Conversation

```
User audio → RTC
  → Managed ASR, LLM, and TTS pipeline
  → Agent audio + RTM transcript events
  → UIKit transcript and visualizer in the web app
```

### 4. Agent Stop

```
Frontend: POST /api/stopAgent { agentId }
  → Stop session directly or through stateless fallback
  → Client cleans up RTC and RTM state
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/get_config` | GET | Generate connection config (Token007, channel, UIDs) |
| `/startAgent` | POST | Start the agent session |
| `/stopAgent` | POST | Stop the agent by `agent_id` |

The following derivative extension routes are loopback-only and are not part of
the reusable three-route quickstart contract:

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/local/workspace` | GET | Return Project Folder profile, scope, and state |
| `/local/workspace` | PUT | Resolve, persist, and activate an existing Project Folder |
| `/local/workspace` | DELETE | Close local ACP and clear the saved selection |
| `/local/workspace/browse` | POST | Open the backend-owned native macOS folder picker |
| `/local/runtime` | GET | Return safe local ACP readiness state |

Frontend calls these as `/api/*`. Next rewrites those calls to `AGENT_BACKEND_URL`; the Next app does not run token or AgentKit logic in-process.

## Authentication

Token007 (AccessToken2) — generated from `AGORA_APP_ID` + `AGORA_APP_CERTIFICATE` only. No API_KEY/API_SECRET needed. The SDK handles token generation and API auth internally.

## Managed-path evidence ingress

The Managed Voice LLM evidence harness adds two ASGI surfaces in one local process so they can share process-local validation state:

```text
Browser -> loopback FastAPI:8000 -> agent lifecycle and local seed controls
Agora Cloud -> ngrok -> public ASGI:8001 -> authenticated /mcp only
```

`server/src/architecture_validation/public_server.py` constructs the public surface. It contains the Streamable HTTP MCP app and no token, agent lifecycle, seed, diagnostics, or report routes. Every MCP request requires a runner-issued, per-session capability. `server/src/server.py` mounts the validation admin router, whose handlers reject non-loopback clients.

The live runner must own both listeners in one process. Running the public app separately would create another in-memory capability registry and is unsupported. The four MCP tools operate on synthetic receipts only; they do not start ACP, coding agents, commands, or file operations.

The existing authenticated Agent session replaces the complete `llm.system_messages` list with the base prompt plus at most one bounded current permission. The same session announces the question with one `say(..., priority="APPEND", interruptable=True)` call. No separate model-provider credentials or public LLM callback are required.

`server/src/architecture_validation/config.py` reads the versioned evidence controls once. `server/src/agent.py` always builds the Agora-managed `OpenAI` provider with the prompt, model controls, history, MCP endpoint, bearer header, allowed tools, STT, TTS, turn detection, and session settings.

The interactive runner owns both Uvicorn listeners, rotates the active scenario on the same per-session capability, seeds only synthetic state, and appends recursively redacted JSONL evidence. Invalidated operator/setup attempts remain in evidence under unique IDs and are rerun. The harness is optional and consumes live Agora usage when run.

## Verification Boundary

The offline suite verifies fake ACP protocol behavior, workspace persistence,
loopback guards, rewrite contracts, fake FastAPI proxying, and web build output.
It does not prove that `npx` can download/run the pinned ACP package, that a
browser can complete ChatGPT authentication, that the native picker works on a
developer machine, or that an Agora conversation/ngrok ingress succeeds. Run
those live/manual checks only with the appropriate credentials and authorization.

## Detailed Documentation

- [docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) — web ↔ FastAPI topology, rewrites, lifecycle
- [docs/ai/L1/03_code_map.md](./docs/ai/L1/03_code_map.md) — where code lives under `web/` and `server/`
- [AGENTS.md](./AGENTS.md) — AI agent development guide
- [README.md](./README.md) — Quick start, configuration, deployment
