# 04 Conventions

> How code is structured in this repo and what patterns to preserve when editing.

## Languages & Tooling

| Concern        | Toolchain                                                                              |
| -------------- | -------------------------------------------------------------------------------------- |
| Python format  | None enforced in-repo. Match existing style; `ruff`/`black` are not configured.        |
| Python verify  | Compile `server/src/` and run validation, ACP, and Task Runtime pytest (`bun run verify:backend`). |
| Python deps    | `pip install -r server/requirements.txt` inside `server/venv` (created by `bun run setup:backend`). |
| TypeScript     | `strict: true` in `web/tsconfig.json`; path alias `@/* → ./src/*`.                     |
| Linter         | Biome (`web/biome.json`); `noExplicitAny` off, `useExhaustiveDependencies` off.        |
| Format         | Biome (`bun run lint:fix` writes).                                                     |
| JS orchestration | bun (root `package.json` `concurrently`, `bun --filter web …`).                       |

There is **no ESLint config file** in `web/` — Biome is the only TS/JS linter.

## Python Patterns

- `Agent` is a class with `async def start(...)` and `async def stop(...)`. Routes call `await agent.start(...)` directly.
- The FastAPI `agent` instance is created once at module scope (`agent = Agent()`). `Agent.__init__` reads env via `os.environ`. Recreating `Agent` per request would be wasteful and is intentionally avoided.
- `Agent` is **not stateless**: it holds `self._sessions: Dict[str, Any]` keyed by `agent_id` for the lifetime of the worker. Per-request data still lives in pydantic models and locals; only cross-call session bookkeeping belongs on `self`.
- If `Agent()` fails during module load (missing env after imports succeed), the module exports `agent = None` and route handlers return `500`. `verify:backend` does not call live Agora; use `verify:local:fastapi` or `bun run dev` to exercise route startup behavior.
- Errors are raised, not returned as tuples. `_to_http_error` in `server.py` maps `ValueError` → `400`, `RuntimeError` → `500`, anything else → `500`.
- Logging: `logging.getLogger("uvicorn.error")`. There is no custom logger.
- Type hints are used for pydantic models (`StartAgentRequest`, `StopAgentRequest`) and `Agent` method signatures.

## Pydantic Models

| Model                    | Lives in           | Fields                                        |
| ------------------------ | ------------------ | --------------------------------------------- |
| `StartAgentRequest`      | `server/src/server.py` | `channelName`, `rtcUid`, `userUid`, optional `parameters` |
| `StopAgentRequest`       | `server/src/server.py` | `agentId`                                    |

`StartAgentRequest.parameters` is optional — `server.py` only reads `output_audio_codec` from it.

## JSON Contract Style

- Browser sends camelCase (`channelName`, `rtcUid`, `userUid`, `agentId`).
- Server responses use the envelope `{ "code": 0, "msg": "success", "data": {...} }`.
- `data` payloads use snake_case (`app_id`, `channel_name`, `agent_uid`).

## TypeScript / React Patterns

- Components are PascalCase `.tsx` files under `web/src/components/`. Shared primitives live under `components/ui/` in lowercase files.
- The RTC client is held in a `useRef` inside a dynamically imported `AgoraRTCProvider` to survive React StrictMode double-mount.
- `useJoin`, `useLocalMicrophoneTrack`, `usePublish` from `agora-rtc-react` own normal mount/unmount lifecycles — avoid duplicate cleanup effects that call `.leave()`, `.close()`, or `unpublish`.
- The explicit end-call button is the exception: `ConversationComponent.handleEndConversation` unpublishes and closes the active microphone track before delegating to `LandingPage.onEndConversation`.
- `normalizeTranscript` in `web/src/lib/conversation.ts` remaps `uid === '0'` to the local UID. Keep this remap upstream of any side-of-screen heuristic.

## Hook Ownership Quick Reference

| Hook                       | Owns                          | Anti-pattern                                       |
| -------------------------- | ----------------------------- | -------------------------------------------------- |
| `useJoin`                  | `client.leave()`              | Manual `client.leave()` calls in cleanup            |
| `useLocalMicrophoneTrack`  | Track creation + default `.close()` | Duplicate `track.close()` in StrictMode cleanup     |
| `usePublish`               | Publish state                 | Manually `unpublish` to mute (use `setEnabled`)     |

