from __future__ import annotations

from app.db.database import get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.processed_mail import list_processed_messages
from app.services.review_queue import apply_message_action, sync_unread_messages


def test_processed_messages_include_underlying_message_id(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "keep")

    response = api_client.get("/api/messages/processed")

    assert response.status_code == 200
    payload = response.json()["messages"]
    assert payload[0]["message_id"] == 1


def test_recover_processed_message_returns_message_to_review_queue(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "trash")

    response = api_client.post("/api/messages/1/recover")

    assert response.status_code == 200
    payload = response.json()
    assert payload["message_id"] == 1
    assert payload["selected_action"] == "recover"
    assert payload["current_category"] == "needs_review"

    with get_connection() as conn:
        message_row = conn.execute(
            "SELECT reviewed, current_category, recovery_pending FROM messages WHERE id = ?",
            (1,),
        ).fetchone()
        recover_log = conn.execute(
            """
            SELECT selected_action
            FROM actions_log
            WHERE message_id = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (1,),
        ).fetchone()

    assert message_row["reviewed"] == 0
    assert message_row["current_category"] == "needs_review"
    assert message_row["recovery_pending"] == 1
    assert recover_log["selected_action"] == "recover"


def test_recover_processed_message_returns_reconnect_error_for_expired_token(
    monkeypatch,
    api_client,
    isolated_db,
):
    sync_unread_messages()
    apply_message_action(1, "trash")

    def fail_recover(*args, **kwargs):
        raise GmailReadonlySyncError(
            "Stored Gmail credentials were expired or revoked. Reconnect the account."
        )

    monkeypatch.setattr("app.api.routes.recover_processed_message", fail_recover)

    response = api_client.post("/api/messages/1/recover")

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Stored Gmail credentials were expired or revoked. Reconnect the account."
    )
    assert response.json()["code"] == "gmail_reconnect_required"


def test_recover_audit_rows_do_not_appear_in_processed_mail(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "keep")
    api_client.post("/api/messages/1/recover")

    response = api_client.get("/api/messages/processed")

    assert response.status_code == 200
    payload = response.json()["messages"]
    assert all(message["selected_action"] != "recover" for message in payload)


def test_recovered_message_stays_in_queue_even_when_missing_from_unread_sync(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "trash")
    api_client.post("/api/messages/1/recover")

    with get_connection() as conn:
        account_row = conn.execute(
            "SELECT mail_account_id, account_email FROM messages WHERE id = ?",
            (1,),
        ).fetchone()
        from app.services.review_queue import _reconcile_gmail_account_queue

        reconciled = _reconcile_gmail_account_queue(
            conn,
            int(account_row["mail_account_id"]) if account_row["mail_account_id"] is not None else account_row["account_email"],
            set(),
            "2026-05-13T20:00:00+00:00",
        )
        message_row = conn.execute(
            "SELECT reviewed, current_category, recovery_pending FROM messages WHERE id = ?",
            (1,),
        ).fetchone()

    assert reconciled >= 0
    assert message_row["reviewed"] == 0
    assert message_row["current_category"] == "needs_review"
    assert message_row["recovery_pending"] == 1

    queue_response = api_client.get("/api/review-queue")
    assert queue_response.status_code == 200
    queue_message_ids = {
        message["id"]
        for account in queue_response.json()["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    assert 1 in queue_message_ids


def test_processed_messages_work_without_legacy_account_row(isolated_db):
    with get_connection() as conn:
        user_id = conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES ('owner@example.com', 'Owner', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """
        ).lastrowid
        mail_account_id = conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'owner@example.com', 'Owner Gmail', 1, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            (user_id,),
        ).lastrowid
        message_id = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, subject, snippet,
                body_preview, gmail_labels_json, provider_labels_json, headers_json,
                has_attachments, current_category, confidence, protected, reviewed,
                created_at, updated_at
            ) VALUES (
                'processed-msg', 'processed-thread', 'owner@example.com', ?,
                'processed-msg', 'processed-thread', 'Sender <sender@example.com>',
                'Processed subject', 'Processed snippet', 'Processed body',
                '[]', '[]', '{}', 0, 'keep', 0.9, 0, 1,
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            (mail_account_id,),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO actions_log (
                gmail_message_id, account_email, message_id, mail_account_id, provider_message_id,
                selected_action, recommended_action, user_overrode,
                gmail_labels_added_json, gmail_labels_removed_json,
                provider_labels_added_json, provider_labels_removed_json,
                created_at
            ) VALUES (
                'processed-msg', 'owner@example.com', ?, ?, 'processed-msg',
                'keep', 'keep', 0, '[]', '[]', '[]', '[]', CURRENT_TIMESTAMP
            )
            """,
            (message_id, mail_account_id),
        )

    payload = list_processed_messages()
    assert any(
        message["message_id"] == message_id
        and message["account_email"] == "owner@example.com"
        and message["subject"] == "Processed subject"
        for message in payload
    )
