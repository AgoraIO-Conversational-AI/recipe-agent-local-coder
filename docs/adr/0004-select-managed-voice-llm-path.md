# Select the Managed Voice LLM path for v0.1

## Context

Voice-to-ACP Local needs one Voice LLM path between Agora-managed STT/TTS and the authenticated MCP tools. We implemented offline-testable Managed and Custom candidates and originally planned a 190-run live comparison. Live conversations consume limited Agora project minutes, and the Custom candidate also requires separate provider configuration and credentials.

## Decision

Version 0.1 supports only Agora's Managed Voice LLM path. The Recipe uses the authenticated Agent session to replace bounded system context and announce a current permission, and it exposes only authenticated MCP through the public ingress. It has no runtime path selector, Custom LLM callback route, provider-key configuration, or comparison scorer.

## Evidence

One real Managed voice conversation established that the Agora voice session and authenticated MCP ingress can connect. Offline tests verify Managed construction, bounded context replacement, permission correlation, synthetic tool guards, capability isolation, and public-route isolation. The full Managed-versus-Custom live matrix was not run, so this decision does not claim that Managed won a comparative quality or latency benchmark.

## Rejected alternative

Maintaining a Custom Voice LLM callback in v0.1 was rejected. It would add provider credentials, an authenticated public callback, SSE forwarding, correlation, and another production path before the product's ACP and local-runner value is established. The official Custom LLM recipe remains a reference if future requirements justify reopening provider ownership.

## Consequences

The default matches the Agora Python quickstart and minimizes first-run configuration. Dynamic permission context uses Managed-session updates instead of a Recipe-owned model endpoint. Provider portability and direct control over model requests are deferred. The optional live evidence harness consumes Agora minutes and may run only with explicit authorization.

## Revalidation triggers

Revisit this decision if Managed context updates cannot meet permission-correlation requirements, a required model or region is unavailable through the Managed path, customers require model-provider ownership or data-path control, measurable latency or reliability fails the release corpus, or Agora changes the Managed API contract materially.
