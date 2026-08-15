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

Frontend calls these as `/api/*`. Next rewrites those calls to `AGENT_BACKEND_URL`; the Next app does not run token or AgentKit logic in-process.

## Authentication

Token007 (AccessToken2) — generated from `AGORA_APP_ID` + `AGORA_APP_CERTIFICATE` only. No API_KEY/API_SECRET needed. The SDK handles token generation and API auth internally.

## Architecture-validation ingress

The temporary Voice LLM comparison adds two ASGI surfaces in one local process so they can share process-local validation state:

```text
Browser -> loopback FastAPI:8000 -> agent lifecycle and local seed controls
Agora Cloud -> ngrok -> public ASGI:8001 -> authenticated /mcp only
```

`server/src/architecture_validation/public_server.py` constructs the public surface. It contains the Streamable HTTP MCP app and no token, agent lifecycle, seed, diagnostics, or report routes. Every MCP request requires a runner-issued, per-session capability. `server/src/server.py` mounts the validation admin router, whose handlers reject non-loopback clients.

The live runner must own both listeners in one process. Running the public app separately would create another in-memory capability registry and is unsupported. The four MCP tools operate on synthetic receipts only; they do not start ACP, coding agents, commands, or file operations.

For the Managed candidate, the existing authenticated Agent session replaces the complete `llm.system_messages` list with the base prompt plus at most one bounded current permission. The same session announces the question with one `say(..., priority="APPEND", interruptable=True)` call. No separate Agora REST credentials are required.

For the Custom candidate, the public app additionally mounts `/llm/chat/completions`. A separate runner-issued callback capability identifies the session; the handler removes stale validation context, injects the same bounded current permission before the latest user message, and forwards one real OpenAI-compatible streaming request. It does not persist history, execute tools, or transform SSE tool-call chunks.

`server/src/architecture_validation/config.py` reads the versioned comparison controls once. `server/src/agent.py` builds either `OpenAI` or `CustomLLM` with identical prompt, model controls, history, MCP endpoint, bearer header, allowed tools, STT, TTS, turn detection, and session settings. Only the provider class, callback URL, and callback bearer differ.

The interactive runner owns both Uvicorn listeners, rotates the active scenario on the same per-session capabilities, seeds only synthetic state, and appends recursively redacted JSONL evidence. Invalidated operator/setup attempts remain in evidence under unique IDs and are rerun. The report applies safety disqualifiers before tool accuracy, configuration burden, p95 latency, and failure rate.

## Detailed Documentation

- [docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) — web ↔ FastAPI topology, rewrites, lifecycle
- [docs/ai/L1/03_code_map.md](./docs/ai/L1/03_code_map.md) — where code lives under `web/` and `server/`
- [AGENTS.md](./AGENTS.md) — AI agent development guide
- [README.md](./README.md) — Quick start, configuration, deployment
