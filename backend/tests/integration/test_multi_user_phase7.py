from __future__ import annotations

from app.db.runtime import fetch_all, get_connection, insert_and_return_id
from app.services import auto_sync, review_queue
from app.services.review_queue import get_review_queue, sync_unread_messages
from app.services.rules import create_rule


def _seed_two_users_with_mock_accounts() -> dict[str, int]:
    with get_connection() as conn:
        owner_user_id = insert_and_return_id(
            conn,
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES ('owner@example.com', 'Owner User', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        )
        friend_user_id = insert_and_return_id(
            conn,
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES ('friend@example.com', 'Friend User', 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        )

        owner_mail_account_id = insert_and_return_id(
            conn,
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (
                :user_id, 'mock_gmail', 'owner-mail@example.com', 'Owner Mail',
                1, 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"user_id": owner_user_id},
        )
        friend_mail_account_id = insert_and_return_id(
            conn,
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (
                :user_id, 'mock_gmail', 'friend-mail@example.com', 'Friend Mail',
                1, 'active', NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"user_id": friend_user_id},
        )

    return {
        "owner_user_id": owner_user_id,
        "friend_user_id": friend_user_id,
        "owner_mail_account_id": owner_mail_account_id,
        "friend_mail_account_id": friend_mail_account_id,
    }


def _message_payload(
    *,
    gmail_message_id: str,
    account_email: str,
    sender: str,
    subject: str,
) -> dict:
    return {
        "gmail_message_id": gmail_message_id,
        "gmail_thread_id": f"{gmail_message_id}-thread",
        "sender": sender,
        "reply_to": "",
        "recipient_to": account_email,
        "recipient_cc": "",
        "subject": subject,
        "received_at": "2026-05-15T08:00:00+00:00",
        "snippet": f"Snippet for {subject}",
        "body_preview": f"Body preview for {subject}",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {},
        "has_attachments": 0,
    }


def test_user_rules_only_affect_their_own_sync_results(empty_db, monkeypatch):
    seeded = _seed_two_users_with_mock_accounts()

    create_rule(
        {
            "scope": "account",
            "account_email": "owner-mail@example.com",
            "rule_type": "domain",
            "pattern": "updates.shared-example.com",
            "action": "keep",
        },
        user_id=seeded["owner_user_id"],
    )
    create_rule(
        {
            "scope": "account",
            "account_email": "friend-mail@example.com",
            "rule_type": "domain",
            "pattern": "updates.shared-example.com",
            "action": "junk_review",
        },
        user_id=seeded["friend_user_id"],
    )

    monkeypatch.setattr(
        review_queue,
        "get_mock_messages",
        lambda account_email: [
            _message_payload(
                gmail_message_id=f"{account_email}-msg-1",
                account_email=account_email,
                sender="Shared Sender <alerts@updates.shared-example.com>",
                subject=f"Update for {account_email}",
            )
        ],
    )

    owner_result = sync_unread_messages(user_id=seeded["owner_user_id"])
    friend_result = sync_unread_messages(user_id=seeded["friend_user_id"])

    assert owner_result["synced_messages"] == 1
    assert friend_result["synced_messages"] == 1

    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT account_email, reviewed, current_category
            FROM messages
            WHERE account_email IN ('owner-mail@example.com', 'friend-mail@example.com')
            ORDER BY account_email ASC
            """,
        )
        actions = fetch_all(
            conn,
            """
            SELECT account_email, selected_action
            FROM actions_log
            WHERE account_email IN ('owner-mail@example.com', 'friend-mail@example.com')
            ORDER BY account_email ASC
            """,
        )

    assert [dict(row) for row in rows] == [
        {
            "account_email": "friend-mail@example.com",
            "reviewed": 1,
            "current_category": "junk_review",
        },
        {
            "account_email": "owner-mail@example.com",
            "reviewed": 0,
            "current_category": "keep",
        },
    ]
    assert [dict(row) for row in actions] == [
        {"account_email": "friend-mail@example.com", "selected_action": "junk_review"},
    ]


def test_scheduler_style_sync_keeps_user_queues_isolated(empty_db, monkeypatch):
    seeded = _seed_two_users_with_mock_accounts()

    monkeypatch.setattr(
        review_queue,
        "get_mock_messages",
        lambda account_email: [
            _message_payload(
                gmail_message_id=f"{account_email}-msg-1",
                account_email=account_email,
                sender=(
                    "Owner Sender <owner@owner.example.com>"
                    if account_email == "owner-mail@example.com"
                    else "Friend Sender <friend@friend.example.com>"
                ),
                subject=(
                    "Owner queue message"
                    if account_email == "owner-mail@example.com"
                    else "Friend queue message"
                ),
            )
        ],
    )

    result = auto_sync._run_user_scoped_syncs()

    assert result["users_processed"] == 2
    assert result["synced_messages"] == 2
    assert result["reconciled_messages"] == 0
    assert result["auto_applied_messages"] == 0

    owner_queue = get_review_queue(user_id=seeded["owner_user_id"])
    friend_queue = get_review_queue(user_id=seeded["friend_user_id"])

    owner_subjects = {
        message["subject"]
        for account in owner_queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    friend_subjects = {
        message["subject"]
        for account in friend_queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }

    assert owner_subjects == {"Owner queue message"}
    assert friend_subjects == {"Friend queue message"}
