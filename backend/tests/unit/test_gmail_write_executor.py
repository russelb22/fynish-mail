from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import GMAIL_MODIFY_SCOPE
from app.db.database import get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.gmail_write_executor import (
    GmailExecutionResult,
    execute_message_action,
    execute_selected_message_actions,
    log_executed_message_action,
)


def _insert_gmail_account_and_message(scopes: list[str]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        account_id = cursor.lastrowid
        conn.execute(
            """
            INSERT INTO gmail_account_connections (
                account_id, token_path, scopes_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?)
            """,
            (account_id, "/tmp/fake-token.json", json.dumps(scopes), now, now),
        )
        message_cursor = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, headers_json, has_attachments,
                current_category, confidence, protected, reviewed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "real-1",
                "thread-1",
                "owner@example.com",
                "Sender <sender@example.com>",
                "example.com",
                "",
                "owner@example.com",
                "",
                "Promo mail",
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


def _insert_normalized_gmail_account_and_message(scopes: list[str]) -> int:
    now = datetime.now(timezone.utc).isoformat()
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
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, ?, ?, '{}', ?, ?)
            """,
            (mail_account_id, "/tmp/fake-token.json", json.dumps(scopes), now, now),
        )
        message_cursor = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, provider_labels_json, headers_json,
                has_attachments, current_category, confidence, protected, reviewed,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "real-1",
                "thread-1",
                "owner@example.com",
                mail_account_id,
                "real-1",
                "thread-1",
                "Sender <sender@example.com>",
                "example.com",
                "",
                "owner@example.com",
                "",
                "Promo mail",
                now,
                "Snippet",
                "Preview",
                json.dumps(["UNREAD", "INBOX"]),
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


def _insert_second_gmail_message_for_owner() -> int:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        message_cursor = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, headers_json, has_attachments,
                current_category, confidence, protected, reviewed, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "real-2",
                "thread-2",
                "owner@example.com",
                "Sender <sender@example.com>",
                "example.com",
                "",
                "owner@example.com",
                "",
                "Second promo mail",
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


def test_execute_message_action_blocks_without_modify_scope(isolated_db):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.readonly"]
    )
    result = execute_message_action(message_id, "bulk_mail", allow_live_writes=True)

    assert result is not None
    assert result.executed is False
    assert result.oauth_scope_ready is False
    assert any("gmail.modify" in note for note in result.notes)


def test_execute_message_action_accepts_db_backed_token_without_token_path(
    isolated_db, monkeypatch
):
    message_id = _insert_normalized_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE provider_connections
            SET token_path = NULL,
                metadata_json = ?
            WHERE mail_account_id = (
                SELECT mail_account_id
                FROM messages
                WHERE id = ?
            )
            """,
            (json.dumps({"gmail_authorized_user_json": '{"refresh_token":"abc"}'}), message_id),
        )

    monkeypatch.setattr(
        "app.services.gmail_write_executor.get_mail_provider_adapter",
        lambda provider: type(
            "_Adapter",
            (),
            {
                "modify_message_labels": staticmethod(
                    lambda **kwargs: ["UNREAD", "Fynish/Trash"]
                )
            },
        )(),
    )

    result = execute_message_action(
        message_id,
        "trash",
        allow_live_writes=True,
        require_feature_flag=False,
        user_id=1,
    )

    assert result is not None
    assert result.executed is True
    assert result.oauth_scope_ready is True
    assert "Fynish/Trash" in result.response_label_ids


def test_execute_message_action_blocks_when_feature_flag_disabled(isolated_db):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    result = execute_message_action(message_id, "bulk_mail", allow_live_writes=False)

    assert result is not None
    assert result.executed is False
    assert result.live_writes_enabled is False
    assert any("disabled" in note for note in result.notes)


def test_list_accounts_exposes_modify_scope(isolated_db):
    from app.services.accounts import list_accounts

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
            (cursor.lastrowid, "/tmp/fake-token.json", json.dumps([GMAIL_MODIFY_SCOPE]), now, now),
        )

    accounts = list_accounts()
    gmail_account = next(account for account in accounts if account["email_address"] == "owner@example.com")
    assert gmail_account["oauth_scopes"] == [GMAIL_MODIFY_SCOPE]


