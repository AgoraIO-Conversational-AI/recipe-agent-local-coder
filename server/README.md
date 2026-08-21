# Agora Voice Coder Python Service

The FastAPI backend for Agora Voice Coder. It owns Agora Agent lifecycle,
Workspace settings, the local Task Runtime, authenticated MCP ingress, and the
ACP coding-agent process boundary.

## Quick Start

Use the repo-root [README.md](../README.md) for the product journey. This
document is for working on the Python backend module directly.

Recommended from the repo root.

Repo setup:

```bash
bun run setup
```

Agora credentials:

```bash
agora project env write server/.env.local
```

Run Agora Voice Coder:

```bash
bun run dev:codex
```

The inherited generic quickstart path remains available for upstream
maintenance, but it does not start the Voice Coder local runtime:

```bash
bun run dev
```

It binds FastAPI to `127.0.0.1:8000`, serves the web app on `127.0.0.1:3000`,
and lets FastAPI own the Project Folder picker, ACP child process, Task Runtime,
and dedicated MCP listener on `127.0.0.1:8001`. It does not start an Agora
conversation until the browser user chooses **Start conversation**. At that
point it starts ngrok, discovers the public MCP URL through the loopback API on
ngrok's default port `4040`, and binds one capability to the Agent. Preflight requires macOS
Apple Silicon, Bun/Node/Python/ngrok, and usable Agora configuration without
printing credential values. Install ngrok and run
`ngrok config add-authtoken ...` once before this flow.

Agora may initialize MCP before Agent creation returns. The pending bearer
allows only protocol discovery; the four Work tools remain closed until the
backend binds the real Agent ID.

This assumes the Agora CLI is installed and logged in. The command uses the project selected in your Agora CLI context, which is usually your default account project.

If you are not using the Agora CLI, create the env file manually and fill in your project values:

```bash
cp server/.env.example server/.env.local
```

From `server/`:

### 1. Configure Environment

Backend-only Agora CLI env write:

```bash
agora project env write .env.local
```

Manual fallback:

```bash
cp .env.example .env.local
```

`.env.example` is the reference template. If you are not using the Agora CLI, edit `.env.local` and fill in your Agora credentials:
- `AGORA_APP_ID` - Your Agora App ID (Required)
- `AGORA_APP_CERTIFICATE` - Your Agora App Certificate (Required)
- `HOST` - Optional bind host (`0.0.0.0` by default; local Codex fixes loopback)
- `PORT` - Optional bind port (`8000` by default)
- Agora managed provider access should be enabled for this project

If you still need to authenticate with the CLI:

```bash
agora login
```

To select a specific existing project before writing env values:

```bash
agora project use <project-id-or-name>
agora project env write .env.local
```

To create a new project instead of using your default project:

```bash
agora project create my-first-voice-agent --feature rtc --feature convoai
agora project use my-first-voice-agent
agora project env write .env.local
```

**Note**: The service uses Token007 authentication generated from `AGORA_APP_ID` and `AGORA_APP_CERTIFICATE`. The voice chain is managed `DeepgramSTT` (`nova-3`) + `OpenAI` (`gpt-4o-mini`) + `MiniMaxTTS` (`speech_2_6_turbo` / `English_captivating_female1`).

### Architecture-validation configuration

Set `VALIDATION_MODEL` to the model declared in `validation/corpus.json` and point `PUBLIC_VALIDATION_BASE_URL` at the ngrok origin exposing local port 8001. Runtime MCP capability tokens are generated in memory and must not be added to the env file.

Run `bun run validate:managed` only when live Agora usage is explicitly authorized. See [`validation/README.md`](../validation/README.md) for route-isolation checks, operator actions, evidence handling, and cost guidance. This harness does not run ACP or local coding work.

### 2. Install Dependencies

**Option A: Using Virtual Environment (Recommended)**
```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
pip install -r requirements.txt
```

**Option B: Global Installation (Not Recommended)**
```bash
pip install -r requirements.txt
```

### 3. Start Service

```bash
# If using virtual environment, make sure it's activated first
python src/server.py
```

The service will start on port 8000 (or the port specified in `.env.local`).

## How This Fits The Repo

- Voice Coder product flow: run `bun run dev:codex` from the repo root. It owns
  the loopback services, Project Folder, ACP session, Task Runtime, and ngrok
  MCP ingress.
