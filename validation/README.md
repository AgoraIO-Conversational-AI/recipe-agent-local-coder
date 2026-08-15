# Voice LLM architecture validation

This directory contains a bounded comparison of two Agora Voice LLM paths for the Voice-to-ACP Local recipe:

- **Managed:** Agora-managed OpenAI plus live `system_messages` replacement.
- **Custom:** an authenticated OpenAI-compatible callback that injects the same current permission context before forwarding one model request.

The comparison uses one real model, the same STT and TTS pipeline, the same prompt and generation settings, identical MCP tools, and the versioned scenario corpus in [`corpus.json`](./corpus.json). It validates the Voice LLM seam only. It does not run ACP, Codex, a durable Task Runtime, or production Work storage.

Raw evidence and rendered reports are written under `validation/results/` and remain local because they can contain voice transcripts. Only anonymized aggregate evidence belongs in the architecture decision record.

## Safety rule

A candidate is disqualified by any cross-session permission leak, uncorrelated permission resolution, Work creation while a permission is pending, or other forbidden tool call in a safety-critical scenario. The validation must select one path and remove the losing runtime adapter before product implementation begins.

## Run the live matrix

The validation is certified only on Apple Silicon macOS. Complete the ordinary quickstart setup first:

```bash
bun run setup
agora login
agora project use <your-project>
agora project env write server/.env.local
```

Add these non-secret values to `server/.env.local`:

```dotenv
VALIDATION_MODEL=gpt-4o-mini
PUBLIC_VALIDATION_BASE_URL=https://your-current-tunnel.example
MODEL_PROVIDER_BASE_URL=https://api.openai.com/v1
```

For the Custom run only, enter `MODEL_PROVIDER_API_KEY` directly in `server/.env.local`. Never paste it into chat, logs, or evidence.

Expose only the public validation listener:

```bash
ngrok http 8001
```

Before live speech, verify the tunnel returns `404` for `/get_config`, `/startAgent`, `/stopAgent`, and `/validation/admin/permissions`; `/mcp/` without a bearer must return `401`. During Managed validation, `/llm/chat/completions` must return `404`; during Custom validation it must return `401` without its separate callback capability.

Use two local terminals. The runner starts the loopback and public Python listeners; the frontend remains the unchanged quickstart process:

```bash
# Terminal 1
bun run validate:managed

# Terminal 2
bun run dev:frontend
```

Complete the prompted trials, then repeat with `bun run validate:custom`. The runner resumes completed trial IDs and never overwrites evidence. After both paths finish:

```bash
bun run validate:report
```

Raw JSONL and rendered reports remain under `validation/results/` and are gitignored. Stop the frontend, runner, and ngrok when finished. The validation harness is not a production runtime.
