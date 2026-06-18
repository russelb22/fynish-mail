from __future__ import annotations

from app.db.database import get_connection
from app.services.review_queue import get_review_queue, sync_unread_messages


def test_sync_populates_queue_for_all_accounts(isolated_db):
    result = sync_unread_messages()
    queue = get_review_queue()
    assert result["synced_messages"] == 30
    assert len(queue["accounts"]) == 3
    assert sum(group["count"] for account in queue["accounts"] for group in account["groups"]) == 30

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE mail_account_id IS NULL
               OR provider_message_id IS NULL
               OR provider_labels_json IS NULL
            """
        ).fetchone()
    assert row["count"] == 0


def test_repeat_sync_does_not_duplicate_messages(isolated_db):
    sync_unread_messages()
    sync_unread_messages()
    with get_connection() as conn:
        row = conn.execute("SELECT COUNT(*) AS count FROM messages").fetchone()
    assert row["count"] == 30
