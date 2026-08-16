---
recipe_role: acp-local
base_recipe: agent-quickstart-python
base_recipe_version: 1.0.0
recipe_version: 0.1.0
recipe_status: experimental
extension_points:
  - id: api.routes
    name: Browser-facing API routes
  - id: agent.managed-config
    name: Managed agent prompt, VAD, model, and voice defaults
  - id: web.conversation-ui
    name: Conversation UI panels and controls
  - id: verification.contracts
    name: Contract and local smoke verification
invariants:
  - id: api.rewrite-boundary
    summary: Browser calls stay on /api/* and Next rewrites to FastAPI.
  - id: secrets.server-only
    summary: Agora App Certificate and BYOK keys stay in the Python backend.
  - id: token.uid-concrete
    summary: Backend resolves missing, zero, or negative UIDs before issuing RTC+RTM tokens.
stable_contracts:
  - id: env.required
    summary: AGORA_APP_ID and AGORA_APP_CERTIFICATE are required by FastAPI; AGENT_BACKEND_URL is required by deployed web rewrites.
  - id: api.core-routes
    summary: GET /api/get_config, POST /api/startAgent, and POST /api/stopAgent remain the browser-facing contract.
  - id: response.envelope
    summary: Successful backend responses use { code, msg, data }.
derivative_extensions:
  - id: local.codex-runtime
    summary: Loopback-only Project Folder and ACP readiness foundation for the local Codex derivative.
---

# Recipe Contract

This document restates the reusable `base` quickstart surface this recipe
inherits from `agent-quickstart-python`, and adds the `acp-local` derivative
extension. The base contract below tracks the upstream `base` recipe (currently
`1.0.0`); the derivative surface is versioned independently under this recipe's
own `recipe_version`.

## Recipe Role

- Role: `acp-local` derivative recipe, inheriting the `base` quickstart contract.
- Target audience: developers extending the Python-backed Agora quickstart with a loopback-only local Codex ACP runtime.
- Reuse model: clone, bind project, run, then customize backend agent behavior or browser UI; the local ACP runtime is an opt-in derivative surface.

## Recipe Scope

This base recipe provides a copyable split-process starter with:

- Python FastAPI token generation and managed agent lifecycle.
- Next.js browser UI with RTC audio, RTM events, transcript, metrics, and connection status.
- Rewrite-only `/api/*` browser facade that hides backend placement.
- Managed default STT, LLM, and TTS provider configuration.
- Contract and local smoke verification that do not require live Agora calls.

## Baseline Implementation Guidance

This repository derives from the Python-backed Agora quickstart baseline (`agent-quickstart-python`). Agents should use this repo's source and progressive disclosure docs as the starting point, then customize.

Do not recreate Agora ConvoAI integration from memory. Provider schemas, SDK builder fields, token behavior, and RTM event details can drift. For a new baseline implementation, follow [L1/L2/from_scratch_bootstrap.md](L1/L2/from_scratch_bootstrap.md) while copying verified patterns from this repo.

## Extension Points

| ID | Surface | How to extend | Required follow-up |
| -- | ------- | ------------- | ------------------ |
| `api.routes` | `server/src/server.py`, `web/next.config.ts`, `web/src/services/api.ts` | Add FastAPI route, add rewrite, add browser fetch helper. | Extend `web/scripts/verify-api-contracts.ts`; add smoke coverage if the route belongs in local verification. |
| `agent.managed-config` | `server/src/agent.py` | Change `ADA_PROMPT`, `AGENT_GREETING`, `turn_detection`, `OpenAI`, `DeepgramSTT`, `MiniMaxTTS`, `parameters`, or session options. | Run backend compile and local FastAPI smoke checks; document new env vars in `server/.env.example`. |
| `web.conversation-ui` | `web/src/components/*`, `web/src/lib/conversation.ts` | Customize pre-call, transcript, metrics, connection status, microphone, or visualizer UI. | Preserve RTC/RTM lifecycle ownership and transcript UID normalization. |
| `verification.contracts` | `web/scripts/*.ts`, root `package.json` | Add contract checks for new browser/backend boundaries. | Keep checks runnable without live Agora credentials where possible. |

## Invariants

- Browser code calls only `/api/get_config`, `/api/startAgent`, and `/api/stopAgent` for the default recipe flow.
- Next.js owns the browser-facing `/api/*` paths only through rewrites; do not add `web/app/api/**/route.ts` for agent or token logic.
- FastAPI owns token generation, `AGORA_APP_CERTIFICATE`, BYOK provider keys, and agent lifecycle.
- The backend returns one RTC+RTM-capable token from `get_config`; it must be issued for a concrete non-zero UID.
- `LandingPage.tsx` coordinates config fetch, agent start, RTM login, token renewal, and call teardown.
- `ConversationComponent.tsx` owns RTC join, microphone publish, `AgoraVoiceAI` initialization, transcript/state/metrics listeners, and explicit end-call media release.
- Managed-provider defaults stay server-side unless a change intentionally adds a BYOK path.

## Stable Contracts

| Contract | Stable shape |
| -------- | ------------ |
| Required backend env | `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE` |
| Optional backend env | `AGENT_GREETING`, `HOST`, `PORT` |
| Required web deploy env | `AGENT_BACKEND_URL` |
| Optional browser env | `NEXT_PUBLIC_AGENT_UID` |
| `GET /api/get_config` | Query `channel?`, `uid?`; returns `data.app_id`, `data.token`, `data.uid`, `data.channel_name`, `data.agent_uid`. |
| `POST /api/startAgent` | Body `{ channelName, rtcUid, userUid, parameters? }`; returns `data.agent_id`, `data.channel_name`, `data.status`. |
| `POST /api/stopAgent` | Body `{ agentId }`; returns `{ code: 0, msg: "success" }`. |
| Success envelope | `{ "code": 0, "msg": "success", "data": ... }` where route has data. |
| Verification entry points | `bun run verify:web`, `bun run verify:backend`, `bun run verify:web:proxy`, `bun run verify:local:fastapi`, `bun run verify:local`. |

## Derivative Local Codex Extension

The repository's local Codex foundation is intentionally separate from the
base quickstart contract. It adds Next rewrite-only `/api/local/*` routes for
loopback FastAPI `/local/*` endpoints:

| Browser route | Backend route | Purpose |
| --- | --- | --- |
| `GET`, `PUT`, `DELETE /api/local/workspace` | `/local/workspace` | Read, save, or clear one Project Folder Workspace Scope. |
| `POST /api/local/workspace/browse` | `/local/workspace/browse` | Start the backend-owned native macOS picker and return an operation ID. |
| `GET /api/local/workspace/browse/:operationId` | `/local/workspace/browse/{operation_id}` | Poll the picker operation to a terminal state. |
| `GET /api/local/runtime` | `/local/runtime` | Read safe ACP readiness state without starting ACP. |
| `POST /api/local/runtime` | `/local/runtime` | Explicitly activate ACP for a valid saved Workspace. |

`bun run dev:codex` starts the loopback backend and frontend. The browser gate
requires one existing Project Folder before conversation start. That resolved
folder is persisted locally and passed to ACP as session context; it is not a
filesystem sandbox. The Codex profile supports one primary directory with no
additional directories.

Ordinary FastAPI startup does not start ACP. The local flow explicitly activates
`CodexAcpClient`, which starts one child process/session at a time. Its default
is `npx -y @agentclientprotocol/codex-acp@1.1.7` with
`INITIAL_AGENT_MODE=agent`. It tries reusable credentials before using an
advertised ChatGPT method on typed authentication-required and retrying once.
Advanced `CODEX_PATH`/API-key child pass-through and JSON-argv custom commands
do not select full access or log their environment.

Next registers `/api/local/*` only for an explicit non-production local-runtime
opt-in and a loopback backend URL. Normal and public web deployments retain only
the three stable quickstart rewrites.

The extension's fake ACP, local proxy, fake FastAPI, and build checks are
offline-safe. They do not validate real `npx` execution, browser authentication,
native picker behavior, Agora conversation start, or ngrok; those are
live/manual checks.

## Internal / Subject to Change

- Exact visual layout, component composition, Tailwind classes, and asset choices under `web/src/components/`.
- Exact managed-provider model names, VAD timing, voice IDs, and prompt text, as long as they remain documented extension points.
- In-memory `Agent._sessions` implementation details; the stable behavior is start by channel/user and stop by returned `agent_id`.
- Verification implementation internals under `web/scripts/`; the stable surface is the root script names and what they assert.
- `agora-agents` SDK minor-version behavior; this recipe lower-bounds v2 but does not freeze every SDK field.

## Related Progressive Disclosure Docs

- `L1/01_setup.md` — setup, env, and command reference.
- `L1/02_architecture.md` — request flow and component topology.
- `L1/05_workflows.md` — common modification workflows.
- `L1/06_interfaces.md` — route, rewrite, env, and event contracts.
- `L1/L2/from_scratch_bootstrap.md` — implementation map for recreating the Python-backed quickstart recipe.
- `L1/L2/managed_agent_config.md` — full agent config detail.
- `L1/L2/session_lifecycle.md` — RTC/RTM/session orchestration.
