from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.core.config import DATABASE_PATH, DATABASE_URL, DB_MODE


_engine: Engine | None = None


def _is_sqlalchemy_connection(connection: Any) -> bool:
    return hasattr(connection, "dialect")


def _ensure_sqlite_parent_dir() -> None:
    if DB_MODE != "sqlite":
        return
    Path(DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    global _engine
    if _engine is None:
        _ensure_sqlite_parent_dir()
        _engine = create_engine(DATABASE_URL, future=True)
    return _engine


def reset_engine_for_tests() -> None:
    global _engine
    if _engine is not None:
        _engine.dispose()
        _engine = None


@contextmanager
def get_connection():
    engine = get_engine()
    with engine.begin() as connection:
        yield connection


def fetch_all(
    connection: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
) -> list[RowMapping]:
    if _is_sqlalchemy_connection(connection):
        return list(connection.execute(text(sql), params or {}).mappings().all())
    return list(connection.execute(sql, params or {}).fetchall())


def fetch_one(
    connection: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
) -> RowMapping | None:
    if _is_sqlalchemy_connection(connection):
        return connection.execute(text(sql), params or {}).mappings().first()
    return connection.execute(sql, params or {}).fetchone()


def execute_sql(
    connection: Connection,
    sql: str,
    params: dict[str, Any] | None = None,
):
    if _is_sqlalchemy_connection(connection):
        return connection.execute(text(sql), params or {})
    return connection.execute(sql, params or {})


def insert_and_return_id(
    connection: Connection,
    insert_sql: str,
    params: dict[str, Any] | None = None,
) -> int:
    if not _is_sqlalchemy_connection(connection):
        result = connection.execute(insert_sql, params or {})
        return int(result.lastrowid)

    statement = insert_sql.strip()
    if (
        connection.dialect.name == "postgresql"
        and " returning " not in statement.lower()
    ):
        statement = f"{statement} RETURNING id"

    result = connection.execute(text(statement), params or {})

    if connection.dialect.name == "postgresql":
        first_row = result.first()
        if first_row:
            return int(first_row[0])

    lastrowid = getattr(result, "lastrowid", None)
    if lastrowid is not None:
        return int(lastrowid)

    if result.returns_rows:
        first_row = result.first()
        if first_row:
            return int(first_row[0])

    try:
        inserted_primary_key = result.inserted_primary_key
    except Exception:
        inserted_primary_key = None

    if inserted_primary_key:
        primary_key = inserted_primary_key[0]
        if primary_key is not None:
            return int(primary_key)

    raise RuntimeError("Unable to determine inserted primary key for statement.")
