from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import GMAIL_MODIFY_SCOPE
from app.db.database import get_connection
from app.services.gmail_readonly import GmailReadonlyNotConfiguredError
from app.services.review_queue import apply_message_action, get_review_queue, sync_unread_messages


def test_connect_gmail_endpoint_requires_oauth_client_file(api_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.connect_gmail_readonly_account",
        lambda **_: (_ for _ in ()).throw(
            GmailReadonlyNotConfiguredError("Google OAuth client file not found")
        ),
    )
    response = api_client.post("/api/accounts/connect-gmail")
    assert response.status_code == 400
    assert "Google OAuth client file not found" in response.json()["detail"]


def test_connect_gmail_modify_endpoint_stores_modify_scope(api_client, monkeypatch):
    monkeypatch.setattr(
        "app.api.routes.connect_gmail_modify_account",
        lambda **_: {
            "id": 99,
            "email_address": "owner@example.com",
            "enabled": True,
            "provider": "gmail_readonly",
            "last_sync_at": None,
            "oauth_scopes": [GMAIL_MODIFY_SCOPE],
        },
    )
    response = api_client.post("/api/accounts/connect-gmail-modify")
    assert response.status_code == 200
    payload = response.json()["account"]
    assert payload["email_address"] == "owner@example.com"
    assert payload["oauth_scopes"] == [GMAIL_MODIFY_SCOPE]


def test_sync_imports_gmail_readonly_account_without_writes(isolated_db, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [
            {
                "gmail_message_id": "real-1001",
                "gmail_thread_id": "thread-1001",
                "sender": "Bank Alerts <alerts@bank.example>",
                "reply_to": "alerts@bank.example",
                "recipient_to": "owner@example.com",
                "recipient_cc": "",
                "subject": "Security alert for your account",
                "received_at": "2026-05-03T12:00:00+00:00",
                "snippet": "Please review the new sign-in.",
                "body_preview": "We noticed a new sign-in to your account from a new browser.",
                "gmail_labels": ["INBOX", "UNREAD"],
                "headers": {},
                "has_attachments": 0,
            }
        ],
    )

    result = sync_unread_messages()
    queue = get_review_queue()

    assert result["synced_messages"] == 31
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    total = sum(group["count"] for group in gmail_account["groups"])
    assert total == 1
    message = next(group["messages"][0] for group in gmail_account["groups"] if group["count"] == 1)
    assert message["subject"] == "Security alert for your account"

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed, gmail_labels_json, mail_account_id, provider_message_id, provider_labels_json
            FROM messages
            WHERE gmail_message_id = 'real-1001' AND account_email = 'owner@example.com'
            """
        ).fetchone()
        mail_account = conn.execute(
            """
            SELECT id
            FROM mail_accounts
            WHERE external_account_email = 'owner@example.com'
            """
        ).fetchone()

    assert row["reviewed"] == 0
    assert json.loads(row["gmail_labels_json"]) == ["INBOX", "UNREAD"]
    assert row["mail_account_id"] == mail_account["id"]
    assert row["provider_message_id"] == "real-1001"
    assert json.loads(row["provider_labels_json"]) == ["INBOX", "UNREAD"]


def test_identical_gmail_refresh_preserves_queue_state_version(isolated_db, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    message_payload = {
        "gmail_message_id": "real-stable-1001",
        "gmail_thread_id": "thread-stable-1001",
        "sender": "Medium Daily Digest <noreply@medium.com>",
        "reply_to": "noreply@medium.com",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "How to Accurately Extract Everything from Documents Using AI",
        "received_at": "2026-06-06T14:50:00+00:00",
        "snippet": "Stories for Russel Brunton.",
        "body_preview": "Medium daily digest highlights and article recommendations.",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {"List-Unsubscribe": "<mailto:unsubscribe@medium.com>"},
        "has_attachments": 0,
    }

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [message_payload],
    )

    sync_unread_messages()
    with get_connection() as conn:
        first = conn.execute(
            """
            SELECT updated_at
            FROM messages
            WHERE gmail_message_id = 'real-stable-1001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    sync_unread_messages()
    with get_connection() as conn:
        second = conn.execute(
            """
            SELECT updated_at
            FROM messages
            WHERE gmail_message_id = 'real-stable-1001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert second["updated_at"] == first["updated_at"]

    changed_payload = {**message_payload, "subject": "Updated Medium digest title"}
    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [changed_payload],
    )

    sync_unread_messages()
    with get_connection() as conn:
        changed = conn.execute(
            """
            SELECT updated_at
            FROM messages
            WHERE gmail_message_id = 'real-stable-1001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert changed["updated_at"] != first["updated_at"]


def test_sync_reconciles_messages_removed_from_unread_inbox(isolated_db, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [
            {
                "gmail_message_id": "real-2001",
                "gmail_thread_id": "thread-2001",
                "sender": "Bank Alerts <alerts@bank.example>",
                "reply_to": "alerts@bank.example",
                "recipient_to": "owner@example.com",
                "recipient_cc": "",
                "subject": "Security alert for your account",
                "received_at": "2026-05-03T12:00:00+00:00",
                "snippet": "Please review the new sign-in.",
                "body_preview": "We noticed a new sign-in to your account from a new browser.",
                "gmail_labels": ["INBOX", "UNREAD"],
                "headers": {},
                "has_attachments": 0,
            }
        ],
    )

    first_result = sync_unread_messages()
    assert first_result["reconciled_messages"] == 0

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [],
    )

    second_result = sync_unread_messages()
    assert second_result["reconciled_messages"] == 1

    queue = get_review_queue()
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    assert sum(group["count"] for group in gmail_account["groups"]) == 0

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed
            FROM messages
            WHERE gmail_message_id = 'real-2001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert row["reviewed"] == 1