def test_execute_keep_action_short_circuits_without_gmail_modify(isolated_db):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.readonly"]
    )
    result = execute_message_action(message_id, "keep", allow_live_writes=True)

    assert result is not None
    assert result.executed is True
    assert result.labels_added == []
    assert result.labels_removed == []
    assert any("No Gmail label mutation" in note for note in result.notes)


def test_log_executed_message_action_writes_provider_neutral_audit_fields(isolated_db):
    message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    result = GmailExecutionResult(
        message_id=message_id,
        gmail_message_id="real-1",
        account_email="owner@example.com",
        selected_action="bulk_mail",
        status="executed",
        executed=True,
        allowed=True,
        live_writes_enabled=True,
        oauth_scope_ready=True,
        labels_added=["Fynish/Bulk Mail"],
        labels_removed=["INBOX"],
        response_label_ids=["UNREAD", "Fynish/Bulk Mail"],
        notes=[],
    )

    log_executed_message_action(result)

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT
                message_id,
                mail_account_id,
                provider_message_id,
                provider_labels_added_json,
                provider_labels_removed_json,
                gmail_labels_added_json,
                gmail_labels_removed_json
            FROM actions_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()

    assert row["message_id"] == message_id
    assert row["mail_account_id"] is not None
    assert row["provider_message_id"] == "real-1"
    assert json.loads(row["provider_labels_added_json"]) == ["Fynish/Bulk Mail"]
    assert json.loads(row["provider_labels_removed_json"]) == ["INBOX"]
    assert json.loads(row["gmail_labels_added_json"]) == ["Fynish/Bulk Mail"]
    assert json.loads(row["gmail_labels_removed_json"]) == ["INBOX"]


def test_execute_message_action_uses_normalized_provider_connection_without_legacy_rows(isolated_db):
    message_id = _insert_normalized_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.readonly"]
    )

    result = execute_message_action(message_id, "bulk_mail", allow_live_writes=True)

    assert result is not None
    assert result.executed is False
    assert result.allowed is True
    assert result.oauth_scope_ready is False
    assert any("gmail.modify" in note for note in result.notes)


def test_execute_selected_message_actions_keeps_processing_after_gmail_failure(
    isolated_db,
    monkeypatch,
):
    first_message_id = _insert_gmail_account_and_message(
        ["https://www.googleapis.com/auth/gmail.modify"]
    )
    second_message_id = _insert_second_gmail_message_for_owner()

    def fake_execute_plan(plan, **kwargs):
        if plan.message_id == first_message_id:
            raise GmailReadonlySyncError(
                "Stored Gmail credentials were expired or revoked. Reconnect the account."
            )
        return GmailExecutionResult(
            message_id=plan.message_id,
            gmail_message_id=plan.gmail_message_id,
            account_email=plan.account_email,
            selected_action=plan.selected_action,
            status="executed",
            executed=True,
            allowed=True,
            live_writes_enabled=True,
            oauth_scope_ready=True,
            labels_added=plan.labels_to_add,
            labels_removed=plan.labels_to_remove,
            response_label_ids=["UNREAD", "Fynish/Trash"],
            notes=["Gmail label modify call executed successfully"],
        )

    monkeypatch.setattr(
        "app.services.gmail_write_executor.execute_gmail_action_plan",
        fake_execute_plan,
    )

    response = execute_selected_message_actions(
        [
            {"message_id": first_message_id, "action": "bulk_mail"},
            {"message_id": second_message_id, "action": "trash"},
        ],
        allow_live_writes=True,
        require_feature_flag=False,
    )

    assert response["executed"] == 1
    assert response["blocked"] == 0
    assert response["failed"] == 1
    assert [result["status"] for result in response["results"]] == ["failed", "executed"]
    assert "Reconnect the account" in response["results"][0]["notes"][-1]

    with get_connection() as conn:
        logged_actions = conn.execute(
            "SELECT message_id, selected_action FROM actions_log ORDER BY id"
        ).fetchall()

    assert [(row["message_id"], row["selected_action"]) for row in logged_actions] == [
        (second_message_id, "trash")
    ]
