from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db import database
from app.services.accounts import seed_mock_accounts
from app.services.reminders import get_reminder_summary
from app.services.review_queue import get_review_queue, reclassify_pending_messages, sync_unread_messages


def reset_database(remove_existing: bool = True) -> Path:
    if remove_existing and database.DATABASE_PATH.exists():
        database.DATABASE_PATH.unlink()
    database.ensure_database()
    seed_mock_accounts()
    return database.DATABASE_PATH


def count_messages() -> int:
    with database.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()
    return int(row["count"])


def count_rules() -> int:
    with database.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM rules").fetchone()
    return int(row["count"])


def count_accounts() -> int:
    with database.get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM accounts").fetchone()
    return int(row["count"])


def queue_snapshot() -> dict:
    return get_review_queue()


def simple_queue_counts() -> dict:
    queue = get_review_queue()
    return {
        account["account_email"]: {
            group["category"]: group["count"] for group in account["groups"]
        }
        for account in queue["accounts"]
    }


def dump_json(data: dict) -> str:
    return json.dumps(data, indent=2, sort_keys=True)


def reminder_snapshot() -> dict:
    return get_reminder_summary()


def sync_mock_messages() -> dict:
    before = count_messages()
    result = sync_unread_messages()
    after = count_messages()
    result["inserted"] = max(0, after - before)
    result["skipped_duplicates"] = max(0, result["synced_messages"] - result["inserted"])
    return result


def reclassify_queue() -> dict:
    return reclassify_pending_messages()
