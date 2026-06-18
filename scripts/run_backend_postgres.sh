#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
BACKEND_PORT="${FYNISH_BACKEND_PORT:-8000}"

export FYNISH_APP_ENV="${FYNISH_APP_ENV:-local}"
export FYNISH_DB_MODE="${FYNISH_DB_MODE:-postgres}"
export FYNISH_DATABASE_URL="${FYNISH_DATABASE_URL:-postgresql+psycopg://fynish_app:fynish_password@127.0.0.1:54329/fynish}"
export FYNISH_SEED_MOCK_ACCOUNTS="${FYNISH_SEED_MOCK_ACCOUNTS:-0}"
export FYNISH_AUTO_SYNC_ENABLED="${FYNISH_AUTO_SYNC_ENABLED:-0}"
export FYNISH_ENABLE_GMAIL_WRITES="${FYNISH_ENABLE_GMAIL_WRITES:-0}"
export FYNISH_FRONTEND_URL="${FYNISH_FRONTEND_URL:-http://127.0.0.1:5173/}"
export FYNISH_BACKEND_CORS_ORIGINS="${FYNISH_BACKEND_CORS_ORIGINS:-http://127.0.0.1:5173}"

cd "$ROOT_DIR"
source .venv/bin/activate
exec uvicorn app.main:app --app-dir backend --host 127.0.0.1 --port "$BACKEND_PORT" --reload
