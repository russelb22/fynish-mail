#!/usr/bin/env python3
"""Apply the PostgreSQL bootstrap schema to the configured Postgres database."""

from __future__ import annotations

import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DATABASE_URL, DB_MODE  # noqa: E402
from app.db.runtime import get_engine, reset_engine_for_tests  # noqa: E402
from app.db.database import ADDITIVE_COLUMNS  # noqa: E402

SCHEMA_PATH = ROOT / "backend" / "app" / "db" / "schema.postgres.sql"
EXPECTED_TABLES = {
    "accounts",
    "users",
    "mail_accounts",
    "provider_connections",
    "messages",
    "classification_results",
    "rules",
    "actions_log",
    "staged_commit_requests",
    "gmail_account_connections",
    "notification_settings",
    "notification_settings_by_user",
    "digest_delivery_log",
}


def _load_statements() -> list[str]:
    if not SCHEMA_PATH.exists():
        raise FileNotFoundError(f"Schema file not found: {SCHEMA_PATH}")
    raw_sql = SCHEMA_PATH.read_text(encoding="utf-8")
    return [statement.strip() for statement in raw_sql.split(";") if statement.strip()]


def _ensure_additive_columns(conn) -> None:
    for table_name, columns in ADDITIVE_COLUMNS.items():
        existing_columns = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT column_name
                    FROM information_schema.columns
                    WHERE table_schema = 'public' AND table_name = :table_name
                    """
                ),
                {"table_name": table_name},
            )
        }
        for column_name, definition in columns:
            if column_name in existing_columns:
                continue
            conn.exec_driver_sql(
                f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}"
            )


def main() -> int:
    if DB_MODE != "postgres":
        print("ERROR: FYNISH_DB_MODE must be set to 'postgres' for schema apply.")
        return 1
    if not DATABASE_URL.startswith("postgresql+psycopg://"):
        print("ERROR: FYNISH_DATABASE_URL must use the postgresql+psycopg:// SQLAlchemy URL shape.")
        return 1

    reset_engine_for_tests()
    engine = get_engine()
    statements = _load_statements()

    print(f"Applying PostgreSQL schema from {SCHEMA_PATH} ...")
    with engine.begin() as conn:
        for statement in statements:
            conn.exec_driver_sql(statement)
        _ensure_additive_columns(conn)

        existing_tables = {
            row[0]
            for row in conn.execute(
                text(
                    """
                    SELECT tablename
                    FROM pg_catalog.pg_tables
                    WHERE schemaname = 'public'
                    """
                )
            )
        }

    missing = sorted(EXPECTED_TABLES - existing_tables)
    if missing:
        print("ERROR: Schema apply completed, but expected tables are missing:")
        for table in missing:
            print(f"  - {table}")
        return 1

    print("PostgreSQL schema apply succeeded.")
    print(f"Verified {len(EXPECTED_TABLES)} expected tables.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
