from __future__ import annotations

import importlib
import json
import os
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

os.environ.setdefault("FYNISH_APP_ENV", "local")
os.environ.setdefault("FYNISH_DB_MODE", "postgres")
os.environ.setdefault(
    "FYNISH_DATABASE_URL",
    "postgresql+psycopg://fynish_app:fynish_password@127.0.0.1:54329/fynish",
)
os.environ.setdefault("FYNISH_SEED_MOCK_ACCOUNTS", "0")
os.environ.setdefault("FYNISH_AUTO_SYNC_ENABLED", "0")
os.environ.setdefault("FYNISH_ENABLE_GMAIL_WRITES", "0")


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import DATABASE_URL, DB_MODE
from app.db.database import ensure_database
from app.db.runtime import get_engine


API_BASE_URL = os.getenv("FYNISH_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _print_result(ok: bool, label: str) -> bool:
    print(f"{'PASS' if ok else 'FAIL'} {label}")
    return ok


def _request_json(path: str) -> dict:
    request = Request(f"{API_BASE_URL}{path}", headers={"Content-Type": "application/json"})
    with urlopen(request) as response:
        return json.loads(response.read().decode())


def main() -> int:
    checks: list[bool] = []

    checks.append(_print_result(DB_MODE == "postgres", "FYNISH_DB_MODE is set to postgres"))
    checks.append(
        _print_result(
            DATABASE_URL.startswith("postgresql+psycopg://"),
            "FYNISH_DATABASE_URL uses the psycopg SQLAlchemy dialect",
        )
    )

    try:
        importlib.import_module("psycopg")
        checks.append(_print_result(True, "psycopg driver is installed"))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(_print_result(False, f"psycopg driver import failed: {exc}"))

    try:
        ensure_database()
        with get_engine().connect() as conn:
            row = conn.exec_driver_sql(
                "SELECT current_database() AS db_name, current_user AS db_user"
            ).mappings().first()
        checks.append(
            _print_result(
                row is not None and bool(row["db_name"]) and bool(row["db_user"]),
                "direct PostgreSQL connectivity check succeeded",
            )
        )
        if row is not None:
            print(f"INFO connected to database={row['db_name']} user={row['db_user']}")
    except Exception as exc:
        checks.append(_print_result(False, f"direct PostgreSQL connectivity failed: {exc}"))

    try:
        health = _request_json("/api/health")
        checks.append(_print_result(health.get("status") == "ok", "backend health endpoint reachable"))

        queue = _request_json("/api/review-queue")
        checks.append(
            _print_result(
                isinstance(queue.get("accounts"), list),
                "review queue endpoint returned accounts payload",
            )
        )

        rules = _request_json("/api/rules")
        checks.append(
            _print_result(
                isinstance(rules.get("rules"), list),
                "rules endpoint returned rules list",
            )
        )

        processed = _request_json("/api/messages/processed")
        checks.append(
            _print_result(
                isinstance(processed.get("messages"), list),
                "processed mail endpoint returned messages list",
            )
        )
    except URLError as exc:
        checks.append(_print_result(False, f"backend API not reachable at {API_BASE_URL}: {exc}"))
    except Exception as exc:  # pragma: no cover - defensive
        checks.append(_print_result(False, f"backend API validation failed: {exc}"))

    passed = sum(1 for ok in checks if ok)
    failed = len(checks) - passed
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
