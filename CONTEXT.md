# Domain context

## Voice LLM Path

The interpretation layer inside Agora's cascading voice pipeline. Voice-to-ACP Local v0.1 supports one path: Managed Voice LLM.

## Managed Voice LLM

Agora's managed OpenAI integration. The Recipe updates its bounded system context through the authenticated Agent session and exposes ACP-facing tools through authenticated MCP.

## Custom Voice LLM

A possible future alternative in which the Recipe owns an OpenAI-compatible model callback. It is not a supported or maintained v0.1 runtime path.

## Architecture Evidence

Versioned offline tests and explicitly authorized live observations used to support an architecture decision. Evidence must distinguish verified behavior from unrun comparisons and must record live-usage cost constraints.
