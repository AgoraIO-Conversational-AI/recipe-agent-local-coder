#!/usr/bin/env bash
set -euo pipefail

runner=""
backend_command="${LOCAL_BACKEND_COMMAND:-bun run dev:backend:codex}"
frontend_command="${LOCAL_FRONTEND_COMMAND:-bun run dev:frontend:codex}"

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
