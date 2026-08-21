# Agent Development Guide

This guide is for coding agents making changes in `recipe-agent-voice-coder`.
This repository is the **acp-local** derivative recipe in the Agora
Conversational AI recipes family, derived from the `base` quickstart
`agent-quickstart-python` (see [UPSTREAM.md](UPSTREAM.md)).

## How to Load

This repository uses progressive disclosure documentation. Docs live under `docs/ai/` in three levels.

1. Read [docs/ai/L0_repo_card.md](docs/ai/L0_repo_card.md) to identify the repo.
2. This repo declares `Recipe Role: acp-local`; read [docs/ai/RECIPE.md](docs/ai/RECIPE.md) before changing reusable quickstart contracts inherited from the `base` recipe.
3. Load ALL 8 files in [docs/ai/L1/](docs/ai/L1/). They are small — load all upfront.
4. Follow L2 deep-dive links only when L1 isn't detailed enough. The index is at [docs/ai/L1/L2/_index.md](docs/ai/L1/L2/_index.md).

The sections below (Start Here, Patterns, Anti-Patterns, etc.) remain the canonical contributor handbook for hands-on work; the `docs/ai/` tree is the structured summary used by AI agents.

## Start Here

- Read [README.md](./README.md) for setup, supported run modes, and verification.
- Use [ARCHITECTURE.md](./ARCHITECTURE.md) for system-level request flow.
- For layout and responsibilities inside `web/` vs `server/`, use [docs/ai/L1/03_code_map.md](docs/ai/L1/03_code_map.md) and [docs/ai/L1/02_architecture.md](docs/ai/L1/02_architecture.md).

## Current System Shape

- Frontend: Next.js 16, React 19, TypeScript, Tailwind CSS, `agora-rtc-react`, `agora-rtm`, `agora-agent-client-toolkit`, and `agora-agent-uikit`
- Backend: Python FastAPI in `server`
- Web API facade: Next rewrites in `web/next.config.ts`
- Auth: Token007 generated from `AGORA_APP_ID` and `AGORA_APP_CERTIFICATE`
- Current derivative config: managed Deepgram STT, OpenAI LLM, and MiniMax TTS

## Supported Modes

### Local Python-Backed Development

- Run from the repo root with `bun run dev`.
- Root scripts start FastAPI on `http://localhost:8000` and Next.js on `http://localhost:3000`.
- The web app calls `/api/*`; Next rewrites those requests to the Python service through `AGENT_BACKEND_URL=http://localhost:8000`.

### Local Codex Foundation

- Run `bun run dev:codex` for the loopback-only local runtime. It starts FastAPI
  on `127.0.0.1:8000` and Next on `127.0.0.1:3000`, with sibling cleanup.
- Its Local Launcher Supervisor receives terminal signals once, keeps
  `concurrently` responsible for sibling lifecycle and labeled output, and
  force-cleans the isolated process group after a deliberate second Ctrl-C or
  10 seconds. SIGHUP also cleans descendants when the terminal closes.
- Its preflight requires macOS Apple Silicon, Bun/Node/Python/ngrok, and usable Agora
  credentials without printing their values.
- The browser automatically opens the Project Folder Settings gate until an
  existing directory is selected and the local runtime reports `ready`.
- The selected resolved directory is persisted in
  `~/Library/Application Support/Agora Voice ACP/workspace.json`, unless
  `VOICE_ACP_STATE_DIR` overrides the state directory. It is ACP context, not a
  filesystem sandbox.
- The backend owns the native macOS picker and all `/local/*` routes; those
  routes are loopback-only. Next exposes `/api/local/*` only for the explicit
  non-production local-runtime opt-in with a loopback backend URL.
- `LocalRuntimeCoordinator` owns at most one ACP session. It starts ACP only
  through explicit local activation after a ready Workspace Scope and closes an
  old session before a replacement. Ordinary FastAPI startup never starts ACP.
- The opted-in local app owns one SQLite-backed Task Runtime Core. It persists
  Work before FIFO execution, maps safe ACP activity, correlates one
  current-operation permission, confirms cancellation, and fails interrupted
  Work on restart.
