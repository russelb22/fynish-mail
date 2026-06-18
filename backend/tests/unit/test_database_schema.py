from __future__ import annotations

import sqlite3
from pathlib import Path
from unittest.mock import Mock

from app.db import database


LEGACY_SCHEMA = """
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email_address TEXT NOT NULL UNIQUE,
    enabled INTEGER NOT NULL DEFAULT 1,
    provider TEXT NOT NULL DEFAULT 'mock_gmail',
    last_sync_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL,
    gmail_thread_id TEXT,
    account_email TEXT NOT NULL,
    sender TEXT,
    sender_domain TEXT,
    reply_to TEXT,
    recipient_to TEXT,
    recipient_cc TEXT,
    subject TEXT,
    received_at TEXT,
    snippet TEXT,
    body_preview TEXT,
    gmail_labels_json TEXT NOT NULL DEFAULT '[]',
    headers_json TEXT NOT NULL DEFAULT '{}',
    has_attachments INTEGER NOT NULL DEFAULT 0,
    current_category TEXT,
    confidence REAL,
    protected INTEGER NOT NULL DEFAULT 0,
    reviewed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(gmail_message_id, account_email)
);

CREATE TABLE rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope TEXT NOT NULL DEFAULT 'global',
    account_email TEXT,
    rule_type TEXT NOT NULL,
    pattern TEXT NOT NULL,
    action TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    created_from_account TEXT,
    created_from_message_id TEXT,
    match_count INTEGER NOT NULL DEFAULT 0,
    last_matched_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE actions_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    gmail_message_id TEXT NOT NULL,
    account_email TEXT NOT NULL,
    selected_action TEXT NOT NULL,
    recommended_action TEXT,
    user_overrode INTEGER NOT NULL DEFAULT 0,
    gmail_labels_added_json TEXT NOT NULL DEFAULT '[]',
    gmail_labels_removed_json TEXT NOT NULL DEFAULT '[]',
    created_rule_id INTEGER,
    created_at TEXT NOT NULL
);
"""


def _column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table_name})").fetchall()}


def test_ensure_database_adds_foundation_tables_and_columns(monkeypatch, tmp_path: Path):
    db_path = tmp_path / "legacy.sqlite3"
    monkeypatch.setattr(database, "DATA_DIR", tmp_path)
    monkeypatch.setattr(database, "DATABASE_PATH", db_path)

    with sqlite3.connect(db_path) as conn:
        conn.executescript(LEGACY_SCHEMA)
        conn.commit()

    database.ensure_database()

    with sqlite3.connect(db_path) as conn:
        tables = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }

        assert "users" in tables
        assert "mail_accounts" in tables
        assert "provider_connections" in tables
        assert "digest_sender_connections" in tables
        assert "notification_settings_by_user" in tables
        assert "digest_delivery_log" in tables

        message_columns = _column_names(conn, "messages")
        assert "mail_account_id" in message_columns
        assert "provider_message_id" in message_columns
        assert "provider_thread_id" in message_columns
        assert "provider_labels_json" in message_columns
        assert "recovery_pending" in message_columns
        assert "queue_source" in message_columns
        assert "queue_source_detail" in message_columns

        rule_columns = _column_names(conn, "rules")
        assert "user_id" in rule_columns
        assert "mail_account_id" in rule_columns
        assert "created_from_mail_account_id" in rule_columns

        action_columns = _column_names(conn, "actions_log")
        assert "message_id" in action_columns
        assert "mail_account_id" in action_columns
        assert "provider_message_id" in action_columns
        assert "provider_labels_added_json" in action_columns
        assert "provider_labels_removed_json" in action_columns
        assert "action_source" in action_columns

        mail_account_columns = _column_names(conn, "mail_accounts")
        assert "high_confidence_auto_clean_enabled" in mail_account_columns

        notification_columns = _column_names(conn, "notification_settings_by_user")
        assert "digest_enabled" in notification_columns
        assert "digest_time" in notification_columns
        assert "ai_digest_summary_enabled" in notification_columns


def test_ensure_database_postgres_mode_checks_connectivity_and_additive_schema(monkeypatch):
    fake_result = Mock()
    fake_connection = Mock()
    fake_connection.execute.return_value = fake_result
    fake_connection.exec_driver_sql.side_effect = [None, None, None, None, None, None, [], None, None]
    fake_begin_ctx = Mock()
    fake_begin_ctx.__enter__ = Mock(return_value=fake_connection)
    fake_begin_ctx.__exit__ = Mock(return_value=None)
    fake_engine = Mock()
    fake_engine.begin.return_value = fake_begin_ctx

    monkeypatch.setattr(database, "DB_MODE", "postgres")
    monkeypatch.setattr(database, "get_engine", Mock(return_value=fake_engine))

    database.ensure_database()

    fake_engine.begin.assert_called_once()
    fake_connection.execute.assert_called_once()
    assert fake_connection.exec_driver_sql.call_count == 9
