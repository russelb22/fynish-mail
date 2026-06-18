from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.database import get_connection
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.services.gmail_readonly import GmailReadonlySyncError


def _insert_gmail_account_and_message(scopes: list[str]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        user_row = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (DEFAULT_LOCAL_OWNER_EMAIL,),
        ).fetchone()
        if user_row is None:
            user_cursor = conn.execute(
                """
                INSERT INTO users (email, display_name, status, created_at, updated_at)
                VALUES (?, ?, 'active', ?, ?)
                """,
                (DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME, now, now),
            )
            user_id = user_cursor.lastrowid
        else:
            user_id = user_row["id"]
        existing_account = conn.execute(
            "SELECT id FROM accounts WHERE email_address = ?",
            ("owner@example.com",),
        ).fetchone()
        if existing_account is None:
            cursor = conn.execute(
                """
                INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                VALUES (?, 1, 'gmail_readonly', ?, ?)
                """,
                ("owner@example.com", now, now),
            )
            account_id = cursor.lastrowid
        else:
            account_id = existing_account["id"]
        existing_mail_account = conn.execute(
            """
            SELECT id
            FROM mail_accounts
            WHERE user_id = ? AND provider = 'gmail_readonly' AND external_account_email = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (user_id, "owner@example.com"),
        ).fetchone()
        if existing_mail_account is None:
            mail_account_cursor = conn.execute(
                """
                INSERT INTO mail_accounts (
                    user_id, provider, external_account_email, display_name,
                    enabled, status, created_at, updated_at
                ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', ?, ?)
                """,
                (user_id, "owner@example.com", "owner@example.com", now, now),
            )
            mail_account_id = mail_account_cursor.lastrowid
        else:
            mail_account_id = existing_mail_account["id"]
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(account_id) DO UPDATE SET
                token_path = excluded.token_path,
                scopes_json = excluded.scopes_json,
                updated_at = excluded.updated_at
            """,
            (account_id, "/tmp/fake-token.json", json.dumps(scopes), now, now),
        )
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, token_path, scopes_json, metadata_json,
                created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', ?, ?, '{}', ?, ?)
            """,
            (mail_account_id, "/tmp/fake-token.json", json.dumps(scopes), now, now),
        )
        existing_count = conn.execute(
            "SELECT COUNT(*) AS count FROM messages WHERE account_email = ?",
            ("owner@example.com",),
        ).fetchone()["count"]
        gmail_message_id = f"real-2001-{existing_count + 1}"
        thread_id = f"thread-2001-{existing_count + 1}"
        message_cursor = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, headers_json, has_attachments,
                current_category, confidence, protected, reviewed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                gmail_message_id,
                thread_id,
                "owner@example.com",
                mail_account_id,
                "Sender <sender@example.com>",
                "example.com",
                "",
                "owner@example.com",
                "",
                "Dry run candidate",
                now,
                "Snippet",
                "Preview",
                json.dumps(["UNREAD", "INBOX"]),
                json.dumps({}),
                0,
                "bulk_mail",
                0.99,
                0,
                0,
                now,
                now,
            ),
        )
    return int(message_cursor.lastrowid)


def test_live_plan_endpoint_returns_safe_plan(api_client, isolated_db):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.readonly"]
    )

    response = api_client.post(
        f"/api/messages/{message_id}/live-plan",
        json={"action": "bulk_mail"},
    )

    assert response.status_code == 200
    payload = response.json()["plan"]
    assert payload["message_id"] == message_id
    assert payload["labels_to_add"] == ["Fynish/Bulk Mail"]
    assert payload["labels_to_remove"] == ["INBOX"]
    assert payload["allowed"] is True
    assert "UNREAD label will be preserved" in payload["safety_notes"]


def test_live_execute_endpoint_returns_blocked_result_when_feature_is_off(
    api_client, isolated_db
):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )

    response = api_client.post(
        f"/api/messages/{message_id}/live-execute",
        json={"action": "bulk_mail"},
    )

    assert response.status_code == 200
    payload = response.json()["result"]
    assert payload["message_id"] == message_id
    assert payload["executed"] is False
    assert payload["oauth_scope_ready"] is True
    assert payload["live_writes_enabled"] is False
    assert any("disabled" in note for note in payload["notes"])


def test_live_execute_endpoint_returns_reconnect_error_for_expired_token(
    monkeypatch,
    api_client,
    isolated_db,
):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )

    def fail_execute(*args, **kwargs):
        raise GmailReadonlySyncError(
            "Stored Gmail credentials were expired or revoked. Reconnect the account."
        )

    monkeypatch.setattr("app.api.routes.execute_message_action", fail_execute)

    response = api_client.post(
        f"/api/messages/{message_id}/live-execute",
        json={"action": "bulk_mail"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Stored Gmail credentials were expired or revoked. Reconnect the account."
    )
    assert response.json()["code"] == "gmail_reconnect_required"


def test_bulk_live_execute_endpoint_returns_results_for_each_message(
    api_client, isolated_db
):
    first_message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    second_message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )

    response = api_client.post(
        "/api/messages/apply-selected-live",
        json={
            "items": [
                {"message_id": first_message_id, "action": "bulk_mail"},
                {"message_id": second_message_id, "action": "keep"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 2
    assert payload["executed"] == 1
    assert payload["blocked"] == 1


def test_bulk_live_execute_endpoint_reports_missing_message(
    api_client,
    isolated_db,
):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )

    response = api_client.post(
        "/api/messages/apply-selected-live",
        json={
            "items": [
                {"message_id": message_id, "action": "keep"},
                {"message_id": 999999, "action": "bulk_mail"},
            ]
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["results"]) == 2
    assert payload["executed"] == 1
    assert payload["failed"] == 1
    missing_result = payload["results"][1]
    assert missing_result["message_id"] == 999999
    assert missing_result["status"] == "failed"
    assert missing_result["notes"] == ["Message is no longer available."]
