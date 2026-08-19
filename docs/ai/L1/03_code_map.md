# 03 Code Map

> Where to find things. Paths are relative to the repo root.

## Top-Level Tree (curated)

```
package.json              # JS workspace (web/); bun-driven orchestration scripts
bun.lock
README.md                 # Setup + commands
ARCHITECTURE.md           # Top-level environment model
AGENTS.md                 # Contributor entry point
CLAUDE.md                 # Pointer to AGENTS.md
LICENSE

web/                      # Next.js 16 app (workspace member)
  app/
    layout.tsx            # Fonts, metadata, viewport, imports @/index.css
    page.tsx              # Renders <LandingPage />
  src/
    components/
      LandingPage.tsx
      ConversationComponent.tsx
      QuickstartConversationLayout.tsx
      QuickstartTranscriptPanel.tsx
      QuickstartPipelineMetrics.tsx
      QuickstartPreCallCard.tsx
      ProjectFolderSettings.tsx  # blocking local Codex Project Folder gate
      ConnectionStatusPanel.tsx
      ConversationErrorCard.tsx
      MicrophoneSelector.tsx
      ErrorBoundary.tsx
      LoadingSkeleton.tsx
      share-button.tsx
      ui/
        button.tsx
        dropdown-menu.tsx
    lib/
      agora.ts            # DEFAULT_AGENT_UID = 123456
      conversation.ts     # Transcript normalization + visualizer mapping
      utils.ts            # cn() (clsx + tailwind-merge)
    services/
      api.ts              # getConfig / startAgent / stopAgent fetch helpers
    types/
      conversation.ts     # AgoraTokenData, AgoraRenewalTokens, ConversationComponentProps
    index.css             # Tailwind layers + theme variables
  public/                 # favicon.svg, agora logos, site.webmanifest
  scripts/
    doctor.ts             # Requires AGENT_BACKEND_URL
    verify-api-contracts.ts
    verify-local-proxy.ts
    verify-local-fastapi.ts
  src/lib/
    workspace.ts        # Workspace Scope + readiness browser types
    local-runtime.ts    # conversation-start readiness gate
  biome.json
  next.config.ts          # rewrites() (see 02_architecture)
  tsconfig.json
  docs/                   # Workflow + review + project state templates

server/                   # Python FastAPI backend
  requirements.txt        # fastapi, uvicorn, requests, dotenv, agora-agents
  .env.example
  README.md
  src/
    __init__.py
    server.py             # FastAPI app + APIRouter routes
    agent.py              # Agent class: start, stop, vendor chain
    acp_runtime/
      workspace.py        # durable one-folder Workspace Scope
      routes.py           # loopback-only settings/readiness routes
      picker.py           # backend-owned native macOS picker
      codex.py            # ACP child process/session client
      launch.py           # validated --workspace launch override
      readiness.py        # one-session local readiness coordinator
    task_runtime/
      models.py           # Work, activity, permission, and result domain types
      store.py            # SQLite Work receipts and recovery
      permissions.py      # one current-operation Permission Broker
      runtime.py          # serial FIFO ACP execution and workspace guard
    architecture_validation/
      admin.py            # Loopback-only state seeding
      config.py           # Fail-closed Managed-path evidence controls
      context.py          # Shared bounded permission projection
      managed.py          # Agent-session update and APPEND speech adapter
      mcp_app.py          # Authenticated FastMCP tool surface
      public_server.py    # Minimal public ASGI app factory
      recorder.py         # Append-only recursively redacted evidence
      runner.py           # Optional interactive dual-listener evidence run
      runtime.py          # Process-local shared state
      state.py            # Capability, permission, and synthetic Work state
      tools.py            # Four shared validation tools
  scripts/
    run_fake_server.py    # Patches Agent to a FakeAgent for smoke tests

scripts/
  run-local-codex.sh       # argument parsing and sibling process supervision
  local-codex-preflight.ts # platform/runtime/Agora config validation
  verify-local-launcher.ts # harmless launcher integration checks
```

## Core Files Table

| File                                                | Purpose                                                                  |
| --------------------------------------------------- | ------------------------------------------------------------------------ |
| `package.json` (root)                               | `concurrently`-driven dev orchestration; every workflow script.          |
| `web/next.config.ts`                                | Stable rewrites plus opt-in development-only local rewrites.             |
| `web/src/services/api.ts`                           | Browser API client: `getConfig`, `startAgent`, `stopAgent`.              |
| `web/src/components/LandingPage.tsx`                | Session bootstrap, RTM login, renewal handler, provider wiring.          |
| `web/src/components/ConversationComponent.tsx`      | RTC join, `AgoraVoiceAI` init, transcript/state/metrics, mic UI.         |
| `web/src/lib/conversation.ts`                       | `normalizeTranscript` (uid `"0"` remap), visualizer state mapping.       |
| `web/scripts/verify-api-contracts.ts`               | Asserts no `app/api` route handlers + browser-side fetch shapes.         |
| `web/scripts/verify-local-proxy.ts`                 | Smoke test: fake server + Next rewrites round-trip.                      |
| `web/scripts/verify-local-fastapi.ts`               | Spawns `server/scripts/run_fake_server.py`, exercises full path.         |
| `server/src/server.py`                              | FastAPI app, env loading, three routes, response envelope, error mapping.|
| `server/src/agent.py`                               | `Agent` class — vendor chain + async session lifecycle.                  |
| `server/src/acp_runtime/`                           | Local Codex derivative: workspace persistence, ACP, and readiness.      |
| `server/src/task_runtime/`                          | Durable Work, FIFO ACP execution, permissions, cancellation, recovery. |
| `server/src/architecture_validation/`               | Managed Voice LLM evidence state, tools, and isolated public ingress.    |
| `server/scripts/run_fake_server.py`                 | Patches `server.agent` to `FakeAgent` for verification.                  |

## Module Boundaries

- `web/` owns React UI, RTC/RTM lifecycle, and the proxy contract.
- `server/src/` owns FastAPI handlers and all Agora SDK calls; secrets stay here.
- `web/scripts/` owns verification harnesses that gate `bun run verify`.
- Module-specific `AGENTS.md` / `ARCHITECTURE.md` under `web/` and `server/` were removed — use repo-root `ARCHITECTURE.md`, `AGENTS.md`, and this L1 tree.

## What's Not in the Repo

- **No `web/src/hooks/`** and **no `useAgoraConnection.ts`** — RTC/RTM orchestration lives in `LandingPage.tsx` and `ConversationComponent.tsx`.
- **No `pyproject.toml`** — Python deps are pip + `requirements.txt`.
- **`server/tests/architecture_validation/`** — pytest coverage for Managed-path context, tools, and route isolation; ordinary backend routes still use the bun-spawned smoke scripts.
- **`server/tests/acp_runtime/`** and **`server/tests/task_runtime/`** — offline fake-ACP coverage for local readiness, protocol mapping, durable Work, permissions, cancellation, and recovery.
- **No `Makefile`** — `bun run …` is the canonical entry point.
- **No `app/api/**/route.ts`** under `web/` — `verify-api-contracts.ts` enforces this.

## Related Deep Dives

- [From-Scratch Bootstrap](L2/from_scratch_bootstrap.md) — Baseline map for recreating the Python-backed quickstart recipe.
- [Session Lifecycle](L2/session_lifecycle.md) — Concrete walk through `LandingPage` + `ConversationComponent`.
