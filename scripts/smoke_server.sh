#!/usr/bin/env bash
# Run a checkpoint smoke test (scripts/smoke.py) against a real server started on a temp DB in the background.
# Usage: scripts/smoke_server.sh cp1|cp2|cp3
# Env:   SMOKE_BASE=http://host:port  test an already-running server instead (nothing is started)
#        SMOKE_PORT (default 8765) · SMOKE_BOOT_S (default 90) · any STORMCHECK_* / *_IMPL / LLM_MODE knob
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"
cp="${1:?usage: scripts/smoke_server.sh cp1|cp2|cp3}"
if [ -n "${SMOKE_BASE:-}" ]; then
  exec uv run python scripts/smoke.py "$cp" --base "$SMOKE_BASE"
fi
port="${SMOKE_PORT:-8765}"
tmp="$(mktemp -d -t sc-smoke-XXXXXX)"
export STORMCHECK_DB="$tmp/stormcheck.db"
uv run uvicorn server.app:app --host 127.0.0.1 --port "$port" >"$tmp/server.log" 2>&1 &
pid=$!
cleanup() { kill "$pid" 2>/dev/null || true; wait "$pid" 2>/dev/null || true; rm -rf "$tmp"; }
trap cleanup EXIT INT TERM
deadline=$(( $(date +%s) + ${SMOKE_BOOT_S:-90} ))
until curl -sf "http://127.0.0.1:$port/api/health" >/dev/null; do
  if ! kill -0 "$pid" 2>/dev/null || [ "$(date +%s)" -ge "$deadline" ]; then
    echo "smoke: server did not come up on :$port"; tail -40 "$tmp/server.log"; exit 1
  fi
  sleep 0.5
done
if ! uv run python scripts/smoke.py "$cp" --base "http://127.0.0.1:$port"; then
  echo "---- server log (tail)"; tail -30 "$tmp/server.log"; exit 1
fi
