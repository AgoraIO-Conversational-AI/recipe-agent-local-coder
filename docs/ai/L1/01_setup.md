# 01 Setup

> Local environment for the two-process Python + Next.js quickstart: prerequisites, env vars, and verification commands wired through the root `package.json` and `web/scripts/`.

## Prerequisites

- **Python** ≥ 3.10 (README + `server/README.md`).
- **bun** as the JS toolchain (root `package.json` scripts and root `bun.lock`).
- **pip** + `venv` for Python dependencies. No `pyproject.toml` is present.
- Agora project with App ID + App Certificate.

## Install

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
```

The SDK is lower-bounded at v2 — add an upper bound or exact pin if you need reproducible SDK behavior.

## Quick Commands

```bash
bun run dev                    # setup:env → setup:deps → concurrently {backend, frontend}
bun run dev:codex              # loopback FastAPI + Next with local Codex readiness gate
bun run dev:backend            # python3 server/src/server.py
bun run dev:frontend           # cd web && AGENT_BACKEND_URL=http://localhost:8000 bun run dev
bun run doctor                 # bun + node_modules sanity
bun run doctor:local           # adds python3 + .env.local + AGORA_* presence
bun run preflight:codex        # certified platform/runtime/Agora config, no secret output
bun run build                  # bun --filter web build
bun run verify                 # doctor + verify:web:api + verify:web:build
bun run verify:local           # doctor:local + verify:backend + verify:local:fastapi + verify:web:proxy + verify:web:build
bun run verify:backend         # compile server/src and run architecture-validation pytest
bun run verify:web:api         # web/scripts/verify-api-contracts.ts
bun run verify:web:proxy       # web/scripts/verify-local-proxy.ts
bun run verify:local:fastapi   # spawns server/scripts/run_fake_server.py
bun run verify:launcher        # harmless child-process supervisor checks
bun run clean                  # remove backend venv, node_modules, .next, web/dist
bun run validate:managed       # optional interactive Managed evidence run; uses live Agora minutes
```

`cd web && bun run doctor` separately enforces `AGENT_BACKEND_URL` validity.

## Verification Safety

| Command                       | Live Agora? | Notes                                                |
| ----------------------------- | ----------- | ---------------------------------------------------- |
| `bun run doctor`              | No          | bun + node_modules sanity                            |
| `bun run doctor:local`        | No          | Adds python3 + env presence                          |
| `bun run verify:web:api`      | No          | Contract harness with mocked SDK                     |
| `bun run verify:web:proxy`    | No          | Static fake-server smoke                             |
| `bun run verify:local:fastapi`| No          | Boots `server/scripts/run_fake_server.py`            |
| `bun run verify:backend`      | No          | Compile server sources + architecture-validation pytest |
| `bun run verify:web:build`    | No          | `bun --filter web build`                             |
| `bun run dev`                 | Yes (for use) | Port binding blocked in many sandboxes              |
| `bun run dev:codex`           | No (until Start conversation) | Starts local services; no Agora call or ngrok by itself |
| `cd server && ... pytest -q`  | No          | ACP tests inject fakes; no real `npx` or browser auth |

## Local Codex Setup

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
Agora conversation, or ngrok.

## Common Setup Failures

- `bun run doctor:local` fails on **"python3 not found"** → install Python ≥ 3.10.
- Doctor fails on missing `server/.env.local` → run `bun run setup:env` or copy from `server/.env.example`.
- `cd web && bun run doctor` rejects empty/invalid `AGENT_BACKEND_URL` → ensure the URL is `http://` or `https://`.
- `verify:web:api` fails on a new route → extend `web/scripts/verify-api-contracts.ts` to cover it.

## Related Deep Dives

- [Verification Scripts](L2/verification_scripts.md) — Each `web/scripts/*.ts` harness explained.
