# Domain context

## Voice LLM Path

The interpretation layer inside Agora's cascading voice pipeline. Voice-to-ACP Local v0.1 supports one path: Managed Voice LLM.

## Managed Voice LLM

Agora's managed OpenAI integration. The Recipe updates its bounded system context through the authenticated Agent session and exposes ACP-facing tools through authenticated MCP.

## Custom Voice LLM

A possible future alternative in which the Recipe owns an OpenAI-compatible model callback. It is not a supported or maintained v0.1 runtime path.

## Architecture Evidence

Versioned offline tests and explicitly authorized live observations used to support an architecture decision. Evidence must distinguish verified behavior from unrun comparisons and must record live-usage cost constraints.

## Agent Profile

A backend-neutral declaration of an ACP Agent's configuration needs and supported Workspace capabilities. The v0.1 Codex profile requires one primary directory and supports no additional directories.

## Workspace Scope

The session context bound to Work and an ACP session. It contains a stable local identifier and one resolved primary directory without implying filesystem isolation.

## Project Folder

The user-facing name for the Workspace Scope's primary directory: where the Agent works and resolves relative paths. It is not the only folder the Agent can access and is not a Recipe-owned sandbox.

## Configuration Gate

The blocking pre-ready state shown when the active Agent Profile requires a Project Folder and no valid selection exists. Settings remains available after the gate is cleared so the selection can be changed safely.

## Local Launcher Supervisor

The local-only lifecycle boundary that owns terminal signals and coordinates one clean shutdown of the backend, frontend, and their descendants.
_Avoid_: Signal broadcaster, process-group launcher

## Work

One durable, Workspace-scoped executable objective delegated to the ACP Agent.

## Work Receipt

The authoritative persisted record of Work identity, state, safe activity,
result, and delivery status. Acceptance exists only after this record commits.

## Pending Permission

One unresolved current-operation authorization request. It has no TTL and only
an explicit allow, reject, Work cancellation, ACP cancellation, or runner exit
can resolve it.

## Final Presentation

The backend-neutral completed result containing required speech text and
optional safe inline content.

## Task Runtime

The local coordinator that owns durable Work receipts, FIFO ACP execution,
permission correlation, confirmed cancellation, and safe result persistence.

## Managed MCP Ingress

The dedicated loopback Streamable HTTP listener exposed temporarily through
ngrok so Agora's Managed Voice LLM can call the local Task Runtime. It contains
only the four production Work tools and is never mounted into lifecycle
FastAPI.

## Agent Capability

One high-entropy, in-memory bearer prepared for one Agora Agent creation. While
pending, it authenticates only side-effect-free MCP discovery. Work authority
exists only after the bearer is bound to the exact active Agora Agent,
Workspace Scope, and Workspace generation. It is a temporary development
credential rather than the durable identity of Work and is revoked before the
Agent stops.
