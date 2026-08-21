# 01 Setup

> Local environment for Agora Voice Coder: a macOS voice experience backed by
> Next.js, FastAPI, an authenticated MCP ingress, and a local Codex ACP process.

## Prerequisites

- **Python** ≥ 3.10 (README + `server/README.md`).
- **bun** as the JS toolchain (root `package.json` scripts and root `bun.lock`).
- **pip** + `venv` for Python dependencies. No `pyproject.toml` is present.
- **ngrok** installed and authenticated once with `ngrok config add-authtoken ...`.
- Agora project with App ID + App Certificate.

## Install

The primary consumer journey starts from this repository:

```bash
git clone https://github.com/AgoraIO-Conversational-AI/recipe-agent-voice-coder.git
cd recipe-agent-voice-coder
agora login
agora project use <your-project>
bun run setup
agora project env write server/.env.local
bun run dev:codex
```

The lower-level dependency setup is:

```bash
bun install                # JS deps for the workspace, including web/
cd server
python3 -m venv venv       # canonical name; matches package.json scripts
source venv/bin/activate
pip install -r requirements.txt
```

Or use the orchestrated flow:

```bash
bun run setup
# runs: setup:env → setup:backend → setup:frontend → setup:done
```

`setup:env` copies `server/.env.example` → `server/.env.local` if missing. `setup:backend` recreates `server/venv`, upgrades pip, and installs `requirements.txt`. `setup:frontend` runs `bun install`. `setup:deps` exists for `bun run dev:check`, not for `bun run setup`.

> The package.json scripts use `server/venv/` (no leading dot). `bun run dev:backend` activates `server/venv` and runs `python src/server.py` from inside `server/`. If you create the venv under a different name you'll need to adjust the scripts or symlink.

## Environment Variables

`server/.env.example`:

```
AGORA_APP_ID=your_agora_app_id
AGORA_APP_CERTIFICATE=your_agora_app_certificate
AGENT_GREETING=Hi there! I'm Ada, your virtual assistant from Agora. How can I help?
HOST=0.0.0.0
PORT=8000
```

`web/.env.local.example`:

```
# Required: Next rewrites /api/* requests to the Python backend.
AGENT_BACKEND_URL=http://localhost:8000
```

| Variable                 | Process              | Required | Notes                                                                 |
| ------------------------ | -------------------- | -------- | --------------------------------------------------------------------- |
| `AGORA_APP_ID`           | Python (server)      | Yes      | Loaded by `Agent.__init__` via `os.environ`.                          |
| `AGORA_APP_CERTIFICATE`  | Python (server)      | Yes      | Server-only.                                                          |
| `AGENT_GREETING`         | Python (server)      | No       | Optional first utterance.                                             |
| `HOST`                   | Python (server)      | No       | Default `0.0.0.0`; `dev:codex` fixes loopback.                        |
| `PORT`                   | Python (server)      | No       | Default `8000` (`server.py`).                                          |
| `AGENT_BACKEND_URL`      | Next build (web)     | Yes for rewrites | Empty/missing → no `/api/*` rewrites registered. Required by `web/scripts/doctor.ts`. |
| `NEXT_PUBLIC_AGENT_UID`  | Browser (web)        | No       | Optional UID override read in `ConversationComponent.tsx`.            |
| `VOICE_ACP_STATE_DIR`    | Python (local Codex) | No       | Overrides the parent directory for persisted `workspace.json`.        |
| `VOICE_ACP_WORKSPACE`    | Python (local Codex) | No       | Internal value set by the validated `--workspace` launcher option.     |
| `CODEX_PATH`             | ACP child            | No       | Advanced Codex binary override passed only to the child.               |
| `CODEX_API_KEY` / `OPENAI_API_KEY` | ACP child | No | Advanced auth pass-through; values are never logged.                   |
| `VOICE_ACP_COMMAND_JSON` | Python (local Codex) | No       | Advanced JSON argv array; never parsed by a shell.                     |
| `VOICE_ACP_MCP_PORT`     | Python (local Codex) | No       | Dedicated loopback MCP listener; default `8001`.                       |

The optional Managed-path evidence harness additionally uses `VALIDATION_MODEL` and `PUBLIC_VALIDATION_BASE_URL`. It calls `update` and `say` through the authenticated Agent session and needs no separate model-provider credentials. The runner creates MCP capabilities in memory; do not add static capability tokens to `.env.local`.

## Python Dependencies

`server/requirements.txt`:

```
fastapi>=0.100.0
uvicorn>=0.20.0
requests>=2.31.0
python-dotenv>=1.0.0
agora-agents>=2.0.0
mcp>=1.2.0,<2
httpx>=0.27,<1
```

The SDK is lower-bounded at v2 — add an upper bound or exact pin if you need reproducible SDK behavior.

## Quick Commands

