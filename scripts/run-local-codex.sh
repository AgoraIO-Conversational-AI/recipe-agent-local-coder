#!/usr/bin/env bash
set -euo pipefail

runner=""

cleanup() {
  if [[ -n "$runner" ]] && kill -0 "$runner" 2>/dev/null; then
    kill -INT "$runner" 2>/dev/null || true
    wait "$runner" || true
  fi
}

trap cleanup EXIT INT TERM

concurrently -k --success first -n backend,frontend -c blue,green \
  "bun run dev:backend:codex" \
  "bun run dev:frontend:codex" &
runner=$!
wait "$runner"
