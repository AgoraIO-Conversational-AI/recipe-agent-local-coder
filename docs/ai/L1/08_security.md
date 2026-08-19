# 08 Security

> Trust boundaries, secret handling, and security-relevant invariants for the two-process Python quickstart.

## Trust Model

- The browser is untrusted. It may only see Agora tokens issued by the FastAPI server.
- The FastAPI server is the only process that holds `AGORA_APP_CERTIFICATE` and any future BYOK keys.
- The Next.js process sees `AGENT_BACKEND_URL` (a server-side build env var) but does not see any Agora secret.
- The FastAPI server has no per-user authentication today; the threat model assumes the backend URL is gated upstream.

## Environment Variable Boundaries

| Boundary       | Variables                                                              |
| -------------- | ---------------------------------------------------------------------- |
| Browser        | `NEXT_PUBLIC_AGENT_UID` (optional)                                     |
| Next build/run | `AGENT_BACKEND_URL`                                                    |
| FastAPI        | `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE`, `AGENT_GREETING`, `HOST`, `PORT` |
| Local launcher | `VOICE_ACP_LOCAL_RUNTIME`, `VOICE_ACP_WORKSPACE`, `VOICE_ACP_COMMAND_JSON` |
| ACP child      | trimmed inherited env plus `INITIAL_AGENT_MODE=agent` and explicit `CODEX_PATH` / API-key pass-through |

Mark `AGORA_APP_CERTIFICATE` as a sensitive secret in whichever host runs the Python service. The certificate value never appears in `web/`.

## Token Issuance

- `server.py` `get_config` calls `generate_convo_ai_token(GenerateConvoAITokenOptions(..., token_expire=3600))`.
- The same token grants RTC and RTM privileges; missing, zero, and negative UIDs are replaced with a generated UID before minting so RTM can log in with the token subject.
- Sessions also carry `expires_in=3600` in `create_async_session`, so an idle session aligns with token expiry.

## Token Renewal

- The client listens for `token-privilege-will-expire` on the RTC engine.
- It calls `getConfig()` twice (RTC UID + stored UID) and renews each client.
- If renewal fails, the next failure surfaces through `MESSAGE_ERROR` on RTM or RTC disconnect events.

## CORS

`server/src/server.py` uses:

- `allow_origins=["*"]`
- `allow_credentials=True`
- `allow_methods=["*"]`
- `allow_headers=["*"]`

This is suitable for a local-only quickstart. For a public deploy:

1. Restrict `allow_origins` to your deployed client origin(s).
2. Consider whether `allow_credentials: True` is needed; if not, drop it.
3. Front the FastAPI service with a reverse proxy that enforces its own CORS policy if you need defense in depth.

## Authentication

- No bearer-token or API-key middleware on FastAPI routes.
- No auth in the Next.js rewrites; the browser hits the rewrite directly.
- Anyone with the deployed web URL can start an agent session.

If you need real auth, add a FastAPI dependency that validates a header on each route. Update `web/src/services/api.ts` and `verify-api-contracts.ts` to send and assert the header.

## Input Validation

- pydantic `StartAgentRequest` / `StopAgentRequest` validate body shape automatically.
- Cross-field validation lives in `Agent.start` / `Agent.stop` — they raise `ValueError` on bad input, which `_to_http_error` maps to `400`.
- `RuntimeError` is mapped to `500`.

## Secret Handling Rules

- `server/.env.local` is the developer's secret store; do not commit it.
- `server/.env.example` documents shape only — never put real values there.
- `load_dotenv` reads `server/.env.local` then `server/.env` using a path derived from `server/src/server.py`; missing credentials fail startup initialization and leave routes returning `500`.
- Do not log full env. `logger.error("failed: %s", err)` is fine; `logger.error(os.environ)` is not.

## CSP / Security Headers

- No CSP or HSTS headers are set on FastAPI responses today.
- No security headers are configured in `web/next.config.ts`.
- Add them at the reverse-proxy layer if you put one in front of FastAPI.

## Known Limitations

- No rate limiting on `/get_config`, `/startAgent`, `/stopAgent`. A determined client can rapidly issue tokens — bound this upstream if exposed publicly.
- `server/scripts/run_fake_server.py` accepts the same routes with no validation. Do not deploy it.
- The web client does not encrypt or sign the browser → Next → FastAPI path beyond TLS at the host level.

