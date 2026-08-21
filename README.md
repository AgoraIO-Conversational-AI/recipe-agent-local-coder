# Agora Voice Coder

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](./LICENSE)
[![Python](https://img.shields.io/badge/python-%3E%3D3.10-blue)](https://www.python.org/)
[![Bun](https://img.shields.io/badge/bun-latest-black)](https://bun.sh/)

Control a local coding agent through an Agora voice conversation.

Speak naturally while Agora handles the realtime voice experience. When a
request depends on your selected Project Folder, the voice agent delegates the
work to a local coding agent over the [Agent Client Protocol
(ACP)](https://agentclientprotocol.com/), keeps you in control of permissions
and cancellation, and speaks the result when it is done.

## What It Does

- Runs the coding agent locally against one selected Project Folder.
- Uses Agora Managed STT, LLM, and TTS for the voice conversation.
- Delegates durable background Work through authenticated MCP tools.
- Relays coding-agent permission decisions through the voice conversation.
- Supports status checks, cancellation, and spoken completion results.

## Current Support

- macOS on Apple Silicon
- Codex through a pinned ACP adapter
- Claude Code is the next planned Agent Profile; it is not included yet.

## Prerequisites

- [Python 3.10+](https://www.python.org/)
- [Bun](https://bun.sh/)
- [Agora CLI](https://github.com/AgoraIO/cli)
- [ngrok](https://ngrok.com/)
- Codex authentication supported by the pinned ACP adapter (ChatGPT or API key)

## Run It

```bash
git clone https://github.com/AgoraIO-Conversational-AI/recipe-agent-voice-coder.git
cd recipe-agent-voice-coder

agora login
agora project use <your-project>
bun run setup
agora project env write server/.env.local

# One-time ngrok account setup, if it is not already configured:
ngrok config add-authtoken <your-token>

bun run dev:codex
```

Open [http://127.0.0.1:3000](http://127.0.0.1:3000). On first launch, select an
existing **Project Folder**, then start a conversation and ask for an outcome in
natural language. Starting a conversation uses Agora minutes; setup and offline
verification do not.

The first Codex request reuses existing credentials when possible. If Codex ACP
reports that authentication is required, complete its advertised ChatGPT login
flow and retry.

Services started by `bun run dev:codex`:

- Web app: `http://127.0.0.1:3000`
- Local API: `http://127.0.0.1:8000`
- Private MCP listener: `http://127.0.0.1:8001`

## How It Works

```text
Voice -> Agora Managed STT / LLM / TTS
      -> authenticated MCP over ngrok
      -> local Task Runtime
      -> selected Project Folder
      -> ACP over local stdio
      -> local Codex
```

1. The browser joins an Agora RTC/RTM channel and starts a managed voice Agent.
2. The managed LLM receives four authenticated Work tools: start, status,
   cancel, and permission response.
3. Workspace-dependent requests become natural-language Work objectives. The
   public tool returns immediately while the local FIFO Task Runtime executes
   the objective through ACP.
4. Codex activity and permission requests are converted into bounded,
   voice-safe state. Permission decisions remain explicit.
5. Completed or failed Work is submitted once to the originating active voice
   Agent. Durable status remains authoritative if speech is unavailable or its
   delivery outcome is uncertain.

## Safety and Privacy

- Only the authenticated MCP listener crosses the ngrok tunnel. The local API,
  Project Folder routes, ACP session, and coding-agent process remain loopback
  or local-only.
- Every voice Agent receives a short-lived bearer bound to its exact Agent and
  Workspace generation. Ending the Agent revokes that capability.
- The Project Folder is working context, **not a filesystem sandbox**. The
  local coding agent retains the access allowed by its own process and account.
- The Project Folder path is shown only in the loopback settings UI. ACP
  identifiers, credentials, and full MCP configuration are not returned to the
  browser or included in public MCP results.
- Local Work state is stored in SQLite. Public status output is bounded and
  durable text is redacted before storage.
- Agent-native authentication and provider billing remain between you and the
  selected coding agent.

## Environment Variables

Primary backend environment file: [`server/.env.example`](server/.env.example).

| Variable | Required | Default | Notes |
| --- | :---: | --- | --- |
| `AGORA_APP_ID` | Yes | — | Agora project App ID |
| `AGORA_APP_CERTIFICATE` | Yes | — | Server-only Agora App Certificate |
| `AGENT_GREETING` | No | Built in | Opening voice message |
| `VOICE_ACP_STATE_DIR` | No | macOS Application Support | Workspace and Work state parent directory |
| `HOST` | No | `0.0.0.0` | `dev:codex` always binds the local API to `127.0.0.1` |
| `PORT` | No | `8000` | Local API port |
| `CODEX_PATH` | No | Packaged Codex | Advanced Codex binary override passed only to the ACP child |
| `CODEX_API_KEY` | No | — | Advanced child-process credential pass-through |
| `OPENAI_API_KEY` | No | — | Advanced child-process credential pass-through |
| `VOICE_ACP_COMMAND_JSON` | No | Pinned adapter | Advanced JSON argv array; never evaluated by a shell |

Agora manages the default voice STT, LLM, and TTS providers, so the voice
pipeline does not require separate provider keys. Per-Agent MCP credentials are
generated at runtime and are not developer-managed environment variables.

## Commands

```bash
# Setup and local run
bun run setup
bun run doctor:local
bun run preflight:codex
bun run dev:codex

# Offline verification
bun run verify
bun run verify:backend
bun run verify:local
bun run verify:launcher
```

Offline checks use fake ACP, ngrok, voice Agent, and FastAPI paths. They do not
start a conversation, open the native picker, authenticate a real coding agent,
or consume Agora minutes.

### Advanced ACP launch options

```bash
bun run dev:codex -- --workspace /absolute/path/to/project
CODEX_PATH=/absolute/path/to/codex bun run dev:codex
CODEX_API_KEY=... bun run dev:codex
OPENAI_API_KEY=... bun run dev:codex
bun run dev:codex -- --acp-command-json '["/absolute/path/to/acp-agent","--stdio"]'
```

The custom command must be a JSON argv array and is never run through a shell.
These options do not bypass Project Folder validation or change the default
Agent mode. Secret values and child environments are never logged.

### Managed voice validation harness

`bun run validate:managed` is an isolated architecture-evidence harness. It
uses synthetic MCP and permission behavior and does not execute local coding
Work. It starts a real Agora Agent and therefore requires separate permission
when conversation minutes are limited. See [`validation/README.md`](validation/README.md).

## Architecture

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="./.github/images/system-architecture-dark.svg">
  <img src="./.github/images/system-architecture.svg" alt="Agora Voice Coder system architecture">
</picture>

The web client owns RTC/RTM and the visible conversation. FastAPI owns Agora
tokens, Agent lifecycle, Workspace settings, the Task Runtime, and the private
MCP listener. The launcher owns the frontend, backend, ngrok, native picker,
and ACP child-process lifecycle so one shutdown cleans up the complete local
process group.

The selected Project Folder is persisted at
`~/Library/Application Support/Agora Voice ACP/workspace.json` unless
`VOICE_ACP_STATE_DIR` overrides the state directory. This compatibility path
does not change when the repository is renamed.

The default ACP command is pinned and launched on demand:

```text
npx -y @agentclientprotocol/codex-acp@1.1.7
```

See [ARCHITECTURE.md](./ARCHITECTURE.md) for component boundaries and
[docs/ai/L1/02_architecture.md](./docs/ai/L1/02_architecture.md) for the detailed
lifecycle.

## Repo Map

- `web/` — Next.js conversation UI and RTC/RTM lifecycle
- `server/src/agent.py` — Agora voice Agent lifecycle and managed provider setup
- `server/src/managed_ingress/` — authenticated MCP ingress and Work tools
- `server/src/task_runtime/` — durable Work, permissions, cancellation, and delivery
- `server/src/acp_runtime/` — Project Folder state and local Codex ACP client
- `scripts/` — setup, verification, and supervised local launcher
- `validation/` — optional architecture-evidence corpus and local results

## Troubleshooting

| Problem | Fix |
| --- | --- |
| Setup or credentials are incomplete | Run `bun run doctor:local` and `bun run preflight:codex`. |
| Agent greets but does not start Work | Confirm ngrok is authenticated, then restart and check that the selected Project Folder reports ready. |
| Project Folder settings remain open | Select an existing directory; the folder is validated by the local backend. |
| Codex requests authentication | Complete the advertised ChatGPT flow, or configure a supported child-process API key. |
| Port 3000 is already in use | Stop the exact process using that port, then run `bun run dev:codex` again. |
| A previous terminal closed unexpectedly | Restart the launcher; interrupted nonterminal Work is marked failed rather than silently resumed. |
| You need the latest result again | Ask for Work status; spoken delivery is intentionally not replayed into a newer Agent session. |

## Upstream

This recipe is derived from
[`agent-quickstart-python`](https://github.com/AgoraIO-Conversational-AI/agent-quickstart-python).
See [UPSTREAM.md](./UPSTREAM.md) for the pinned base and sync policy.

## License

Released under the [MIT License](./LICENSE).
