#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$ROOT_DIR/.dev-logs"
BACKEND_LOG="$LOG_DIR/backend.log"
FRONTEND_LOG="$LOG_DIR/frontend.log"

mkdir -p "$LOG_DIR"

kill_matching() {
  local pattern="$1"
  local pids
  pids="$(pgrep -f "$pattern" || true)"
  if [[ -n "$pids" ]]; then
    echo "$pids" | xargs kill
    sleep 1
  fi
}

wait_for_http() {
  local url="$1"
  local label="$2"
  for _ in $(seq 1 30); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      echo "$label is ready at $url"
      return 0
    fi
    sleep 1
  done
  echo "$label did not become ready: $url" >&2
  return 1
}

echo "Stopping existing dev servers..."
kill_matching "uvicorn app.main:app --app-dir backend --reload"
kill_matching "vite --host 127.0.0.1 --port 5173"
kill_matching "npm run dev -- --host 127.0.0.1 --port 5173"

echo "Starting backend..."
(
  cd "$ROOT_DIR"
  source .venv/bin/activate
  exec env FYNISH_ENABLE_GMAIL_WRITES=1 uvicorn app.main:app --app-dir backend --reload --host 127.0.0.1 --port 8000
) >"$BACKEND_LOG" 2>&1 &
BACKEND_PID=$!

echo "Starting frontend..."
(
  cd "$ROOT_DIR/frontend"
  exec npm run dev -- --host 127.0.0.1 --port 5173
) >"$FRONTEND_LOG" 2>&1 &
FRONTEND_PID=$!

wait_for_http "http://127.0.0.1:8000/api/health" "Backend"
wait_for_http "http://127.0.0.1:5173/" "Frontend"

cat <<EOF

Restart complete.

Backend PID: $BACKEND_PID
Frontend PID: $FRONTEND_PID

Backend log: $BACKEND_LOG
Frontend log: $FRONTEND_LOG

App URL: http://127.0.0.1:5173/
Health URL: http://127.0.0.1:8000/api/health
EOF
