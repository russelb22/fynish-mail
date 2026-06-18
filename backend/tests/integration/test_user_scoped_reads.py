from __future__ import annotations

from app.core import config
from app.db.runtime import execute_sql, get_connection, insert_and_return_id


def _seed_two_user_state():
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
                :user_id, 'gmail_readonly', 'owner-mail@example.com', 'owner-mail@example.com',
                1, 'active', '2026-05-14T10:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
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
                :user_id, 'gmail_readonly', 'friend-mail@example.com', 'friend-mail@example.com',
                1, 'active', '2026-05-14T11:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"user_id": friend_user_id},
        )

        execute_sql(
            conn,
            """
            INSERT INTO accounts (email_address, enabled, provider, last_sync_at, created_at, updated_at)
            VALUES
              ('owner-mail@example.com', 1, 'gmail_readonly', '2026-05-14T10:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
              ('friend-mail@example.com', 1, 'gmail_readonly', '2026-05-14T11:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        )

        owner_message_id = insert_and_return_id(
            conn,
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, provider_labels_json, headers_json,
                has_attachments, current_category, confidence, protected, reviewed,
                recovery_pending, created_at, updated_at
            ) VALUES (
                'owner-msg', 'owner-thread', 'owner-mail@example.com', :mail_account_id,
                'owner-msg', 'owner-thread', 'alerts@example.com', 'example.com',
                NULL, NULL, NULL, 'Owner subject', '2026-05-14T09:00:00+00:00', 'Owner snippet',
                'Owner body preview', '[]', '[]', '{}',
                0, 'needs_review', 0.92, 0, 0,
                0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"mail_account_id": owner_mail_account_id},
        )
        friend_message_id = insert_and_return_id(
            conn,
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, provider_labels_json, headers_json,
                has_attachments, current_category, confidence, protected, reviewed,
                recovery_pending, created_at, updated_at
            ) VALUES (
                'friend-msg', 'friend-thread', 'friend-mail@example.com', :mail_account_id,
                'friend-msg', 'friend-thread', 'offers@example.com', 'example.com',
                NULL, NULL, NULL, 'Friend subject', '2026-05-14T08:30:00+00:00', 'Friend snippet',
                'Friend body preview', '[]', '[]', '{}',
                0, 'bulk_mail', 0.88, 0, 0,
                0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"mail_account_id": friend_mail_account_id},
        )

        execute_sql(
            conn,
            """
            INSERT INTO classification_results (
                message_id, category, confidence, reasons_json, protected,
                protection_reasons_json, created_at
            ) VALUES
              (:owner_message_id, 'needs_review', 0.92, '[]', 0, '[]', CURRENT_TIMESTAMP),
              (:friend_message_id, 'bulk_mail', 0.88, '[]', 0, '[]', CURRENT_TIMESTAMP)
            """,
            {
                "owner_message_id": owner_message_id,
                "friend_message_id": friend_message_id,
            },
        )

        execute_sql(
            conn,
            """
            INSERT INTO rules (
                user_id, mail_account_id, scope, account_email, rule_type, pattern,
                action, enabled, created_at, updated_at
            ) VALUES
              (:owner_user_id, :owner_mail_account_id, 'account', 'owner-mail@example.com', 'domain', 'owner.example.com', 'keep', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
              (:friend_user_id, :friend_mail_account_id, 'account', 'friend-mail@example.com', 'domain', 'friend.example.com', 'junk_review', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {
                "owner_user_id": owner_user_id,
                "owner_mail_account_id": owner_mail_account_id,
                "friend_user_id": friend_user_id,
                "friend_mail_account_id": friend_mail_account_id,
            },
        )

        execute_sql(
            conn,
            """
            INSERT INTO actions_log (
                gmail_message_id, account_email, message_id, mail_account_id, provider_message_id,
                selected_action, recommended_action, user_overrode,
                gmail_labels_added_json, gmail_labels_removed_json,
                provider_labels_added_json, provider_labels_removed_json,
                created_at
            ) VALUES
              ('owner-msg', 'owner-mail@example.com', :owner_message_id, :owner_mail_account_id, 'owner-msg', 'keep', 'keep', 0, '[]', '[]', '[]', '[]', CURRENT_TIMESTAMP),
              ('friend-msg', 'friend-mail@example.com', :friend_message_id, :friend_mail_account_id, 'friend-msg', 'trash', 'bulk_mail', 1, '[]', '[]', '[]', '[]', CURRENT_TIMESTAMP)
            """,
            {
                "owner_message_id": owner_message_id,
                "owner_mail_account_id": owner_mail_account_id,
                "friend_message_id": friend_message_id,
                "friend_mail_account_id": friend_mail_account_id,
            },
        )

        execute_sql(
            conn,
            """
            INSERT INTO notification_settings_by_user (
                user_id, enabled, recipient_email, timezone, morning_enabled,
                morning_time, evening_enabled, evening_time, send_only_if_queue_nonempty,
                created_at, updated_at
            ) VALUES
              (:owner_user_id, 1, 'owner@example.com', 'America/Los_Angeles', 1, '08:00', 1, '16:00', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP),
              (:friend_user_id, 1, 'friend@example.com', 'America/New_York', 1, '09:00', 0, '17:00', 0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
            {
                "owner_user_id": owner_user_id,
                "friend_user_id": friend_user_id,
            },
        )


def test_user_scoped_reads_only_return_owned_data(api_client, empty_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    _seed_two_user_state()

    owner_headers = {
        "X-Fynish-Authenticated-Email": "owner@example.com",
        "X-Fynish-Authenticated-Name": "Owner User",
    }
    friend_headers = {
        "X-Fynish-Authenticated-Email": "friend@example.com",
        "X-Fynish-Authenticated-Name": "Friend User",
    }

    owner_accounts = api_client.get("/api/accounts", headers=owner_headers)
    friend_accounts = api_client.get("/api/accounts", headers=friend_headers)
    assert [row["email_address"] for row in owner_accounts.json()["accounts"]] == [
        "owner-mail@example.com"
    ]
    assert [row["email_address"] for row in friend_accounts.json()["accounts"]] == [
        "friend-mail@example.com"
    ]

    owner_rules = api_client.get("/api/rules", headers=owner_headers)
    friend_rules = api_client.get("/api/rules", headers=friend_headers)
    assert [rule["pattern"] for rule in owner_rules.json()["rules"]] == ["owner.example.com"]
    assert [rule["pattern"] for rule in friend_rules.json()["rules"]] == ["friend.example.com"]

    owner_queue = api_client.get("/api/review-queue", headers=owner_headers)
    friend_queue = api_client.get("/api/review-queue", headers=friend_headers)
    assert [account["account_email"] for account in owner_queue.json()["accounts"]] == [
        "owner-mail@example.com"
    ]
    assert [account["account_email"] for account in friend_queue.json()["accounts"]] == [
        "friend-mail@example.com"
    ]

    owner_processed = api_client.get("/api/messages/processed", headers=owner_headers)
    friend_processed = api_client.get("/api/messages/processed", headers=friend_headers)
    assert [message["subject"] for message in owner_processed.json()["messages"]] == [
        "Owner subject"
    ]
    assert [message["subject"] for message in friend_processed.json()["messages"]] == [
        "Friend subject"
    ]

    owner_reminders = api_client.get("/api/reminders/summary", headers=owner_headers)
    friend_reminders = api_client.get("/api/reminders/summary", headers=friend_headers)
    assert [account["account_email"] for account in owner_reminders.json()["accounts"]] == [
        "owner-mail@example.com"
    ]
    assert [account["account_email"] for account in friend_reminders.json()["accounts"]] == [
        "friend-mail@example.com"
    ]

    owner_settings = api_client.get("/api/settings/notifications", headers=owner_headers)
    friend_settings = api_client.get("/api/settings/notifications", headers=friend_headers)
    assert owner_settings.json()["settings"]["recipient_email"] == "owner@example.com"
    assert friend_settings.json()["settings"]["recipient_email"] == "friend@example.com"