def test_sync_reopens_gmail_message_if_it_returns_to_unread_inbox(isolated_db, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    message_payload = {
        "gmail_message_id": "real-3001",
        "gmail_thread_id": "thread-3001",
        "sender": "Bank Alerts <alerts@bank.example>",
        "reply_to": "alerts@bank.example",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "Security alert for your account",
        "received_at": "2026-05-03T12:00:00+00:00",
        "snippet": "Please review the new sign-in.",
        "body_preview": "We noticed a new sign-in to your account from a new browser.",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {},
        "has_attachments": 0,
    }

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [message_payload],
    )
    sync_unread_messages()

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [],
    )
    sync_unread_messages()

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [message_payload],
    )
    sync_unread_messages()

    queue = get_review_queue()
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    assert sum(group["count"] for group in gmail_account["groups"]) == 1

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed
            FROM messages
            WHERE gmail_message_id = 'real-3001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert row["reviewed"] == 0


def test_manual_keep_on_gmail_message_stays_reviewed_after_refresh(isolated_db, monkeypatch):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    message_payload = {
        "gmail_message_id": "real-4001",
        "gmail_thread_id": "thread-4001",
        "sender": "Security Alerts <alerts@example.net>",
        "reply_to": "alerts@example.net",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "Security alert for your account",
        "received_at": "2026-05-03T12:00:00+00:00",
        "snippet": "Please review the new sign-in.",
        "body_preview": "We noticed a new sign-in to your account from a new browser.",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {},
        "has_attachments": 0,
    }

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [message_payload],
    )

    sync_unread_messages()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id
            FROM messages
            WHERE gmail_message_id = 'real-4001' AND account_email = 'owner@example.com'
            """
        ).fetchone()
    assert row is not None

    apply_message_action(int(row["id"]), "keep")

    queue = get_review_queue()
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    assert sum(group["count"] for group in gmail_account["groups"]) == 0

    sync_unread_messages()

    queue = get_review_queue()
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    assert sum(group["count"] for group in gmail_account["groups"]) == 0

    with get_connection() as conn:
        refreshed = conn.execute(
            """
            SELECT reviewed, current_category
            FROM messages
            WHERE gmail_message_id = 'real-4001' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert refreshed["reviewed"] == 1
    assert refreshed["current_category"] == "keep"


def test_manual_keep_on_bulk_classified_gmail_message_stays_reviewed_after_refresh(
    isolated_db, monkeypatch
):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps(["gmail.readonly"]), now, now),
        )

    message_payload = {
        "gmail_message_id": "real-4002",
        "gmail_thread_id": "thread-4002",
        "sender": "Store Deals <customers@ev.edenfantasys.com>",
        "reply_to": "customers@ev.edenfantasys.com",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "The Gift She Really Wants",
        "received_at": "2026-05-10T15:21:17+00:00",
        "snippet": "Special offer inside.",
        "body_preview": "Limited time offer with product picks, shop now links, and subscriber updates.",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {"List-Unsubscribe": "<mailto:unsubscribe@example.com>"},
        "has_attachments": 0,
    }

    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_path, max_results: [message_payload],
    )

    sync_unread_messages()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, current_category
            FROM messages
            WHERE gmail_message_id = 'real-4002' AND account_email = 'owner@example.com'
            """
        ).fetchone()
    assert row is not None
    assert row["current_category"] == "bulk_mail"

    apply_message_action(int(row["id"]), "keep")
    sync_unread_messages()

    queue = get_review_queue()
    gmail_account = next(
        account for account in queue["accounts"] if account["account_email"] == "owner@example.com"
    )
    assert sum(group["count"] for group in gmail_account["groups"]) == 0

    with get_connection() as conn:
        refreshed = conn.execute(
            """
            SELECT reviewed, current_category
            FROM messages
            WHERE gmail_message_id = 'real-4002' AND account_email = 'owner@example.com'
            """
        ).fetchone()

    assert refreshed["reviewed"] == 1
    assert refreshed["current_category"] == "keep"
