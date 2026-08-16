# Local Runtime Foundation final fix report

Date: 2026-08-15

Review fixed point: `e8fbf2ff563bdd46dde4389f0d2327c32ea267c3`

Outcome: `DONE_WITH_CONCERNS`

The code, documentation, and offline test findings that were safely fixable in
one wave are fixed. Stable quickstart routes are preserved. The plan-mandated
switch guard, ACP event value, and permission value seams remain minimal and
intact. No history was rewritten.

## Findings-to-fixes mapping

### Standards axis

1. **Local Next rewrite exposure — fixed.** `web/next.config.ts` now adds the
   three `/api/local/*` rewrites only when `VOICE_ACP_LOCAL_RUNTIME=1`, the
   backend URL has a loopback hostname, and `NODE_ENV` is not `production`.
   `AGENT_BACKEND_URL` alone still publishes only the three stable quickstart
   routes. `dev:frontend:codex` binds Next to `127.0.0.1` and sets the explicit
   server/client local flags. FastAPI socket-peer loopback enforcement is
   unchanged. `web/next.config.test.ts` and the proxy verifier cover absent
   opt-in, remote backend, production, and valid local development cases.

2. **Readiness exception disclosure — fixed.** Non-authentication failures now
   return one fixed, bounded setup message. Tests inject a private path and a
   secret-shaped value and prove neither reaches the readiness response.
   Authentication-required remains its own fixed user action.

3. **Local API contract gaps — fixed.** Contract verification now covers
   `DELETE /workspace`, `POST /runtime`, required-body `422`, invalid relative
   folder `400` with its fixed validation message, picker cancellation `409`,
   and successful cleanup. The fake FastAPI smoke verifier exercises the real
   local router without launching any external runtime.

4. **False module-discipline documentation — fixed in documentation.** The
   maintained docs now describe the intentional boundaries: the composition
   root imports the production agent builder, and the API contract verifier may
   import production API configuration while substituting transport behavior.
   No architecture-harming relocation was introduced.

5. **Missing `HOST` contract — fixed.** `HOST` is documented in
   `server/.env.example`, the root/server READMEs, architecture references, and
   the maintained AI setup/security/interface docs. Its default remains
   `0.0.0.0`; the local launcher fixes the backend to loopback.

6. **Commit-message history — intentionally not rewritten; controller
   adjudication required.** Commits after the fixed point have no PR suffix,
   and several messages contain the prohibited tool name, including `fad3b48`,
   `c47e80c`, `f409420`, and `c85992b`. The complete affected range is
   `37c80a4..c85992b`. Rewriting this published/local history was explicitly out
   of scope. The fix-wave commit also cannot truthfully add a PR suffix because
   no PR number was provided; the controller must adjudicate or supply one.

7. **Plan-required guard/event/permission seams — preserved.** The serialized
   switch guard, safe ACP event summary value, and bounded/default-deny
   permission value remain present and minimal. No speculative features were
   added to those seams.

8. **Workspace service/resolver boundaries — fixed.** Rollback now calls
   `WorkspaceService.restore()` instead of reaching through to its store.
   Workspace selection and ACP session opening share
   `resolve_project_folder()`, which consistently requires a resolved absolute,
   existing directory. Both service and route coverage exercise rollback and
   validation.

### Spec axis

1. **Saved-auth-first ACP flow — fixed.** `CodexAcpClient.open()` attempts
   `new_session` first. It authenticates only after ACP's typed auth-required
   error code and only with an advertised ChatGPT method, then retries session
   creation once. The fake transport proves saved-auth success skips auth,
   auth-required uses the exact request order, unadvertised auth is not guessed,
   auth failure is typed, and a non-auth error on the retry is not mislabeled as
   authentication-required.

2. **Ordinary backend startup isolation — fixed.** FastAPI lifespan no longer
   calls runtime start, even with a saved Workspace. It still closes any runtime
   activated later. `POST /local/runtime` is the explicit activation boundary,
   and the local-only landing flow calls it for valid saved state. Normal/public
   UI startup does not load local settings or readiness. A lifespan test proves
   zero start calls and one shutdown close call.

3. **Advanced overrides — fixed.** The launcher accepts only
   `--workspace <absolute-path>` and `--acp-command-json <JSON-array>`; unknown
   or incomplete options fail with usage. Workspace override uses the normal
   validated/persisted service path. Custom commands are parsed as a bounded,
   non-empty JSON argv array and never by a shell. `CODEX_PATH`,
   `CODEX_API_KEY`, and `OPENAI_API_KEY` pass only to the child environment.
   The default remains
   `npx -y @agentclientprotocol/codex-acp@1.1.7`, and
   `INITIAL_AGENT_MODE=agent` is forced even if the parent requests full access.
   Tests use only the Python fake ACP process and inert child scripts; no command
   or secret environment is logged.