## Local ACP Conventions

- Keep `WorkspaceService` responsible for resolved, durable one-directory
  selection. The Project Folder is ACP context, never a sandbox claim.
- Keep `/local/*` server routes loopback-only and expose them to the browser
  only through the explicit, non-production local Next rewrite boundary under
  `/api/local/*`, with a loopback backend URL.
- `LocalRuntimeCoordinator` owns serialized session open/close and exposes
  safe readiness only. Do not leak ACP frames, private identifiers, raw
  reasoning, auth data, or environment values.
- `CodexAcpClient` owns one child process/session. It defaults to the pinned
  command and agent mode. It tries reusable authentication before a typed
  auth-required ChatGPT retry. Advanced `CODEX_PATH`, API-key pass-through, and
  JSON-argv custom commands never log child environments or auto-select full access.
- `TaskRuntime` owns one background FIFO worker and is the only production
  caller of ACP prompts. Persist Work before queueing it; never expose raw ACP
  frames, thought content, private identifiers, or exception text.
- `WorkStore` uses one SQLite connection owned by the local app lifespan.
  Workspace changes are rejected while any Work or permission is nonterminal.
- `PermissionBroker` holds at most one current-operation request. Select only
  `allow_once` or `reject_once`; cancellation is the fallback when a matching
  option is unavailable.

## Testing

- Python: `bun run verify:backend` compiles the backend and runs the Managed-path validation, ACP runtime, and Task Runtime pytest suites; ordinary backend route coverage still comes from the smoke scripts.
- TS: no Vitest harness. The verification suite layers Python compile/tests,
  Bun unit tests, API contracts, the rewrite stub, FakeAgent FastAPI smoke,
  launcher integration, local-preflight tests, and the production web build.
  See `docs/ai/L1/L2/verification_scripts.md`.
- Keep architecture-validation Python tests under `server/tests/architecture_validation/` and run them without live Agora or model credentials.
- ACP tests under `server/tests/acp_runtime/` use fake ACP clients/processes.
  They are offline-safe but do not establish real package launch or browser auth.
- Task Runtime tests under `server/tests/task_runtime/` use fake ACP only and
  cover SQLite receipts, FIFO execution, permissions, cancellation, recovery,
  and Workspace switch protection without starting Agora.

## File Naming

- Components: PascalCase `.tsx` (e.g. `ConversationComponent.tsx`).
- UI primitives: lowercase under `ui/` (e.g. `ui/button.tsx`).
- Scripts: kebab-case (`verify-api-contracts.ts`, `verify-local-fastapi.ts`).
- Python modules: snake_case (`server.py`, `agent.py`, `run_fake_server.py`).

## Module Discipline

- `server/src/agent.py` owns managed Agent/provider construction;
  `server/src/server.py` intentionally imports the Agora token helper for the
  stable `/get_config` route. Other backend modules do not import Agora SDKs.
- `web/src/services/api.ts` is the only place that hard-codes `/api/...` paths (apart from `next.config.ts`).
- `web/scripts/verify-api-contracts.ts` intentionally imports the production
  API client and Next config to verify their public contracts. Other scripts
  may import Next config for rewrite smoke checks but do not import React UI.

## Error Handling Shapes

- Python: raise `HTTPException(status_code=..., detail=str(exc))` via `_to_http_error`. FastAPI serializes the string under the JSON `detail` field.
- TS: `api.ts` helpers throw on non-2xx HTTP; callers (`LandingPage`) catch with `try/catch` and surface a user-friendly message via the existing `ConnectionStatusPanel` issue list.

## Git & Docs Conventions

- Commit messages follow conventional commits: `type: description` or `type(scope): description`, lowercase after the prefix, present tense.
- Branch names use `type/short-description`, lowercase and hyphen-separated.
- Do not mention AI tool names in commit messages or PR descriptions; do not add `Co-Authored-By` trailers.
- `AGENTS.md` is the authoritative contributor guide for git conventions and doc commands.

## Related Deep Dives

- [Verification Scripts](L2/verification_scripts.md) — Implementation details of the four verification harnesses.
