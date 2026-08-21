# recipe-agent-voice-coder (python) — Repo Card

> Next.js web client + Python FastAPI backend for an Agora Conversational AI voice agent, with a local Codex ACP runtime and authenticated Managed Voice LLM MCP ingress.

## Identity

| Field         | Value                                                                |
| ------------- | -------------------------------------------------------------------- |
| Repo          | `AgoraIO-Conversational-AI/recipe-agent-voice-coder`                 |
| Type          | `distributed-system` (single repo, two co-located processes)         |
| Language      | Python 3.10+ (FastAPI + uvicorn) backend + Next.js 16 / React 19 web  |
| Deploy Target | macOS local runtime; no supported remote Voice Coder deployment       |
| Owner         | Agora Conversational AI DevEx                                        |
| Last Reviewed | 2026-08-20                                                           |
| Recipe Role   | `acp-local`                                                          |
| Base Recipe   | `agent-quickstart-python` @ `1.0.0`                                  |
| Recipe Version | `0.1.0`                                                             |
| Recipe Status | `experimental`                                                       |

## L1 — Summaries

The Audience column helps agents prioritise: **Use** = consuming the quickstart's behavior, **Maintain** = modifying internals.

| File                                     | Purpose                                                                | Audience       |
| ---------------------------------------- | ---------------------------------------------------------------------- | -------------- |
| [01_setup](L1/01_setup.md)               | bun + venv + pip setup, env vars, doctor, all scripts                  | Use & Maintain |
| [02_architecture](L1/02_architecture.md) | Two-process topology, `/api/*` rewrite proxy, request lifecycle        | Maintain       |
| [03_code_map](L1/03_code_map.md)         | `web/` and `server/` trees with key file responsibilities              | Maintain       |
| [04_conventions](L1/04_conventions.md)   | Python async + FastAPI patterns, Biome, JSON contract, hook ownership  | Maintain       |
| [05_workflows](L1/05_workflows.md)       | Add a route, change managed agent config, verify, deploy each half     | Use            |
| [06_interfaces](L1/06_interfaces.md)     | FastAPI route contracts, rewrites, env vars, managed agent payload     | Use & Maintain |
| [07_gotchas](L1/07_gotchas.md)           | `AGENT_BACKEND_URL` dependency, doc drift, missing hook reference      | Maintain       |
| [08_security](L1/08_security.md)         | Cert handling, CORS wide-open default, token expiry, server-only env   | Maintain       |

## Derivative Local Runtime

This repository also carries a local-only Codex foundation for a downstream
voice-to-work derivative. Its asynchronous Project Folder picker, supervised
local process lifecycle, ACP lifecycle, SQLite-backed Task Runtime Core, and
`/api/local/*` routes are extension contracts, not part of the reusable
three-route quickstart baseline. Missing configuration opens a guided Settings
gate, cancellation is silent, ready setup returns directly to **Start
Conversation**, and bounded activation failures remain actionable. The
derivative owns an isolated four-tool MCP
listener and a launcher-owned, current-ngrok-compatible tunnel. Pending
capabilities permit MCP discovery only; Work calls require exact Agent binding.
The Managed Work prompt treats the selected Project Folder and registered tools
as available capabilities, while `start_work` accepts a natural-language goal
without enumerating anticipated task categories. Completed and failed Work is
submitted once to its exact active Agent session; durable delivery state keeps
status lookup authoritative when speech is unavailable or uncertain. SSE/UI,
playback receipts, proactive permission, and reconnect replay remain deferred.
See [ACP Runtime](L1/L2/acp_runtime.md).