4. **One-command preflight — fixed.** `bun run preflight:codex` validates macOS,
   Apple Silicon, `bun`/`node`/`python3`, and 32-hex-character Agora App ID and
   App Certificate values before readiness. The validator is independently
   tested with injected platform/runtime/config inputs, and its output contains
   only fixed labels, never credential values. `dev:codex:check` invokes it.

## TDD evidence

- Readiness leakage, shared absolute-directory semantics, service restore,
  saved-auth-first ACP behavior, typed auth retry, startup isolation, environment
  and command overrides, launcher parsing, preflight validation, rewrite gating,
  local route contracts, and explicit runtime activation were introduced from
  failing tests and then made green.
- Final audit edge-case red command:
  `cd server && venv/bin/python -m pytest tests/acp_runtime/test_acp_client.py::test_client_does_not_relabel_post_auth_session_failure -q`
  — failed as expected because the post-auth internal error was incorrectly
  converted to `AcpAuthenticationRequired`.
- Green command after the scoped fix:
  `cd server && venv/bin/python -m pytest tests/acp_runtime/test_acp_client.py::test_client_does_not_relabel_post_auth_session_failure -q`
  — `1 passed`.

## Final verification commands and results

All passing commands below ran against the final code tree and remained fully
offline with respect to ACP, authentication, native UI, tunnels, and Agora.

| Command | Result |
| --- | --- |
| `cd server && venv/bin/python -m pytest tests/acp_runtime -q` | `45 passed`, 3 dependency warnings |
| `cd server && venv/bin/python -m pytest -q` | `111 passed`, 4 dependency/deprecation warnings |
| `bun test --cwd web` | `20 passed`, 0 failed |
| `bun test scripts/local-codex-preflight.test.ts` | `4 passed`, 0 failed |
| `bun run verify:web:api` | API contract checks passed |
| `bun run verify:launcher` | Local launcher cleanup/opaque-argument checks passed |
| `bun run preflight:codex` | macOS Apple Silicon, three runtimes, and usable Agora config passed; only fixed labels printed |
| `bun run verify:local` | complete offline release command passed: doctor, `95` backend/architecture/ACP tests, fake FastAPI smoke, local proxy, TypeScript, and Next production build |
| `cd web && ../node_modules/.bin/biome check next.config.ts next.config.test.ts scripts/verify-api-contracts.ts scripts/verify-local-fastapi.ts scripts/verify-local-proxy.ts src/components/LandingPage.tsx src/services/api.ts src/services/api.test.ts ../scripts/local-codex-preflight.ts ../scripts/local-codex-preflight.test.ts ../scripts/verify-local-launcher.ts` | 11 changed modern-style files checked; no fixes required |
| `git diff --check` | passed |

During the wave, the first `bun run verify:web:build` attempt exposed illegal
direct mutation of the readonly TypeScript `NODE_ENV` type in verification code.
The test helpers were changed to use a local mutable environment view; the
command was rerun repeatedly and the final production build passed compilation,
TypeScript, static generation, and optimization.

`cd web && bun run lint` is not green as a repository-wide baseline: Biome
checked 174 files, reported 852 errors and 1 warning, and stated that 38,239
additional diagnostics were not shown. The output is dominated by generated
`.next/` content, and it also includes pre-existing formatting in files such as
`tsconfig.json` and `tailwind.config.js`. No generated or unrelated files were
rewritten. The focused changed-file check above passes; three touched legacy
component/type files retain their existing repository formatting to keep their
functional diffs minimal.

## Explicitly not run

- Real `npx` or the packaged ACP server
- Real Codex process or session
- ChatGPT browser authentication
- Native macOS directory picker
- ngrok or any public tunnel
- Agora agent start, RTC/RTM connection, or conversation
- Any remote mutation or git-history rewrite

## Remaining concerns

1. The historical commit naming/PR-suffix finding needs controller
   adjudication; this wave did not and must not rewrite history.
2. Repository-wide Biome lint has the generated/pre-existing baseline described
   above even though the focused changed-file check is green.
3. The server suite has four upstream dependency/deprecation warnings.
4. Real ACP startup/authentication, native picker UX, and Agora conversation
   remain intentionally unverified and require a later authorized live/manual
   validation pass.
