# Agora Conversational AI Python Quickstart

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![Bun](https://img.shields.io/badge/bun-latest-black)](https://bun.sh/)

Build a production-style voice agent with a Next.js web client and Python FastAPI backend. This quickstart includes live transcript, agent visualizer ([Agent UIKit](https://agoraio-conversational-ai.github.io/agent-uikit/)), and managed STT/LLM/TTS defaults.

> This derivative uses Agora's Managed Voice LLM path. Its isolated evidence harness under `server/src/architecture_validation/` exercises synthetic MCP and permission behavior only; it does not execute ACP or local coding work. See [`validation/README.md`](validation/README.md).

## Prerequisites

- [Python 3.10+](https://www.python.org/)
- [Bun](https://bun.sh/)
- [Agora CLI](https://github.com/AgoraIO/cli)

## Run It

Install the CLI (skip if already installed), scaffold the Python quickstart, install dependencies, and run.

1. **Install the Agora CLI and sign in** (skip if `agora` is already on your PATH):

   ```bash
   curl -fsSL https://raw.githubusercontent.com/AgoraIO/cli/main/install.sh | sh -s -- --add-to-path
   agora login
   ```

2. **Scaffold and run** (replace `my-python-demo` with your own project name):

   ```bash
   agora init my-python-demo --template python
   cd my-python-demo
   bun run setup
   bun run dev
   ```

3. Open [http://localhost:3000](http://localhost:3000) and click **Start conversation**.

If the agent does not join or transcripts do not appear, run **`agora project doctor --deep`** to check credentials, feature enablement, network reachability, and local env binding.

### Working from a clone of this repository

Use this path if you already cloned **this** repo:

```bash
git clone https://github.com/AgoraIO-Conversational-AI/agent-quickstart-python.git
cd agent-quickstart-python
agora login
agora project use <your-project>
bun run setup
agora project env write server/.env.local
bun run doctor:local
bun run dev
```

Services:

- Frontend: `http://localhost:3000`
- Backend: `http://localhost:8000`
- API docs: `http://localhost:8000/docs`

### Run the local Codex foundation

`bun run dev:codex` starts the loopback-only FastAPI backend on
`127.0.0.1:8000` and the Next.js app on `127.0.0.1:3000`. It performs the
normal dependency checks first, verifies macOS Apple Silicon, Bun/Node/Python,
and usable Agora credentials without printing their values, then supervises
both processes so either child stopping also stops its sibling.

The Local Launcher Supervisor owns terminal signals once. The first Ctrl-C
gracefully stops both services; a deliberate second Ctrl-C or the 10-second
shutdown deadline forces cleanup of the isolated local process group. Closing
the terminal follows the same cleanup path, so backend, frontend, ACP, and
picker descendants do not remain in the background. Interrupted exits use
`130` for SIGINT, `143` for SIGTERM, `129` for SIGHUP, and `137` after forced
cleanup.

```bash
bun run dev:codex
```

The opted-in backend now includes the offline-tested **Task Runtime Core**. It
persists Workspace-scoped Work receipts in `work.sqlite3`, executes ACP prompts
through one FIFO worker, stores bounded activity and final text, correlates one
current-operation permission, confirms cancellation, and fails interrupted
Work safely after restart.

The local app now connects that core to Agora's Managed Voice LLM through an
authenticated, launcher-owned ngrok MCP ingress. **Start conversation** prepares
the dedicated MCP listener, starts ngrok after ACP is ready, issues one
per-Agent bearer, and injects exactly four Work tools. ngrok exposes only the
MCP listener; ACP remains local stdio.

The Managed Voice LLM is told that the selected Project Folder and registered
tools are capabilities it can use. It delegates Workspace-dependent requests
to `start_work` as natural-language objectives without requiring commands or
using a preset task-category list.

Agora may begin MCP discovery before Agent creation returns its real Agent ID.
During that short pending phase, the bearer can authenticate only the
side-effect-free MCP handshake; every Work tool remains unavailable until the
backend binds the exact Agent ID.

Install ngrok and complete `ngrok config add-authtoken ...` once before the
first run. The bearer, full MCP configuration, Workspace path, and internal ACP
identifiers are never returned to the browser or persisted. Ending the Agent or
launcher revokes the bearer before stopping the tunnel.

Completed and failed Work now asks the exact originating active Agora Agent to
speak the stored safe result with APPEND priority. A successful request records
`accepted`; it does not prove playback completed. If that Agent has ended, the
Workspace changed, or submission has an unknown outcome, the durable result
remains available through `get_work_status` and is never replayed into a newer
session automatically. SSE activity, the read-only task panel, proactive
permission announcements, playback receipts, and reconnect replay remain
follow-on slices.

On first launch, the app opens a blocking **Project Folder** Settings gate.
Choose an existing folder with the native macOS picker (or use the advanced
path field). The resolved folder is persisted at
`~/Library/Application Support/Agora Voice ACP/workspace.json`, unless
`VOICE_ACP_STATE_DIR` selects a different state directory. A valid saved folder
lets the local web flow explicitly activate one ACP session after both services
start; ordinary FastAPI startup never launches, downloads, or authenticates
ACP. Changing or clearing the folder closes the active session first. A failed
replacement retains the previous saved folder.

Project Folder is ACP session context for resolving work and relative paths. It
is **not** a filesystem sandbox and does not limit what the child process can
access. The v0.1 Codex profile supports one primary directory and no additional
directories.

The default child command is pinned and on-demand:

```text
npx -y @agentclientprotocol/codex-acp@1.1.7
```

The client first tries to create a session with reusable Codex credentials. If
ACP returns its typed authentication-required response, the client uses the
advertised `ChatGPT` method and retries session creation once.

Advanced launch options do not bypass Project Folder validation or select full
access:

```bash
bun run dev:codex -- --workspace /absolute/path/to/project
CODEX_PATH=/absolute/path/to/codex bun run dev:codex
CODEX_API_KEY=... bun run dev:codex
OPENAI_API_KEY=... bun run dev:codex
bun run dev:codex -- --acp-command-json '["/absolute/path/to/acp-agent","--stdio"]'
```

`CODEX_PATH`, `CODEX_API_KEY`, and `OPENAI_API_KEY` are passed only to the ACP
child. The custom command is parsed only as a JSON argv array and is never run
through a shell. Secret values and child-command environments are never logged.

## Deploy

Deploy `web` as a Next.js app and `server` as a reachable Python service.

Browser-facing `/api/*` routes in Next proxy to FastAPI via:

```bash
AGENT_BACKEND_URL=https://your-python-backend.example.com
```

Set backend env values:

```bash
AGORA_APP_ID=your_agora_app_id
AGORA_APP_CERTIFICATE=your_agora_app_certificate
AGENT_GREETING=optional_custom_greeting
```

To export local env values from the Agora CLI-bound project:

```bash
agora project use <your-project>
agora project env write server/.env.local
rg "^(AGORA_APP_ID|AGORA_APP_CERTIFICATE)=" server/.env.local
```

## Environment variables

Primary backend env file: [`server/.env.example`](server/.env.example).

| Variable | Required | Default | Notes |
| --- | :---: | :---: | --- |
| `AGORA_APP_ID` | ✅ | — | Agora Console -> Project -> App ID |
| `AGORA_APP_CERTIFICATE` | ✅ | — | Agora Console -> Project -> App Certificate (server only) |
| `AGENT_GREETING` |  | built-in greeting | Optional opening line override |
| `HOST` |  | `0.0.0.0` | FastAPI bind host; `dev:codex` fixes this to `127.0.0.1` |
| `PORT` |  | `8000` | FastAPI server port |
| `AGENT_BACKEND_URL` (web deploy) | ✅ | — | Required in deployed `web` app when proxying to external FastAPI |
| `VOICE_ACP_STATE_DIR` |  | macOS Application Support | Local Workspace state parent directory |
| `CODEX_PATH` |  | packaged Codex | Advanced Codex binary override passed to ACP |
| `CODEX_API_KEY`, `OPENAI_API_KEY` |  | — | Advanced child-process pass-through; values are never logged |
| `VOICE_ACP_COMMAND_JSON` |  | pinned ACP command | Advanced JSON argv array; prefer `--acp-command-json` |

Architecture-evidence variables are documented in `server/.env.example`. Per-session MCP capabilities are generated at runtime and are never developer-managed environment variables. `VALIDATION_MODEL` must match the controls in `validation/corpus.json`.

> **Default vs BYOK** — this quickstart defaults to Agora-managed STT + LLM + TTS in the backend. Enable BYOK by uncommenting provider blocks in `server/src/agent.py` and adding matching keys.

## Commands

```bash
# Dev
bun run setup
bun run dev
bun run dev:codex

# Quality
bun run doctor
bun run doctor:local
bun run preflight:codex
bun run verify:backend
bun run verify:launcher

# CI / pre-ship
bun run verify:web
bun run verify:local
bun run verify
```

Run `bun run verify` before shipping web-only changes, and `bun run verify:local` when backend behavior changed.

Offline checks use fake ACP, ngrok, Agent, and FastAPI/proxy paths; they
do not execute the pinned `npx` command, authenticate in a browser, open the
native picker, start an Agora conversation, or open ngrok. Those are live/manual
checks. Tests run standalone: `pytest` in `server/`, `bun test` in `web/`. CI
runs them on Linux/macOS/Windows × Python 3.10 & 3.13.

`bun run verify:launcher` uses harmless child stubs to exercise terminal signal
ownership, forced cleanup, and residual descendants. It does not start Agora or
consume conversation minutes. `LOCAL_LAUNCHER_GRACE_SECONDS` is only a private
verification seam for shortening its deadline, not an end-user setting.

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./.github/images/system-architecture-dark.svg">
  <img src="./.github/images/system-architecture.svg" alt="System architecture">
</picture>

The browser talks to Next.js `/api/*` routes. In local mode, Next rewrites those routes to FastAPI using `AGENT_BACKEND_URL=http://localhost:8000`; FastAPI owns token generation and agent start/stop logic.

The derivative local-runtime extension adds loopback-only Project Folder and
readiness routes under `/api/local/*`. Next registers them only for the
explicit local-development opt-in with a loopback backend, and never in a
production build. It does not change the stable quickstart routes or make ACP,
Codex, or the Project Folder public browser APIs.

## What You Get

- Next.js web client (`web/`) with transcript UI and agent visualizer
- FastAPI backend (`server/`) for token generation and agent lifecycle
- `/api/get_config`, `/api/startAgent`, and `/api/stopAgent` browser-facing contract
- A local Codex readiness gate with persisted Project Folder context and one ACP child-process session
- Managed default pipeline (Deepgram STT, OpenAI LLM, MiniMax TTS)

## How It Works

1. Browser requests connection config from `/api/get_config`.
2. Backend generates combined RTC+RTM config and returns channel + token.
3. Browser joins RTC/RTM and starts streaming audio.
4. Browser calls `/api/startAgent`; backend starts the cloud agent session.
5. Browser receives transcript and state updates over RTM, and `/api/stopAgent` ends the session.

## Repo Map

- `web/` — Next.js 16 + React 19 + TypeScript frontend
- `server/` — Python FastAPI backend + Agora Agent Server SDK integration
- `ARCHITECTURE.md` — system-level flow and ownership boundaries
- `AGENTS.md` — contributor agent instructions

## Troubleshooting

- **Agent does not join or transcripts are missing:** run `agora project doctor --deep`.
- **Missing credentials:** run `agora project env write server/.env.local`.
- **Auth errors from backend:** confirm `AGORA_APP_ID` and `AGORA_APP_CERTIFICATE` are set in `server/.env.local`.
- **Frontend cannot reach backend:** confirm `AGENT_BACKEND_URL=http://localhost:8000` in local frontend scripts.
- **Unsure who owns `/api/*`:** Next owns browser-facing `/api/*`; FastAPI owns `/get_config`, `/startAgent`, `/stopAgent`.
- **Project Folder gate is blocked:** choose an existing directory. If the local runtime asks for authentication, complete the advertised ChatGPT sign-in flow and retry. This quickstart does not validate that live flow offline.

## More Docs

- [ARCHITECTURE.md](./ARCHITECTURE.md)
- [AGENTS.md](./AGENTS.md)
- [docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) — full-stack topology and lifecycle
- [docs/ai/L1/03_code_map.md](./docs/ai/L1/03_code_map.md) — curated `web/` + `server/` file map

## License

Released under the [MIT License](./LICENSE).