- The local app owns a separate bearer-authenticated MCP listener. ngrok maps
  only that listener and starts lazily for a Work-capable Agent after ACP is
  ready. Exactly four tools call the real Task Runtime; Agent stop revokes its
  capability before stopping the session. A pending capability may complete
  only the side-effect-free MCP handshake; tools require exact Agent binding.
  The Managed Work prompt presents the selected Project Folder and registered
  tools as capabilities, and `start_work` accepts a complete natural-language
  objective without a command or preset task-category list.
  Completed and failed targeted Work is submitted once to the exact still-active
  Agent session with APPEND priority. API acceptance is not playback proof;
  missing sessions remain pending and ambiguous submission is never retried.
  Never mount this app into FastAPI.
- `CodexAcpClient` owns its child process and defaults to
  `npx -y @agentclientprotocol/codex-acp@1.1.7` with `INITIAL_AGENT_MODE=agent`.
  It tries reusable authentication first, then uses an advertised ChatGPT method
  only after typed authentication-required and retries once. Advanced
  `CODEX_PATH`, API-key pass-through, and JSON-argv custom commands never change
  the default mode or log child environments.
- `bun run dev:codex` does not start an Agora conversation until the user starts
  one. Agent preparation starts ngrok; tests use fakes and never do. Do not
  infer live Codex, ngrok, or Agora acceptance from offline checks.

### Managed Voice LLM Evidence Harness

- Use `bun run validate:managed` only when live Agora usage is explicitly authorized; it consumes conversation minutes.
- Expose only local port 8001 through ngrok. Port 8000, lifecycle routes, admin routes, and reports stay loopback-only.
- Keep the corpus controls and shared MCP tools stable. Raw evidence stays local.
- This harness does not implement ACP, Codex execution, or the production Task Runtime.

### Inherited Deployment Path (not Voice Coder)

The Voice Coder product path is local-only. The following split deployment is
retained solely for maintaining the upstream quickstart surface:

- Deploy `web` as a Next.js app.
- Deploy or provide a reachable Python FastAPI backend.
- Set `AGENT_BACKEND_URL` in the web deployment target.

## Routing / Ownership

- UI and RTC/RTM client lifecycle live in `web`.
- Browser-facing `/api/*` paths are declared in `web/next.config.ts` rewrites.
- Python agent lifecycle logic lives in `server/src`.
- For deployability changes, update README and architecture docs when the owner of `/api/*` changes.

## Key Files

- `README.md`: setup, local vs deploy modes, troubleshooting, and verification.
- `ARCHITECTURE.md`: top-level environment model.
- `web/next.config.ts`: `/api/*` rewrite mappings to the Python backend.
- `web/src/components/LandingPage.tsx`: conversation entry point, RTM login, token renewal.
- `web/src/components/ConversationComponent.tsx`: core real-time UI, RTC join, `AgoraVoiceAI`, mic UI.
- `web/src/services/api.ts`: browser API client.
- `server/src/server.py`: FastAPI entrypoints.
- `server/src/agent.py`: async Agora agent lifecycle wrapper.
- `server/src/acp_runtime/`: durable Workspace Scope, loopback settings routes,
  ACP child-process client, and local readiness coordinator.
- `server/src/task_runtime/`: Work domain, SQLite store, Permission Broker, and
  serial background ACP coordinator.
- `server/src/managed_ingress/`: production capabilities, safe Work tools,
  isolated MCP app, ngrok owner, and Agent-bound lifecycle coordinator.

## Patterns

- Keep the web client calling `/api/*`; hide backend placement behind Next rewrites.
- Keep token generation behavior in the Python backend.
- Keep RTC client creation StrictMode-safe.
- Keep transcript speaker mapping based on actual UIDs, not heuristics.
- Keep the Managed Voice LLM provider as the single v0.1 path unless a new architecture decision explicitly reopens provider ownership.

## Working Rules

- Prefer the smallest change that keeps local mode and deployed mode aligned.
- Keep Python-specific agent lifecycle changes in `server`.
- Keep browser state and RTC/RTM lifecycle changes in `web`.
- Treat `server/.env.local` as CLI-managed by default.
- If you change request or response contracts, update the web client, backend, contract checks, and README together.
- Preserve the three stable quickstart routes. Treat `/api/local/*` as
  loopback-only derivative extensions, not a replacement public API.
- Do not describe Project Folder as a sandbox. Keep the reviewed `CODEX_PATH`,
  API-key pass-through, and JSON-argv custom-command paths explicit, child-only,
  secret-safe, and pinned to `INITIAL_AGENT_MODE=agent` by default.

## Commands

From the repo root:

```bash
bun install
bun run doctor
bun run doctor:local
bun run preflight:codex
bun run dev
bun run dev:codex
bun run verify
bun run verify:local
```