## Local Codex Boundary

- `/local/workspace`, `/local/workspace/browse`, `/local/runtime`, and
  `/validation/admin/*` are registered on the FastAPI app only when
  `server.create_app(enable_local_routes=True)` — i.e. when
  `VOICE_ACP_LOCAL_RUNTIME=1`. Ordinary and public deployments build the default
  app, which mounts only the three stable quickstart routes, so these routes
  return 404 there rather than depending solely on `require_loopback`. This is
  the backend counterpart to the Next `/api/local/*` rewrite opt-in.
- When they are mounted, `/local/*` and `/validation/admin/*` call
  `require_loopback`; they are not public deployment endpoints.
- `require_loopback` checks the socket peer, the `Origin` header, and the `Host`
  header. The socket-peer check blocks other machines, but a local browser is a
  loopback peer, so a malicious web page could otherwise drive these routes as a
  confused deputy. A cross-site caller is rejected by its forbidden `Origin`
  (which page JavaScript cannot forge); the `Host` check closes the
  DNS-rebinding gap for requests that carry no `Origin`. Non-browser callers
  (curl, native, and the Next server-side rewrite) send no `Origin` and pass.
  This does not defend against a malicious local process, which reaches the
  loopback port without a browser.
- Next registers `/api/local/*` only with an explicit local-development opt-in,
  a loopback backend URL, and a non-production process. `AGENT_BACKEND_URL`
  alone never exposes these routes.
- The native macOS picker runs in the backend process, so the browser receives
  only the selected status payload and never direct filesystem-picker access.
- Project Folder gives ACP a resolved working-directory context. It is not a
  filesystem sandbox or access-control boundary; do not rely on it for isolation.
- `CodexAcpClient` does not log ACP JSON-RPC frames, environment values,
  authentication data, raw reasoning, or private protocol identifiers. Callback
  storage retains only safe update-kind summaries and bounded permission prompts.
- Readiness failures return fixed safe messages rather than exception text,
  paths, protocol/auth details, or command/environment values.
- The Task Runtime Permission Broker keeps at most one current-operation
  request, stores only bounded safe fields, and correlates a response to its
  Workspace and Work. Allow and reject responses select only advertised
  `allow_once` and `reject_once` options; otherwise the request is cancelled.
  There is no timeout. Work cancellation or runner shutdown resolves the
  pending request without granting access.
- Work receipts, safe activity, bounded results, and permission decisions are
  persisted in a mode-`0600` SQLite file under a mode-`0700` state directory.
  Raw ACP frames, thought content, authentication data, child environments,
  and private protocol identifiers are not stored.
- No lifecycle HTTP Work/permission route is exposed. The dedicated public MCP
  app exposes only four tools, authenticates before reading request bodies,
  enforces Host/Origin/method/content-type policy and a 64 KiB pre-read cap,
  and derives Agent/Workspace authority from a memory-only bearer.
- Capabilities are generation-bound, use separate start/status budgets plus a
  shared cancellation/permission mutation budget, and are revoked before
  Agent or tunnel shutdown. Tool projections omit filesystem paths, internal
  identifiers, raw ACP frames, and unbounded results.
- Reusable credentials are tried before authentication. Only a typed
  authentication-required response may invoke the advertised ChatGPT method and
  one retry. `CODEX_PATH`, `CODEX_API_KEY`, and `OPENAI_API_KEY` are explicit
  advanced child pass-through values; custom ACP uses a JSON argv array. The
  runtime never logs these values or changes the forced agent mode to full access.

## Managed-path evidence boundary

- ngrok maps only the dedicated public ASGI listener, never the lifecycle FastAPI port.
- ngrok remains in the launcher process group so supervisor cleanup also owns
  the public tunnel; tests substitute a fake CLI and never expose a port.
- MCP requests require a per-session, 256-bit runner-issued capability held only in memory.
- Model-provided tool arguments cannot select a session.
- Loopback seed controls verify the socket peer, reject cross-site `Origin`/`Host`
  callers, and do not trust forwarding headers.
- Validation evidence is gitignored because it can contain transcripts; recursive credential redaction is added with the evidence recorder.
- The harness has no runtime provider selector or public LLM callback route.

## Related Deep Dives

- [Managed Agent Config](L2/managed_agent_config.md) — Where to plug BYOK vendor keys.
