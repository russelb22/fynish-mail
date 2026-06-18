from __future__ import annotations

from app.core import config
from app.db.runtime import execute_sql, fetch_one, get_connection, insert_and_return_id


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

        owner_account_id = insert_and_return_id(
            conn,
            """
            INSERT INTO accounts (email_address, enabled, provider, last_sync_at, created_at, updated_at)
            VALUES ('owner-mail@example.com', 1, 'gmail_readonly', '2026-05-14T10:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
            """,
        )
        friend_account_id = insert_and_return_id(
            conn,
            """
            INSERT INTO accounts (email_address, enabled, provider, last_sync_at, created_at, updated_at)
            VALUES ('friend-mail@example.com', 1, 'gmail_readonly', '2026-05-14T11:00:00+00:00', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
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
                'Owner body preview', '[\"INBOX\",\"UNREAD\"]', '[\"INBOX\",\"UNREAD\"]', '{}',
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
                'Friend body preview', '[\"INBOX\",\"UNREAD\"]', '[\"INBOX\",\"UNREAD\"]', '{}',
                0, 'bulk_mail', 0.88, 0, 0,
                0, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"mail_account_id": friend_mail_account_id},
        )

        owner_rule_id = insert_and_return_id(
            conn,
            """
            INSERT INTO rules (
                user_id, mail_account_id, scope, account_email, rule_type, pattern,
                action, enabled, created_at, updated_at
            ) VALUES (
                :user_id, :mail_account_id, 'account', 'owner-mail@example.com', 'domain', 'owner.example.com',
                'keep', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"user_id": owner_user_id, "mail_account_id": owner_mail_account_id},
        )
        friend_rule_id = insert_and_return_id(
            conn,
            """
            INSERT INTO rules (
                user_id, mail_account_id, scope, account_email, rule_type, pattern,
                action, enabled, created_at, updated_at
            ) VALUES (
                :user_id, :mail_account_id, 'account', 'friend-mail@example.com', 'domain', 'friend.example.com',
                'junk_review', 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            )
            """,
            {"user_id": friend_user_id, "mail_account_id": friend_mail_account_id},
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

    return {
        "owner_account_id": owner_account_id,
        "friend_account_id": friend_account_id,
        "owner_message_id": owner_message_id,
        "friend_message_id": friend_message_id,
        "owner_rule_id": owner_rule_id,
        "friend_rule_id": friend_rule_id,
    }


def test_user_scoped_mutations_block_foreign_resources(api_client, empty_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    seeded = _seed_two_user_state()

    owner_headers = {
        "X-Fynish-Authenticated-Email": "owner@example.com",
        "X-Fynish-Authenticated-Name": "Owner User",
    }

    response = api_client.post(
        f"/api/messages/{seeded['friend_message_id']}/action",
        json={"action": "keep"},
        headers=owner_headers,
    )
    assert response.status_code == 404

    response = api_client.post(
        f"/api/messages/{seeded['friend_message_id']}/recover",
        headers=owner_headers,
    )
    assert response.status_code == 404

    response = api_client.patch(
        f"/api/rules/{seeded['friend_rule_id']}",
        json={"enabled": False},
        headers=owner_headers,
    )
    assert response.status_code == 404

    response = api_client.delete(
        f"/api/rules/{seeded['friend_rule_id']}",
        headers=owner_headers,
    )
    assert response.status_code == 404

    response = api_client.post(
        f"/api/accounts/{seeded['friend_account_id']}/disable",
        headers=owner_headers,
    )
    assert response.status_code == 404

    response = api_client.post(
        f"/api/accounts/{seeded['friend_account_id']}/enable",
        headers=owner_headers,
    )
    assert response.status_code == 404


def test_notification_settings_update_is_user_scoped(api_client, empty_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    _seed_two_user_state()

    owner_headers = {
        "X-Fynish-Authenticated-Email": "owner@example.com",
        "X-Fynish-Authenticated-Name": "Owner User",
    }

    response = api_client.patch(
        "/api/settings/notifications",
        json={"recipient_email": "owner+updated@example.com"},
        headers=owner_headers,
    )
    assert response.status_code == 200
    assert response.json()["settings"]["recipient_email"] == "owner+updated@example.com"

    with get_connection() as conn:
        owner_row = fetch_one(
            conn,
            """
            SELECT recipient_email
            FROM notification_settings_by_user ns
            JOIN users u ON u.id = ns.user_id
            WHERE u.email = 'owner@example.com'
            """,
        )
        friend_row = fetch_one(
            conn,
            """
            SELECT recipient_email
            FROM notification_settings_by_user ns
            JOIN users u ON u.id = ns.user_id
            WHERE u.email = 'friend@example.com'
            """,
        )

    assert owner_row["recipient_email"] == "owner+updated@example.com"
    assert friend_row["recipient_email"] == "friend@example.com"


def test_rule_creation_cannot_target_foreign_account(api_client, empty_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    _seed_two_user_state()

    owner_headers = {
        "X-Fynish-Authenticated-Email": "owner@example.com",
        "X-Fynish-Authenticated-Name": "Owner User",
    }

    response = api_client.post(
        "/api/rules",
        json={
            "scope": "account",
            "account_email": "friend-mail@example.com",
            "rule_type": "domain",
            "pattern": "friend.example.com",
            "action": "junk_review",
        },
        headers=owner_headers,
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Account is not available to the current user.",
        "code": "rule_account_unavailable",
    }
