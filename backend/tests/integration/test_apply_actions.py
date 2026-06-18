from __future__ import annotations

import json

from app.db.database import get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.review_queue import (
    UnsafeMessageActionError,
    apply_message_action,
    apply_selected_actions,
    get_review_queue,
)


def _message_id_by_subject(subject: str) -> int:
    with get_connection() as conn:
        row = conn.execute(
            "SELECT id FROM messages WHERE subject = ?",
            (subject,),
        ).fetchone()
    return int(row["id"])


def test_bulk_action_logs_labels_and_removes_message_from_queue(seeded_db):
    message_id = _message_id_by_subject("Your daily digest")
    result = apply_message_action(message_id, "bulk_mail")
    assert result["labels_added"] == ["Fynish/Bulk Mail"]
    assert result["labels_removed"] == ["INBOX"]

    queue = get_review_queue()
    subjects = {
        message["subject"]
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    assert "Your daily digest" not in subjects

    with get_connection() as conn:
        log_row = conn.execute(
            """
            SELECT
                selected_action,
                message_id,
                mail_account_id,
                provider_message_id,
                gmail_labels_added_json,
                gmail_labels_removed_json,
                provider_labels_added_json,
                provider_labels_removed_json
            FROM actions_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert log_row["selected_action"] == "bulk_mail"
    assert log_row["message_id"] == message_id
    assert log_row["mail_account_id"] is not None
    assert log_row["provider_message_id"] is not None
    assert json.loads(log_row["gmail_labels_removed_json"]) == ["INBOX"]
    assert json.loads(log_row["provider_labels_removed_json"]) == ["INBOX"]


def test_keep_action_removes_from_queue_without_inbox_removal(seeded_db):
    message_id = _message_id_by_subject("Photos from Sunday dinner")
    result = apply_message_action(message_id, "keep")
    assert result["labels_added"] == []
    assert result["labels_removed"] == []

    with get_connection() as conn:
        log_row = conn.execute(
            """
            SELECT message_id, provider_message_id, provider_labels_added_json, provider_labels_removed_json
            FROM actions_log
            ORDER BY id DESC
            LIMIT 1
            """
        ).fetchone()
    assert log_row["message_id"] == message_id
    assert log_row["provider_message_id"] is not None
    assert json.loads(log_row["provider_labels_added_json"]) == []
    assert json.loads(log_row["provider_labels_removed_json"]) == []


def test_apply_selected_reports_missing_messages_without_failing_batch(seeded_db):
    message_id = _message_id_by_subject("Your daily digest")

    result = apply_selected_actions(
        [
            {"message_id": message_id, "action": "bulk_mail"},
            {"message_id": 999999, "action": "trash"},
        ]
    )

    assert result["applied_count"] == 1
    assert result["failed_count"] == 1
    assert result["applied"][0]["message_id"] == message_id
    assert result["failed"] == [
        {
            "message_id": 999999,
            "action": "trash",
            "reason": "Message is no longer available.",
        }
    ]


def test_apply_selected_reports_known_apply_errors_without_failing_batch(
    seeded_db,
    monkeypatch,
):
    message_id = _message_id_by_subject("Your daily digest")

    def fake_apply_message_action(message_id, action, user_id=None):
        if action == "trash":
            raise GmailReadonlySyncError("Stored Gmail credentials were expired or revoked.")
        return {"message_id": message_id, "selected_action": action}

    monkeypatch.setattr(
        "app.services.review_queue.apply_message_action",
        fake_apply_message_action,
    )

    result = apply_selected_actions(
        [
            {"message_id": message_id, "action": "bulk_mail"},
            {"message_id": message_id + 1, "action": "trash"},
        ]
    )

    assert result["applied_count"] == 1
    assert result["failed_count"] == 1
    assert result["applied"] == [{"message_id": message_id, "selected_action": "bulk_mail"}]
    assert result["failed"] == [
        {
            "message_id": message_id + 1,
            "action": "trash",
            "reason": "Stored Gmail credentials were expired or revoked.",
        }
    ]


def test_single_action_endpoint_reports_unsafe_action_code(
    api_client,
    seeded_db,
    monkeypatch,
):
    def fail_apply_message_action(*args, **kwargs):
        raise UnsafeMessageActionError("Unsafe Gmail action plan for message 1")

    monkeypatch.setattr("app.api.routes.apply_message_action", fail_apply_message_action)

    response = api_client.post("/api/messages/1/action", json={"action": "trash"})

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Unsafe Gmail action plan for message 1",
        "code": "unsafe_message_action",
    }
