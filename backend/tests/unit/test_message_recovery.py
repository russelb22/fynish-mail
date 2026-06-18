from __future__ import annotations

from unittest.mock import Mock

from app.db.database import get_connection
from app.services import message_recovery


def test_recover_gmail_message_skips_empty_modify(monkeypatch):
    connection_row = {
        "provider": "gmail_readonly",
        "token_path": "/tmp/token.json",
        "scopes_json": "[]",
        "metadata_json": "{}",
        "account_email": "primary.user@example.com",
    }
    adapter = Mock()

    monkeypatch.setattr(message_recovery, "ENABLE_GMAIL_WRITES", True)
    monkeypatch.setattr(message_recovery, "_connection_row_for_account", lambda conn, account_email: connection_row)
    monkeypatch.setattr(message_recovery, "get_mail_provider_adapter", lambda provider: adapter)

    execute_sql_calls: list[dict] = []

    def _capture_execute_sql(conn, sql, params):
        execute_sql_calls.append({"sql": sql, "params": params})
        return None

    monkeypatch.setattr(message_recovery, "execute_sql", _capture_execute_sql)

    labels_added, labels_removed = message_recovery._recover_gmail_message(
        conn=object(),
        message_row={
            "id": 42,
            "account_email": "primary.user@example.com",
            "provider_message_id": "provider-42",
            "gmail_message_id": "gmail-42",
            "provider_labels_json": '["INBOX","UNREAD"]',
        },
    )

    assert labels_added == []
    assert labels_removed == []
    adapter.modify_message_labels.assert_not_called()
    assert execute_sql_calls[0]["params"]["provider_labels_json"] == '["INBOX", "UNREAD"]'


def test_connection_row_for_account_prefers_normalized_provider_connection(isolated_db):
    now = "2026-05-14T19:00:00+00:00"
    with get_connection() as conn:
        user_id = conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            ("owner@example.com", "Owner", now, now),
        ).lastrowid
        mail_account_id = conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', ?, ?)
            """,
            (user_id, "owner@example.com", "Owner Gmail", now, now),
        ).lastrowid
        provider_connection_id = conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, ?, '[]', '{}', ?, ?)
            """,
            (mail_account_id, "/tmp/normalized-token.json", now, now),
        ).lastrowid

        row = message_recovery._connection_row_for_account(conn, "owner@example.com")

    assert row is not None
    assert row["provider"] == "gmail_readonly"
    assert row["provider_connection_id"] == provider_connection_id
    assert row["token_path"] == "/tmp/normalized-token.json"
