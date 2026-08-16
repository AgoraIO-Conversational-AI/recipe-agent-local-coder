# Managed Voice LLM evidence harness

This directory contains an optional evidence harness for the Managed Voice LLM path selected for Voice-to-ACP Local v0.1. It uses the versioned scenario corpus in [`corpus.json`](./corpus.json) to exercise bounded permission context and synthetic MCP tools. It does not run ACP, Codex, commands, file operations, a durable Task Runtime, or production Work storage.

The Managed path was selected under a cost and setup constraint, not by completing the originally planned Managed-versus-Custom live matrix. One successful Managed conversation established that the Agora voice session and authenticated MCP ingress can connect. Offline tests cover local context, tool, capability, and route-isolation behavior. Those facts do not constitute a comparative benchmark.

Raw evidence is written under `validation/results/` and remains local because it can contain voice transcripts. The removed Custom LLM callback remains a future architecture alternative, not a supported v0.1 runtime path.

## Cost and authorization

Every live run starts Agora voice conversations and consumes project minutes. Do not run `validate:managed`, start a browser conversation, or invoke the Agora agent lifecycle merely to verify code. Use the offline test commands for ordinary development. Run this harness only when a person has explicitly authorized the expected live usage.

## Offline verification

From the repository root:

```bash
bun run verify:backend
```

This compiles the Python sources and runs the architecture-evidence tests without contacting Agora.

## Optional live evidence run

The harness is certified only on Apple Silicon macOS. Complete the ordinary quickstart setup first:

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
```

Expose only the public evidence listener:

```bash
ngrok http 8001
```

Before live speech, verify that the tunnel returns `404` for `/get_config`, `/startAgent`, `/stopAgent`, `/validation/admin/permissions`, and `/llm/chat/completions`. `/mcp/` without a bearer must return `401`.

Use two local terminals:

```bash
# Terminal 1: starts the loopback and public Python listeners
bun run validate:managed

# Terminal 2: starts the unchanged quickstart frontend
bun run dev:frontend
```

The runner resumes completed trial IDs and never overwrites evidence. A reconnect trial is accepted only after the browser creates a new Agora agent session; the harness rebinds the same synthetic pending permission to that session. Invalidated operator or setup attempts require a reason, remain in raw evidence, and are rerun.

For a bounded setup check, `bun run validate:managed:smoke` runs each scenario once. It still consumes live Agora minutes. Stop the frontend, runner, and ngrok when finished.