```bash
bun run dev:codex              # primary macOS Voice Coder flow
bun run dev                    # inherited generic quickstart maintenance flow
bun run dev:backend            # python3 server/src/server.py
bun run dev:frontend           # cd web && AGENT_BACKEND_URL=http://localhost:8000 bun run dev
bun run doctor                 # bun + node_modules sanity
bun run doctor:local           # adds python3 + .env.local + AGORA_* presence
bun run preflight:codex        # platform/Bun/Node/Python/ngrok/Agora config, no secret output
bun run build                  # bun --filter web build
bun run verify:public-repo     # fail if local-only workflow plans are tracked
bun run verify                 # public boundary + doctor + web API/lint/build
bun run verify:local           # public boundary + complete local offline chain
bun run verify:backend         # compile server/src and run all offline Python suites
bun run verify:web:api         # web/scripts/verify-api-contracts.ts
bun run verify:web:proxy       # web/scripts/verify-local-proxy.ts
bun run verify:local:fastapi   # spawns server/scripts/run_fake_server.py
bun run verify:launcher        # harmless child-process supervisor checks
bun run clean                  # remove backend venv, node_modules, .next, web/dist
bun run validate:managed       # optional interactive Managed evidence run; uses live Agora minutes
```

`cd web && bun run doctor` separately enforces `AGENT_BACKEND_URL` validity.

`bun run dev:codex` replaces its argument-parsing shell with the Local Launcher
Supervisor before starting `concurrently`. The first terminal signal becomes
child SIGTERM for quiet graceful shutdown, while the supervisor preserves the
terminal-facing status. A second deliberate Ctrl-C or the 10-second deadline
force-cleans the isolated process group. Terminal closure is handled as SIGHUP
cleanup. Interrupted statuses are `130` (SIGINT), `143` (SIGTERM), `129`
(SIGHUP), and `137` (forced cleanup).
`LOCAL_LAUNCHER_GRACE_SECONDS` is a verification-only seam.

## Verification Safety

| Command                       | Live Agora? | Notes                                                |
| ----------------------------- | ----------- | ---------------------------------------------------- |
| `bun run doctor`              | No          | bun + node_modules sanity                            |
| `bun run doctor:local`        | No          | Adds python3 + env presence                          |
| `bun run verify:web:api`      | No          | Contract harness with mocked SDK                     |
| `bun run verify:web:proxy`    | No          | Static fake-server smoke                             |
| `bun run verify:local:fastapi`| No          | Boots `server/scripts/run_fake_server.py`            |
| `bun run verify:backend`      | No          | Compile sources + validation, ACP, Task Runtime, and Managed ingress pytest |
| `bun run verify:web:build`    | No          | `bun --filter web build`                             |
| `bun run dev`                 | Yes (for use) | Port binding blocked in many sandboxes              |
| `bun run dev:codex`           | No (until Start conversation) | Starts local services; Agent preparation then starts ngrok |
| `cd server && ... pytest -q`  | No          | ACP tests inject fakes; no real `npx` or browser auth |

## Local Voice Coder Setup

Run `bun run dev:codex`, then choose a Project Folder in the automatically
opened Settings gate. The backend opens the native macOS picker; manual path
entry is an advanced UI fallback. The chosen resolved directory is stored in
`~/Library/Application Support/Agora Voice ACP/workspace.json` by default, or
under `VOICE_ACP_STATE_DIR` when that variable is set.

The folder supplies ACP session context and relative-path resolution; it is not
a filesystem sandbox. The default ACP child command is
`npx -y @agentclientprotocol/codex-acp@1.1.7`. The client first tries session
creation with reusable credentials. Typed authentication-required triggers the
advertised ChatGPT method and one retry. Ordinary backend startup never starts
ACP; the local browser flow explicitly activates a valid saved Workspace.

Use `bun run dev:codex -- --workspace /absolute/path` for the startup Workspace
override. `CODEX_PATH`, `CODEX_API_KEY`, and `OPENAI_API_KEY` are advanced child
pass-through values. `--acp-command-json '["agent","--stdio"]'` supplies a
Compatible custom command without shell parsing. None selects full access.
Offline checks cannot verify package download, browser sign-in, native picker,
Agora conversation, real ngrok reachability, or end-to-end Managed LLM tool use.

After ACP is ready, **Start conversation** starts the dedicated MCP listener
and ngrok, issues one in-memory capability for the new Agora Agent, and injects
exactly four Work tools. Ending the Agent or launcher revokes the capability
and closes the tunnel.

## Common Setup Failures

- `bun run doctor:local` fails on **"python3 not found"** → install Python ≥ 3.10.
- Preflight reports a missing ngrok runtime → install ngrok and authenticate it once.
- Doctor fails on missing `server/.env.local` → run `bun run setup:env` or copy from `server/.env.example`.
- `cd web && bun run doctor` rejects empty/invalid `AGENT_BACKEND_URL` → ensure the URL is `http://` or `https://`.
- `verify:web:api` fails on a new route → extend `web/scripts/verify-api-contracts.ts` to cover it.

## Related Deep Dives

- [Verification Scripts](L2/verification_scripts.md) — Each `web/scripts/*.ts` harness explained.
