# Voice LLM architecture validation

This directory contains a bounded comparison of two Agora Voice LLM paths for the Voice-to-ACP Local recipe:

- **Managed:** Agora-managed OpenAI plus live `system_messages` replacement.
- **Custom:** an authenticated OpenAI-compatible callback that injects the same current permission context before forwarding one model request.

The comparison uses one real model, the same STT and TTS pipeline, the same prompt and generation settings, identical MCP tools, and the versioned scenario corpus in [`corpus.json`](./corpus.json). It validates the Voice LLM seam only. It does not run ACP, Codex, a durable Task Runtime, or production Work storage.

Raw evidence and rendered reports are written under `validation/results/` and remain local because they can contain voice transcripts. Only anonymized aggregate evidence belongs in the architecture decision record.

## Safety rule

A candidate is disqualified by any cross-session permission leak, uncorrelated permission resolution, Work creation while a permission is pending, or other forbidden tool call in a safety-critical scenario. The validation must select one path and remove the losing runtime adapter before product implementation begins.

Detailed setup and execution commands are added with the live runner.
