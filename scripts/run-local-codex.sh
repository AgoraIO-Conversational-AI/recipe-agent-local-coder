#!/usr/bin/env bash
set -euo pipefail

runner=""
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

cleanup() {
  if [[ -n "$runner" ]] && kill -0 "$runner" 2>/dev/null; then
    kill -INT "$runner" 2>/dev/null || true
    wait "$runner" || true
  fi
}

trap cleanup EXIT INT TERM

concurrently -k --success first -n backend,frontend -c blue,green \
  "$backend_command" \
  "$frontend_command" &
runner=$!
wait "$runner"
