from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.database import get_connection
from app.services.gmail_write_planner import (
    plan_action_for_message_row,
    plan_gmail_readonly_account_actions,
    plan_message_action,
)


def _message_row_by_subject(subject: str):
    with get_connection() as conn:
        return conn.execute(
            """
            SELECT m.*, a.provider
            FROM messages m
            JOIN accounts a ON a.email_address = m.account_email
            WHERE m.subject = ?
            """,
            (subject,),
        ).fetchone()


def test_bulk_mail_plan_preserves_unread_and_removes_inbox(seeded_db):
    row = _message_row_by_subject("Your daily digest")
    plan = plan_action_for_message_row(row, "bulk_mail")

    assert plan.allowed is True
    assert plan.labels_to_add == ["Fynish/Bulk Mail"]
    assert plan.labels_to_remove == ["INBOX"]
    assert plan.preserves_unread is True
    assert plan.will_use_trash is False
    assert plan.will_delete_permanently is False


def test_keep_plan_is_non_mutating(seeded_db):
    row = _message_row_by_subject("Photos from Sunday dinner")
    plan = plan_action_for_message_row(row, "keep")

    assert plan.allowed is True
    assert plan.will_modify_gmail is False
    assert plan.labels_to_add == []
    assert plan.labels_to_remove == []


def test_planner_supports_gmail_readonly_accounts(isolated_db):
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
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
                "Google <no-reply@accounts.google.com>",
                "accounts.google.com",
                "",
                "owner@example.com",
                "",
                "Security alert",
                now,
                "Snippet",
                "Preview",
                json.dumps(["UNREAD", "INBOX", "IMPORTANT"]),
                json.dumps({}),
                0,
                "keep",
                0.99,
                1,
                0,
                now,
                now,
            ),
        )

    plan = plan_message_action(1, "keep")
    assert plan is not None
    assert plan.provider == "gmail_readonly"
    assert "UNREAD" in plan.current_labels

    plans = plan_gmail_readonly_account_actions("owner@example.com")["plans"]
    assert len(plans) == 1
    assert plans[0]["subject"] == "Security alert"
