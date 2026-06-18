#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
COMPOSE_FILE="$ROOT_DIR/docker-compose.postgres.yml"
NATIVE_DATA_DIR="${FYNISH_LOCAL_POSTGRES_DATA_DIR:-$ROOT_DIR/.dev-postgres/data}"
NATIVE_LOG_FILE="${FYNISH_LOCAL_POSTGRES_LOG_FILE:-$ROOT_DIR/.dev-postgres/postgres.log}"
NATIVE_PORT="${FYNISH_LOCAL_POSTGRES_PORT:-54329}"
NATIVE_USER="${FYNISH_LOCAL_POSTGRES_USER:-fynish_app}"
NATIVE_PASSWORD="${FYNISH_LOCAL_POSTGRES_PASSWORD:-fynish_password}"
NATIVE_DB="${FYNISH_LOCAL_POSTGRES_DB:-fynish}"
SCHEMA_FILE="$ROOT_DIR/backend/app/db/schema.postgres.sql"

ensure_native_server_tools() {
  if command -v postgres >/dev/null 2>&1; then
    return 0
  fi

  if command -v brew >/dev/null 2>&1; then
    for formula in postgresql@16 postgresql@15 postgresql; do
      prefix="$(brew --prefix "$formula" 2>/dev/null || true)"
      if [ -n "$prefix" ] && [ -x "$prefix/bin/postgres" ]; then
        export PATH="$prefix/bin:$PATH"
        return 0
      fi
    done

    if brew list --versions libpq >/dev/null 2>&1; then
      echo "Found Homebrew libpq client tools, but no PostgreSQL server binaries."
      echo "Please install a local PostgreSQL server first, for example:"
      echo "  brew install postgresql@16"
      echo "Then re-run:"
      echo "  make postgres-up"
      exit 1
    fi
  fi

  echo "No local PostgreSQL server binary ('postgres') was found."
  echo "Install PostgreSQL server tools or Docker Desktop, then try again."
  exit 1
}

print_env_hint() {
cat <<EOF

Local PostgreSQL is ready.

Suggested env:
  export FYNISH_APP_ENV=local
  export FYNISH_DB_MODE=postgres
  export FYNISH_DATABASE_URL=postgresql+psycopg://${NATIVE_USER}:${NATIVE_PASSWORD}@127.0.0.1:${NATIVE_PORT}/${NATIVE_DB}
  export FYNISH_SEED_MOCK_ACCOUNTS=0
  export FYNISH_AUTO_SYNC_ENABLED=0
  export FYNISH_ENABLE_GMAIL_WRITES=0

Then:
  make postgres-smoke

EOF
}

bootstrap_with_docker() {
  echo "Starting local PostgreSQL container..."
  docker compose -f "$COMPOSE_FILE" up -d postgres

  echo "Waiting for PostgreSQL to become healthy..."
  until docker compose -f "$COMPOSE_FILE" exec -T postgres pg_isready -U fynish_app -d fynish >/dev/null 2>&1; do
    sleep 2
  done

  echo "Applying PostgreSQL schema bootstrap..."
  docker compose -f "$COMPOSE_FILE" exec -T postgres \
    psql -U fynish_app -d fynish -v ON_ERROR_STOP=1 -f /bootstrap/schema.postgres.sql

  print_env_hint
}

bootstrap_with_native_tools() {
  ensure_native_server_tools

  mkdir -p "$(dirname "$NATIVE_DATA_DIR")" "$(dirname "$NATIVE_LOG_FILE")"

  if [ ! -f "$NATIVE_DATA_DIR/PG_VERSION" ]; then
    echo "Initializing local PostgreSQL data directory at $NATIVE_DATA_DIR..."
    initdb -D "$NATIVE_DATA_DIR" --auth=trust >/dev/null
  fi

  if ! pg_isready -h 127.0.0.1 -p "$NATIVE_PORT" >/dev/null 2>&1; then
    echo "Starting local PostgreSQL server on port $NATIVE_PORT..."
    pg_ctl -D "$NATIVE_DATA_DIR" -l "$NATIVE_LOG_FILE" -o "-p $NATIVE_PORT" start >/dev/null
  else
    echo "Local PostgreSQL server already reachable on port $NATIVE_PORT."
  fi

  echo "Waiting for PostgreSQL to become ready..."
  until pg_isready -h 127.0.0.1 -p "$NATIVE_PORT" >/dev/null 2>&1; do
    sleep 2
  done

  echo "Ensuring local role and database exist..."
  psql -h 127.0.0.1 -p "$NATIVE_PORT" -d postgres -v ON_ERROR_STOP=1 <<EOF >/dev/null
DO \$\$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = '${NATIVE_USER}') THEN
        EXECUTE format('CREATE ROLE %I LOGIN PASSWORD %L', '${NATIVE_USER}', '${NATIVE_PASSWORD}');
    ELSE
        EXECUTE format('ALTER ROLE %I WITH LOGIN PASSWORD %L', '${NATIVE_USER}', '${NATIVE_PASSWORD}');
    END IF;
END
\$\$;
EOF

  if ! psql -h 127.0.0.1 -p "$NATIVE_PORT" -d postgres -tAc "SELECT 1 FROM pg_database WHERE datname='${NATIVE_DB}'" | grep -q 1; then
    createdb -h 127.0.0.1 -p "$NATIVE_PORT" -O "$NATIVE_USER" "$NATIVE_DB"
  fi

  echo "Applying PostgreSQL schema bootstrap..."
  psql -h 127.0.0.1 -p "$NATIVE_PORT" -U "$NATIVE_USER" -d "$NATIVE_DB" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE" >/dev/null

  print_env_hint
}

if command -v docker >/dev/null 2>&1; then
  bootstrap_with_docker
elif command -v initdb >/dev/null 2>&1 && command -v pg_ctl >/dev/null 2>&1 && command -v psql >/dev/null 2>&1 || command -v brew >/dev/null 2>&1; then
  bootstrap_with_native_tools
else
  echo "No supported local PostgreSQL bootstrap path found."
  echo "Install Docker Desktop or PostgreSQL command-line tools (initdb, pg_ctl, psql)."
  exit 1
fi