- Inherited quickstart maintenance: `bun run dev` starts only the generic
  Python-backed voice Agent path.
- Module-local backend work: use the commands in this README when you only need to run or inspect the Python service itself.
- Remote Voice Coder deployment is not supported.

### 4. Live API Checks

`GET /get_config` is local and does not start an Agent. `POST /startAgent`
starts a real Agora conversation and consumes minutes; run the start/stop checks
only with explicit live-test authorization.

```bash
# Test config generation
curl http://localhost:8000/get_config

# Test agent start
curl -X POST http://localhost:8000/startAgent \
  -H "Content-Type: application/json" \
  -d '{"channelName": "test_channel", "rtcUid": 123456, "userUid": 789012}'

# Test agent stop (use agent_id from start response)
curl -X POST http://localhost:8000/stopAgent \
  -H "Content-Type: application/json" \
  -d '{"agentId": "your_agent_id"}'
```

## API Endpoints

- `GET /get_config` - Generate connection configuration
- `POST /startAgent` - Start an agent
- `POST /stopAgent` - Stop an agent

`/get_config` now issues one-hour RTC plus RTM tokens. The web client renews both before expiry, matching the reference Next.js session model.

The repo-level `bun run verify:local:fastapi` check exercises this FastAPI app through the Next proxy path, but it swaps in a fake agent implementation so route wiring can be verified without depending on a live agent start.

## Local ACP Runtime

The Codex profile requires exactly one Project Folder. `WorkspaceService`
resolves and persists it as a Workspace Scope in
`~/Library/Application Support/Agora Voice ACP/workspace.json` by default;
set `VOICE_ACP_STATE_DIR` only when a different local state directory is needed.
The selected directory is ACP context for session creation and relative paths,
not a filesystem sandbox.

The loopback-only routes below are consumed through Next `/api/local/*`
rewrites only during the explicit non-production local mode with a loopback
backend. They are derivative extensions and do not change the stable
`/get_config`, `/startAgent`, or `/stopAgent` quickstart routes:

- `GET`, `PUT`, `DELETE /local/workspace`
- `POST /local/workspace/browse` (start the macOS native picker; returns `202` and an operation ID)
- `GET /local/workspace/browse/{operation_id}` (poll picker status)
- `GET /local/runtime` (readiness only; never starts ACP)
- `POST /local/runtime` (explicitly activate a valid saved Workspace)

Ordinary FastAPI startup never starts ACP. `LocalRuntimeCoordinator` starts it
only through the explicit local-runtime flow for a ready workspace and keeps
one session at a time. A folder replacement closes the old session before
opening the new one; if the new session fails, the previous saved workspace
record is restored. If the ACP child has already closed its transport during
shutdown, that transport close is treated as complete while process cleanup
still runs. The default `CodexAcpClient` starts the pinned on-demand command
`npx -y @agentclientprotocol/codex-acp@1.1.7`, uses `INITIAL_AGENT_MODE=agent`,
and opens one ACP session with `mcp_servers=[]`. Session creation is attempted
with reusable credentials first. A typed authentication-required response uses
the advertised ChatGPT method and retries once.

Advanced launch paths support `--workspace`, `CODEX_PATH`, `CODEX_API_KEY`,
`OPENAI_API_KEY`, and `--acp-command-json`. The custom command is a JSON argv
array, never a shell string. Overrides do not select full access, bypass normal
Workspace validation, or log secret values/child environments.
Offline tests inject fake ACP clients/processes, so they do not validate a real
`npx` invocation or browser sign-in.

## Requirements

- Python >= 3.10
- Dependencies listed in `requirements.txt`
- Development verification dependencies listed in `requirements-dev.txt`

## SDK

This project uses `agora-agents` (import `agora_agent`):
- Package: `agora_agent`
- Agent builder: `agora_agent.agentkit.Agent` with fluent `.with_llm()` / `.with_tts()` / `.with_stt()` API
- Default vendors: `DeepgramSTT`, `OpenAI`, `MiniMaxTTS` from `agora_agent.agentkit.vendors`
- Optional BYOK examples in `src/agent.py`: `DeepgramSTT`, `OpenAI(api_key=...)`, `ElevenLabsTTS`
- Token: `agora_agent.agentkit.token.generate_convo_ai_token`
