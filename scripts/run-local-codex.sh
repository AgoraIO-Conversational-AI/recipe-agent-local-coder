#!/usr/bin/env bash
set -euo pipefail

backend_command="${LOCAL_BACKEND_COMMAND:-bun run dev:backend:codex}"
frontend_command="${LOCAL_FRONTEND_COMMAND:-bun run dev:frontend:codex}"

fail_usage() {
  echo "Usage: bun run dev:codex -- [--workspace /absolute/path] [--acp-command-json JSON_ARRAY]" >&2
  exit 2
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workspace)
      [[ $# -ge 2 && -n "$2" ]] || fail_usage
      export VOICE_ACP_WORKSPACE="$2"
      shift 2
      ;;
    --acp-command-json)
      [[ $# -ge 2 && -n "$2" ]] || fail_usage
      export VOICE_ACP_COMMAND_JSON="$2"
      shift 2
      ;;
    *)
      fail_usage
      ;;
  esac
done

export VOICE_ACP_LOCAL_RUNTIME=1
export VOICE_ACP_MCP_PORT="${VOICE_ACP_MCP_PORT:-8001}"
grace_seconds="${LOCAL_LAUNCHER_GRACE_SECONDS:-10}"

exec python3 scripts/supervise-local.py \
  --grace-seconds "$grace_seconds" \
  "$backend_command" \
  "$frontend_command"
