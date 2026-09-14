#!/usr/bin/env bash
# SOUL EXTER — one command to open the trading floor in your own browser.
#
#   ./scripts/run_local.sh            # build the interface, serve UI + API on :8000
#   PORT=9000 ./scripts/run_local.sh  # different port
#   DEV=1 ./scripts/run_local.sh      # hot-reload dev server on :5173 + API on :8000
#
# Everything runs on this machine; nothing is sent anywhere.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO"
PORT="${PORT:-8000}"
PY="${PYTHON:-python3}"

say() { printf '\033[1;36m›\033[0m %s\n' "$1"; }
die() { printf '\033[1;31m✗\033[0m %s\n' "$1" >&2; exit 1; }

command -v "$PY" >/dev/null || die "python3 not found"
command -v node >/dev/null || die "node not found (needed to build the interface)"

say "installing backend dependencies"
"$PY" -m pip install -q --break-system-packages -r backend/requirements.txt 2>/dev/null \
  || "$PY" -m pip install -q -r backend/requirements.txt

say "installing interface dependencies"
(cd frontend && npm install --silent)

say "building the interface"
(cd frontend && npm run build)

# optional: provider keys for hosted desks
if [ -f .env ]; then
  say "found .env — loading provider keys"
  set -a; . ./.env; set +a
fi

export SOUL_EXTER_SETTINGS="${SOUL_EXTER_SETTINGS:-$REPO/soul_exter_settings.json}"

if [ "${DEV:-0}" = "1" ]; then
  say "API on http://127.0.0.1:$PORT (docs at /docs)"
  ( cd backend && "$PY" -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port "$PORT" ) &
  API_PID=$!
  trap 'kill $API_PID 2>/dev/null || true' EXIT
  sleep 4
  say "interface (hot reload) →  http://localhost:5173"
  ( cd frontend && npm run dev -- --port 5173 )
else
  say "floor ready →  http://localhost:$PORT"
  say "press Ctrl+C to stop"
  cd backend && exec "$PY" -m uvicorn soul_exter.api.server:app --host 0.0.0.0 --port "$PORT"
fi
