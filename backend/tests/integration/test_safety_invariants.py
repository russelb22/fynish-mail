from __future__ import annotations

import json

from app.db.database import get_connection
from app.services.review_queue import ACTION_TO_LABELS, get_review_queue


def test_v1_action_model_never_uses_gmail_trash_or_delete(seeded_db):
    for action, labels in ACTION_TO_LABELS.items():
        assert "TRASH" not in labels["add"]
        assert "TRASH" not in labels["remove"]
        assert action in {"keep", "bulk_mail", "junk_review", "trash", "needs_review"}


def test_needs_review_is_never_selected_by_default(seeded_db):
    queue = get_review_queue()
    for account in queue["accounts"]:
        for group in account["groups"]:
            if group["category"] != "needs_review":
                continue
            assert all(message["default_selected"] is False for message in group["messages"])


def test_action_logs_preserve_unread_by_not_removing_it(seeded_db):
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO actions_log (
                gmail_message_id, account_email, selected_action, recommended_action,
                user_overrode, gmail_labels_added_json, gmail_labels_removed_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "test-id",
                "personal@example.com",
                "bulk_mail",
                "bulk_mail",
                0,
                json.dumps(["Fynish/Bulk Mail"]),
                json.dumps(["INBOX"]),
                "2026-05-03T00:00:00Z",
            ),
        )
        row = conn.execute(
            "SELECT gmail_labels_removed_json FROM actions_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
    assert "UNREAD" not in json.loads(row["gmail_labels_removed_json"])
