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
