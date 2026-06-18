from __future__ import annotations

import json

from app.db.database import get_connection
from app.db.foundation_migration import (
    DEFAULT_LOCAL_OWNER_EMAIL,
    migrate_foundation_schema,
)
from app.db.foundation_validation import validate_foundation_migration
from app.services.review_queue import get_review_queue


def test_foundation_migration_backfills_pre_migration_fixture(
    foundation_pre_migration_db,
):
    summary = migrate_foundation_schema()

    assert summary["default_user_id"] >= 1
    assert summary["mail_accounts_total"] == 3
    assert summary["provider_connections_total"] == 2
    assert summary["messages_total"] == 4
    assert summary["rules_total"] == 3
    assert summary["actions_log_total"] == 2
    assert summary["notification_settings_by_user_total"] == 1

    with get_connection() as conn:
        user = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            (DEFAULT_LOCAL_OWNER_EMAIL,),
        ).fetchone()
        assert user is not None

        mail_accounts = conn.execute(
            """
            SELECT external_account_email, provider, user_id, enabled, status, display_name
            FROM mail_accounts
            ORDER BY external_account_email ASC
            """
        ).fetchall()
        assert [row["external_account_email"] for row in mail_accounts] == [
            "legacy-disabled@gmail.com",
            "legacy-live@gmail.com",
            "legacy-mock@example.com",
        ]
        assert all(int(row["user_id"]) == int(user["id"]) for row in mail_accounts)
        assert {
            row["external_account_email"]: row["status"] for row in mail_accounts
        } == {
            "legacy-disabled@gmail.com": "disabled",
            "legacy-live@gmail.com": "active",
            "legacy-mock@example.com": "active",
        }

        provider_connections = conn.execute(
            """
            SELECT ma.external_account_email, pc.provider, pc.token_path, pc.scopes_json
            FROM provider_connections pc
            JOIN mail_accounts ma ON ma.id = pc.mail_account_id
            ORDER BY ma.external_account_email ASC
            """
        ).fetchall()
        assert len(provider_connections) == 2
        scopes_by_account = {
            row["external_account_email"]: json.loads(row["scopes_json"])
            for row in provider_connections
        }
        assert scopes_by_account["legacy-live@gmail.com"] == [
            "https://www.googleapis.com/auth/gmail.modify"
        ]
        assert scopes_by_account["legacy-disabled@gmail.com"] == [
            "https://www.googleapis.com/auth/gmail.readonly"
        ]

        messages = conn.execute(
            """
            SELECT account_email, gmail_message_id, mail_account_id, provider_message_id,
                   provider_thread_id, provider_labels_json
            FROM messages
            ORDER BY account_email ASC, gmail_message_id ASC
            """
        ).fetchall()
        assert len(messages) == 4
        assert all(row["mail_account_id"] is not None for row in messages)
        assert all(row["provider_message_id"] == row["gmail_message_id"] for row in messages)
        assert all(row["provider_thread_id"] is not None for row in messages)
        assert all(
            isinstance(json.loads(row["provider_labels_json"]), list) for row in messages
        )

        rules = conn.execute(
            """
            SELECT account_email, user_id, mail_account_id, created_from_account,
                   created_from_mail_account_id, action, enabled
            FROM rules
            ORDER BY id ASC
            """
        ).fetchall()
        assert len(rules) == 3
        assert all(int(row["user_id"]) == int(user["id"]) for row in rules)
        assert rules[0]["mail_account_id"] is None
        assert rules[1]["mail_account_id"] is not None
        assert rules[1]["created_from_mail_account_id"] is not None
        assert rules[2]["mail_account_id"] is not None
        assert rules[2]["created_from_mail_account_id"] is not None

        actions = conn.execute(
            """
            SELECT gmail_message_id, account_email, message_id, mail_account_id,
                   provider_message_id, provider_labels_added_json, provider_labels_removed_json
            FROM actions_log
            ORDER BY id ASC
            """
        ).fetchall()
        assert len(actions) == 2
        assert all(row["message_id"] is not None for row in actions)
        assert all(row["mail_account_id"] is not None for row in actions)
        assert all(row["provider_message_id"] == row["gmail_message_id"] for row in actions)
        action_by_message = {row["gmail_message_id"]: row for row in actions}
        assert json.loads(action_by_message["live-201"]["provider_labels_added_json"]) == [
            "Fynish/Trash"
        ]
        assert json.loads(
            action_by_message["live-201"]["provider_labels_removed_json"]
        ) == ["INBOX"]

        notification_settings = conn.execute(
            """
            SELECT user_id, enabled, recipient_email, timezone,
                   morning_enabled, morning_time, evening_enabled
            FROM notification_settings_by_user
            """
        ).fetchone()
        assert notification_settings is not None
        assert int(notification_settings["user_id"]) == int(user["id"])
        assert int(notification_settings["enabled"]) == 1
        assert notification_settings["recipient_email"] == "owner@example.com"
        assert notification_settings["timezone"] == "America/Los_Angeles"
        assert notification_settings["morning_time"] == "08:15"
        assert int(notification_settings["evening_enabled"]) == 0


def test_foundation_migration_preserves_queue_behavior(foundation_pre_migration_db):
    migrate_foundation_schema()

    queue = get_review_queue()
    queue_accounts = {account["account_email"]: account for account in queue["accounts"]}

    assert set(queue_accounts) == {
        "legacy-live@gmail.com",
        "legacy-mock@example.com",
    }
    assert "legacy-disabled@gmail.com" not in queue_accounts

    mock_groups = {
        group["category"]: group for group in queue_accounts["legacy-mock@example.com"]["groups"]
    }
    live_groups = {
        group["category"]: group for group in queue_accounts["legacy-live@gmail.com"]["groups"]
    }
    assert mock_groups["bulk_mail"]["count"] == 1
    assert live_groups["junk_review"]["count"] == 1
    assert live_groups["trash"]["count"] == 0


def test_foundation_migration_validation_passes_on_pre_migration_fixture(
    foundation_pre_migration_db,
):
    migrate_foundation_schema()

    payload = validate_foundation_migration()

    assert payload["failed"] == 0
    assert payload["summary"]["mail_account_count"] == 3
    assert payload["summary"]["provider_connection_count"] == 2


def test_foundation_migration_is_idempotent_on_pre_migration_fixture(
    foundation_pre_migration_db,
):
    first = migrate_foundation_schema()
    second = migrate_foundation_schema()

    assert second["mail_accounts_total"] == first["mail_accounts_total"]
    assert second["provider_connections_total"] == first["provider_connections_total"]
    assert second["messages_total"] == first["messages_total"]
    assert second["rules_total"] == first["rules_total"]
    assert second["actions_log_total"] == first["actions_log_total"]
    assert second["notification_settings_by_user_total"] == first[
        "notification_settings_by_user_total"
    ]
