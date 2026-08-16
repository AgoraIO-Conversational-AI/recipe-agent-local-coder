# 06 Interfaces

> Boundary contracts: FastAPI routes, Next rewrites, environment variables, and managed agent payload.

## Python Backend Routes

`server/src/server.py` registers these on an `APIRouter`:

| Path           | Method | Request                                                                              | Success (200)                                                                                | Errors                                                          |
| -------------- | ------ | ------------------------------------------------------------------------------------ | -------------------------------------------------------------------------------------------- | --------------------------------------------------------------- |
| `/get_config`  | GET    | Query: optional `channel`, optional `uid`                                            | `{ "code": 0, "msg": "success", "data": { app_id, token, uid, channel_name, agent_uid } }`   | `500` if `agent is None`; exceptions via `_to_http_error`        |
| `/startAgent`  | POST   | JSON `StartAgentRequest`: `channelName`, `rtcUid`, `userUid`, optional `parameters`  | `{ "code": 0, "msg": "success", "data": { agent_id, channel_name, status } }`                | `400` validation (`ValueError`); `500` runtime / generic        |
| `/stopAgent`   | POST   | JSON `StopAgentRequest`: `agentId`                                                   | `{ "code": 0, "msg": "success" }`                                                            | Same shape                                                       |
| `/validation/admin/permissions` | POST | Loopback-only bounded permission seed | Current authorization ID, version, operation, and question | `403` for non-loopback clients |

CORS middleware: `allow_origins=["*"]`, `allow_credentials=True`.

`StartAgentRequest.parameters` is optional — the handler only reads `output_audio_codec` from it today.

`get_config` treats missing, zero, and negative UIDs as "generate a random user UID" and returns the generated value. This keeps the single RTC+RTM token usable for RTM, where `0` is not a valid login subject.

## Next.js Rewrites

`web/next.config.ts` registers these only when `AGENT_BACKEND_URL` is set:

| Source             | Destination                                  |
| ------------------ | -------------------------------------------- |
| `/api/get_config`  | `${AGENT_BACKEND_URL}/get_config`             |
| `/api/startAgent`  | `${AGENT_BACKEND_URL}/startAgent`             |
| `/api/stopAgent`   | `${AGENT_BACKEND_URL}/stopAgent`              |

The local Codex derivative appends these loopback-only extension rewrites. They
do not alter the stable quickstart routes above. They register only when
`VOICE_ACP_LOCAL_RUNTIME=1`, the backend URL is loopback, and Next is not in
production mode:

| Source | Destination | Method(s) |
| --- | --- | --- |
| `/api/local/workspace` | `${AGENT_BACKEND_URL}/local/workspace` | GET, PUT, DELETE |
| `/api/local/workspace/browse` | `${AGENT_BACKEND_URL}/local/workspace/browse` | POST |
| `/api/local/workspace/browse/:operationId` | `${AGENT_BACKEND_URL}/local/workspace/browse/:operationId` | GET |
| `/api/local/runtime` | `${AGENT_BACKEND_URL}/local/runtime` | GET, POST |

`verify-api-contracts.ts` asserts that no `web/app/api/**/route.ts` files exist. Adding one would create a competing handler in front of the rewrite — don't.

## Environment Variables

| Scope                  | Variable                                  |
| ---------------------- | ----------------------------------------- |
| Python server (required) | `AGORA_APP_ID`, `AGORA_APP_CERTIFICATE` |
| Python server (optional) | `AGENT_GREETING`, `HOST`, `PORT`         |
| Next build             | `AGENT_BACKEND_URL`                       |
| Browser                | `NEXT_PUBLIC_AGENT_UID` (optional)        |
| Local launcher/internal | `VOICE_ACP_LOCAL_RUNTIME`, `NEXT_PUBLIC_LOCAL_RUNTIME_ENABLED`, `VOICE_ACP_WORKSPACE` |
| ACP child advanced     | `CODEX_PATH`, `CODEX_API_KEY`, `OPENAI_API_KEY` |
| Compatible ACP command | `VOICE_ACP_COMMAND_JSON` (JSON argv array) |

`AGENT_BACKEND_URL` is a Next **server**-time env var (used inside `next.config.ts`), not a `NEXT_PUBLIC_*` value — do not prefix it.

## Local Workspace and Runtime Contract

Successful `/local/*` responses use
`{ "code": 0, "msg": "success", "data": ... }`. FastAPI error responses use
`{ "detail": "..." }`, consistent with the rest of the backend:

| Status | Local-runtime condition | Error body |
| --- | --- | --- |
| `403` | Caller is not loopback | `{ "detail": "..." }` |
| `400` | `PUT` path is not an absolute existing directory | `{ "detail": "Project Folder must be an absolute existing directory" }` |
| `409` | Picker cancellation or a Workspace switch guard conflict | `{ "detail": "..." }` |
| `503` | Candidate folder could not activate the local ACP runtime | `{ "detail": "..." }` |

FastAPI also returns its normal validation error body for an invalid request
shape. Clients must not expect a success envelope on non-2xx responses.

`WorkspaceStatus` contains `state` (`unconfigured`, `ready`, or `invalid`), a
Codex `profile`, and an optional workspace `{ id, label, primary_directory }`.
The profile requires one primary directory and supports no additional directories.
`PUT` accepts `{ "path": "..." }`; the path must resolve to an existing
absolute directory. `GET /local/runtime` is read-only; `POST /local/runtime`
explicitly activates a valid saved Workspace. `LocalRuntimeStatus` uses
`configuration_required`, `starting`, `authentication_required`, `ready`, or
`failed`, plus `workspace` and an optional safe `error`.

The default ACP command is pinned to `npx -y @agentclientprotocol/codex-acp@1.1.7`
with `INITIAL_AGENT_MODE=agent`. It tries `new_session` with reusable credentials
first. Only typed authentication-required triggers the advertised `ChatGPT`
method and one retry. `CODEX_PATH`, `CODEX_API_KEY`, and `OPENAI_API_KEY` are
advanced child pass-through values; custom ACP is a JSON argv array. Secret
values and child environments are not logged, and full access is never selected
automatically.

## Token Shape

`get_config` returns:

```json
{
  "code": 0,
  "msg": "success",
  "data": {
    "app_id": "string",
    "token": "string",          // built by generate_convo_ai_token, token_expire=3600
    "uid": "string",            // serialized number
    "channel_name": "string",
    "agent_uid": "string"
  }
}
```

The same token grants RTC and RTM privileges.

## Managed Agent Payload

`server/src/agent.py` does not POST a hand-written JSON payload to Agora — it uses the SDK builder chain:

```python
agent = (
    AgoraAgent(...)
    .with_stt(DeepgramSTT(model="nova-3", language="en"))
    .with_llm(OpenAI(model="gpt-4o-mini", ...))
    .with_tts(MiniMaxTTS(model="speech_2_6_turbo",
                          voice_id="English_captivating_female1"))
)

session = agora_agent.create_async_session(
    client=self.client,
    channel=channel_name,
    agent_uid=str(agent_uid),
    remote_uids=[str(user_uid)],
    enable_string_uid=False,
    idle_timeout=30,
    expires_in=3600,
)
agent_id = await session.start()
```

## RTM Event Shapes (Client-Side)

`AgoraVoiceAI` emits the same toolkit events as the other quickstarts:

- `TRANSCRIPT_UPDATED` — `{ uid, text, status, timestamp }[]`
- `AGENT_STATE_CHANGED` — `AgentState`
- `AGENT_METRICS` — `{ type, name, value, timestamp }`
- `MESSAGE_ERROR` — `{ module, code, message, send_ts }`
- `MESSAGE_SAL_STATUS` — `{ status, timestamp }`
- `AGENT_ERROR` — SDK error info

`ConversationComponent.tsx` also attaches a raw RTM `message` listener as a fallback for the same `message.error` / `message.sal_status` payloads.

## Internal Types

| Type                          | Lives in                                       | Notes                                            |
| ----------------------------- | ---------------------------------------------- | ------------------------------------------------ |
| `StartAgentRequest`           | `server/src/server.py`                         | pydantic, camelCase fields                       |
| `StopAgentRequest`            | `server/src/server.py`                         | pydantic, `agentId`                              |
| `AgoraTokenData`              | `web/src/types/conversation.ts`                | Used by `LandingPage` + `ConversationComponent`  |
| `AgoraRenewalTokens`          | `web/src/types/conversation.ts`                | Renewal handler payload                          |
| `ConversationComponentProps`  | `web/src/types/conversation.ts`                | Includes RTM client + data                       |
| `GetConfigResponse`           | `web/src/services/api.ts`                      | Browser shape for `data` field                   |

## Related Deep Dives

The separate validation public app exposes authenticated Streamable HTTP at `/mcp/` with exactly four tools: `start_work`, `get_work_status`, `cancel_work`, and `respond_permission`. Session identity is derived from a runner-issued bearer and is never accepted as a model-provided tool argument. The public app does not expose any route in the table above.

- [Managed Agent Config](L2/managed_agent_config.md) — Detailed field reference.
- [Verification Scripts](L2/verification_scripts.md) — How the contracts above are enforced by local pre-ship checks.
