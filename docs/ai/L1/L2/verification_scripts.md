# Verification Scripts

> **When to Read This:** Load this document when you are adding a route, changing the proxy boundary, debugging a failing `bun run verify*` command, or expanding the contract harness.

## The Verification Layers

| Layer                    | Script / Tool                                | Bun target                | What it asserts                                              |
| ------------------------ | -------------------------------------------- | ------------------------- | ------------------------------------------------------------ |
| Python compile + unit    | `compileall` + validation + ACP-runtime pytest | `bun run verify:backend`  | Python source compiles; validation and fake ACP runtime behavior pass |
| Web → Rewrite contract   | `web/scripts/verify-api-contracts.ts`        | `bun run verify:web:api`  | No `app/api` routes; `/api/*` rewrites + fetch shapes correct |
| Web → rewrite stub       | `web/scripts/verify-local-proxy.ts`          | `bun run verify:web:proxy`| Imports `next.config.ts`, resolves rewrites, fetches an in-process stub directly |
| Web → FastAPI + FakeAgent| `web/scripts/verify-local-fastapi.ts`        | `bun run verify:local:fastapi` | Spawns FastAPI with `FakeAgent` patched in              |
| Local launcher           | `scripts/verify-local-launcher.ts`           | `bun run verify:launcher` | Harmless child stubs prove sibling cleanup on failure, SIGINT, and SIGTERM |

`bun run verify` is the production-bound chain (`doctor` → `verify:web:api` → `verify:web:build`). `bun run verify:local` is the dev-bound chain (`doctor:local` → `verify:backend` → `verify:local:fastapi` → `verify:web:proxy` → `verify:web:build`).

## `verify-api-contracts.ts`

Purpose: lock the **shape** of the proxy boundary without standing up any backend.

What it does:

1. Globs `web/app/api/**/route.ts` and fails if any exist.
2. Imports `web/next.config.ts` and asserts `rewrites()` returns the expected `source` → `destination` triples.
3. Imports `web/src/services/api.ts` and asserts each helper hits the correct URL with the correct body shape (via a mock `fetch`).

When you add a route:

- Add the new rewrite entry.
- Add the new fetch helper.
- Extend this script with the new expectation.
- Run `bun run verify:web:api`.

## `verify-local-proxy.ts`

Purpose: smoke test the **rewrite mapping** without spawning Next dev or the real FastAPI service.

What it does:

1. Starts an in-process stub backend via `Bun.serve` that responds to `/get_config`, `/startAgent`, `/stopAgent` with canned JSON.
2. Imports `next.config.ts` directly and calls its `rewrites()` async function to get the rewrite triples.
3. For each browser-side path (e.g. `/api/get_config`), resolves the matching `rewrite.destination`, copies the query string, and `fetch`es the stub backend URL directly — no Next process is involved.
4. Asserts canned payloads round-trip cleanly.

This catches rewrite typos and body-shape regressions instantly. It does **not** catch Next-runtime issues (middleware, headers, edge runtime).

If you change rewrite paths or body shapes, this is the first script that breaks.

## `verify-local-fastapi.ts`

Purpose: exercise the **real FastAPI app** locally, with a `FakeAgent` substituted in (no managed cloud calls).

What it does:

1. Spawns `python3 server/scripts/run_fake_server.py`, which:
   - Imports `server.src.server` so the `app` and `agent` module-level singleton exist.
   - Replaces `server_module.agent` with a `FakeAgent` instance.
   - Runs `uvicorn.run(app, ...)` on a known port.
2. Sets `AGENT_BACKEND_URL` to that port and runs the same browser-side fetch helpers through Next.
3. Asserts canned responses round-trip cleanly.

This is the closest CI gets to a full integration test. It never makes outbound calls.

## Python Compile, Validation, and ACP Runtime Tests

`bun run verify:backend` compiles `server/src/` and runs the credential-free
tests under `server/tests/architecture_validation/` and
`server/tests/acp_runtime/`. The ACP runtime suite covers:

- Workspace Scope persistence, existing-directory validation, and state changes.
- Loopback-only workspace/readiness routes, picker cancellation, selection
  rollback, and switch-guard conflicts.
- The macOS picker through a mocked subprocess boundary; it never opens a real
  picker during the suite.
- Serialized local readiness with fake ACP clients: one active session,
  replacement close-before-open, authentication failure, generic failure, and
  concurrent lifecycle handling.
- `CodexAcpClient` through a repository-owned fake ACP process that records
  protocol method names only. It validates initialization, advertised ChatGPT
  authentication, `new_session`, and process cleanup without starting Codex.

It catches:

- Syntax errors.
- Regression in the validation or local ACP foundation contracts listed above.

It does **not** run the real pinned `npx` ACP package, complete browser
authentication, start an Agora conversation, open ngrok, or operate a real
native picker. Pair it with `verify:local:fastapi` whenever you change route
behavior.

## `verify-local-launcher.ts`

Purpose: prove local launcher cleanup without starting the backend, frontend,
ACP, or any network endpoint.

What it does:

1. Checks that `dev:codex` delegates to `scripts/run-local-codex.sh` and that
   the launcher has the expected cleanup trap and sibling-kill behavior.
2. Starts the launcher only with injected harmless shell stubs through
   `LOCAL_BACKEND_COMMAND` and `LOCAL_FRONTEND_COMMAND`.
3. Proves a failing child returns failure and terminates its sibling.
4. Proves SIGINT and SIGTERM terminate both stub child processes.

The injection variables are test seams, not normal end-user command overrides.
This check does not launch the real `dev:codex` services, Codex, browser auth,
Agora, ngrok, or the native picker.

## Adding a New Route — Checklist

1. **Python:** `@router.<verb>("/path")` in `server.py`. Add a pydantic request model if the body is non-trivial. Add a method on `Agent` if you need service logic.
2. **Web rewrite:** new entry in `web/next.config.ts`.
3. **Web fetch helper:** new function in `web/src/services/api.ts`.
4. **Contract harness:** new assertion in `web/scripts/verify-api-contracts.ts`.
5. **Smoke harness (if needed):** new case in `verify-local-proxy.ts` and/or `verify-local-fastapi.ts` if the route belongs in the smoke flow.
6. **Run:** `bun run verify:backend && bun run verify:web:api && bun run verify:local:fastapi`.

## What These Scripts Do NOT Cover

- They do not call the real Agora Conversational AI API. Vendor model changes will not be caught by `bun run verify`.
- They do not exercise RTC or RTM at the wire level. Browser regression testing requires `bun run dev` plus a real Agora project.
- They do not run lint/format. Run `bun run lint` separately.
- They do not prove the real Codex ACP package can download through `npx`, a
  ChatGPT browser sign-in can complete, the native picker works on the host, or
  ngrok ingress is reachable. These are separately authorized live/manual checks.

## Failure Modes

| Symptom                                                           | Cause                                                                |
| ----------------------------------------------------------------- | -------------------------------------------------------------------- |
| `verify-api-contracts` fails on "app/api should not exist"        | Someone added a Next route handler — remove it.                       |
| `verify-local-proxy` hangs on `fetch`                             | Fake server failed to start; check the script's stderr.              |
| `verify-local-fastapi` errors on import                           | `Agent.__init__` failed (env missing or SDK import error).            |
| `verify-backend` reports a syntax error                           | Run `python3 -m py_compile` directly on the offending file.          |

## See Also

- [Back to Setup](../01_setup.md)
- [Back to Workflows](../05_workflows.md)
- [Back to Interfaces](../06_interfaces.md)
