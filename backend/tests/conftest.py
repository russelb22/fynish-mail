from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


ROOT_DIR = Path(__file__).resolve().parents[2]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import database
from app.db import runtime
from app.main import app
from app.services.accounts import seed_mock_accounts
from app.services.review_queue import reclassify_pending_messages, sync_unread_messages


@pytest.fixture()
def empty_db(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    db_path = tmp_path / "fynish-test.sqlite3"
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)
    monkeypatch.setattr(runtime, "DATABASE_PATH", db_path)
    monkeypatch.setattr(runtime, "DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setattr(runtime, "DB_MODE", "sqlite")
    runtime.reset_engine_for_tests()
    database.ensure_database()
    return db_path


@pytest.fixture()
def isolated_db(empty_db: Path) -> Path:
    seed_mock_accounts()
    return empty_db


@pytest.fixture()
def foundation_pre_migration_db(empty_db: Path) -> Path:
    fixture_path = BACKEND_DIR / "tests" / "fixtures" / "foundation_pre_migration_seed.sql"
    with database.get_connection() as conn:
        conn.executescript(fixture_path.read_text())
    return empty_db


@pytest.fixture()
def seeded_db(isolated_db: Path) -> Path:
    sync_unread_messages()
    return isolated_db


@pytest.fixture()
def reclassified_db(seeded_db: Path) -> Path:
    reclassify_pending_messages()
    return seeded_db


@pytest.fixture()
def api_client(isolated_db: Path) -> TestClient:
    with TestClient(app) as client:
        yield client
