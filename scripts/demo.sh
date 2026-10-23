#!/usr/bin/env bash
# One-command demo: build the serving data, then run the API and the production web build.
# Usage: make demo   (API_PORT / WEB_PORT override the defaults)
set -euo pipefail
cd "$(dirname "$0")/.."

API_PORT="${API_PORT:-8000}"
WEB_PORT="${WEB_PORT:-3210}"

need() { command -v "$1" >/dev/null || { echo "✗ $1 is required ($2)"; exit 1; }; }
need uv "https://docs.astral.sh/uv/"
need node "Node 20+ — https://nodejs.org"
for p in "$API_PORT" "$WEB_PORT"; do
  if lsof -iTCP:"$p" -sTCP:LISTEN >/dev/null 2>&1; then
    echo "✗ port $p is in use; set API_PORT / WEB_PORT to free ports"; exit 1
  fi
done

echo "→ Python environment";            make -s setup >/dev/null
echo "→ Simulating Halden and building the warehouse (dbt)"; make -s build >/dev/null
echo "→ Web dependencies";               (cd web && npm ci --silent --no-audit --no-fund)
echo "→ Production web build";           (cd web && npx next build >/dev/null)

pids=()
cleanup() { kill "${pids[@]}" 2>/dev/null || true; }
trap cleanup EXIT INT TERM

uv run uvicorn atlas.api.app:app --port "$API_PORT" --log-level warning &
pids+=($!)
(cd web && ATLAS_API_URL="http://127.0.0.1:$API_PORT" npx next start -p "$WEB_PORT") >/dev/null &
pids+=($!)

for _ in $(seq 60); do
  curl -sf "http://127.0.0.1:$API_PORT/health" >/dev/null && curl -sf "http://127.0.0.1:$WEB_PORT/halden" >/dev/null && break
  sleep 1
done
echo
echo "✓ ATLAS is running"
echo "    App  http://localhost:$WEB_PORT"
echo "    API  http://localhost:$API_PORT/docs"
echo "  Ctrl-C to stop."
wait