Useful narrower checks:

```bash
bun run verify:web
bun run verify:local:fastapi
bun run verify:web:proxy
bun run verify:backend
bun run verify:launcher
```

Inside `web/`, use:

```bash
bun run doctor
bun run verify
```

## Verification Safety

- Safe without live Agora credentials:
  - `bun run doctor`
  - `bun run verify:web:api`
  - `bun run verify:web:proxy`
  - `bun run verify:backend`
- Requires local env setup but not a live Agora session:
  - `bun run doctor:local`
  - `bun run verify:local`
- Exercises the FastAPI route layer through Next with a fake agent implementation:
  - `bun run verify:local:fastapi`
- Uses fake ACP clients/processes and does not run real `npx`/Codex or browser
  authentication:
  - `cd server && source venv/bin/activate && PYTHONPATH=src pytest -q`
  - `bun run verify:backend`
  - `bun run verify:web:proxy`
- Often blocked inside restricted sandboxes because of port binding or Turbopack process spawning:
  - `bun run dev`
  - `bun run verify:web:build`
  - `bun run verify:local`

## Anti-Patterns / What NOT To Do

- Do not reintroduce Next Route Handlers or `web/proxy.ts` for agent/token logic.
- Do not assume Zustand or a separate client-side store exists.
- Do not require third-party vendor API keys unless the code introduces a non-managed path.
- Do not move token generation into the web app.
- Do not change `/api/*` ownership without updating README, architecture docs, root `AGENTS.md`, and the relevant `docs/ai/L1/` files.

## Done Criteria

Before finishing a change:

1. Run the narrowest relevant verification command.
2. If the change affects the deployable web app, ensure `bun run verify:web` passes.
3. If the change affects local Python-backed development, ensure `bun run verify:local` or the narrower `bun run verify:local:fastapi`, `bun run verify:web:proxy`, or `bun run verify:backend` command passes as appropriate.
4. If you change required env vars or setup steps, update both the root README and the module README.
5. Update README or architecture docs when developer workflow, request flow, or deployment guidance changes.
6. If the change touches workflows, interfaces, gotchas, or security details, update the matching file under [docs/ai/L1/](docs/ai/L1/) and bump `Last Reviewed` in [docs/ai/L0_repo_card.md](docs/ai/L0_repo_card.md).
7. Keep offline verification claims separate from live/manual checks for real
   Codex package launch, browser authentication, native picker behavior, Agora
   conversation start, and ngrok.

## Git Conventions

### Commit messages — conventional commits

- **Format:** `type: description` or `type(scope): description`
- **Types:** `feat:` (new feature), `fix:` (bug fix), `chore:` (maintenance, version bumps), `test:` (test additions/changes), `docs:` (documentation)
- **Scoped variant:** `feat(scope):`, `fix(scope):` — e.g. `feat(server): enable_metrics`
- **Lowercase after prefix** — `feat: add feature`, not `feat: Add feature`
- **Present tense** — "add feature", not "added feature"
- **PR number appended** — `feat: add feature (#123)`

### Branch names

- **Format:** `type/short-description` — lowercase, hyphen-separated
- **Types match commit types:** `feat/`, `fix/`, `chore/`, `test/`, `docs/`
- **Examples:** `feat/fastapi-metrics`, `fix/rtm-presence-race`, `docs/progressive-disclosure`

### General rules

- **No AI tool names** — never mention claude, cursor, copilot, cody, aider, gemini, codex, chatgpt, or gpt-3/4 in commit messages or PR descriptions.
- **No Co-Authored-By trailers** — omit AI attribution lines.
- **No `--no-verify`** — let git hooks run normally.
- **No git config changes** — do not modify `user.name` or `user.email`.

## Doc Commands

| Command         | When to use                                                  |
| --------------- | ------------------------------------------------------------ |
| generate docs   | No `docs/ai/` directory exists yet                           |
| update docs     | Code changed since the `Last Reviewed` date in L0            |
| test docs       | Verify docs give agents the right context (writes `docs/ai/test-results.md`) |
| fix docs        | Close findings from a docs review or test run                |

The generator and tester live in the [AgoraIO-Community/ai-devkit](https://github.com/AgoraIO-Community/ai-devkit) skill set. See the [progressive disclosure standard](https://github.com/AgoraIO-Community/ai-devkit/blob/main/docs/progressive-disclosure-standard.md) for the full specification.
