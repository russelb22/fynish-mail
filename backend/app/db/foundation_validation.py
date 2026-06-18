from __future__ import annotations

import json
from collections.abc import Iterable

from app.db.runtime import fetch_all, fetch_one, get_connection
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL
from app.services.review_queue import get_review_queue


def _check(condition: bool, label: str) -> tuple[bool, str]:
    return condition, f"{'PASS' if condition else 'FAIL'} {label}"


def _coalesce_count(value: object) -> int:
    return int(value or 0)


def _count_invalid_json_array_rows(rows: Iterable[object], key: str) -> int:
    invalid = 0
    for row in rows:
        try:
            parsed = json.loads(row[key] or "[]")
        except (TypeError, json.JSONDecodeError):
            invalid += 1
            continue
        if not isinstance(parsed, list):
            invalid += 1
    return invalid


def validate_foundation_migration() -> dict[str, object]:
    results: list[tuple[bool, str]] = []

    with get_connection() as conn:
        account_count = int(fetch_one(conn, "SELECT COUNT(*) AS count FROM accounts")["count"])
        mail_account_count = int(
            fetch_one(conn, "SELECT COUNT(*) AS count FROM mail_accounts")["count"]
        )
        gmail_connection_count = int(
            fetch_one(conn, "SELECT COUNT(*) AS count FROM gmail_account_connections")["count"]
        )
        provider_connection_count = int(
            fetch_one(conn, "SELECT COUNT(*) AS count FROM provider_connections")["count"]
        )
        default_user = fetch_one(
            conn,
            "SELECT id FROM users WHERE email = :email",
            {"email": DEFAULT_LOCAL_OWNER_EMAIL},
        )
        default_user_id = int(default_user["id"]) if default_user is not None else None

        missing_mail_account_mappings = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM accounts a
                LEFT JOIN mail_accounts ma
                  ON ma.external_account_email = a.email_address
                 AND ma.provider = a.provider
                WHERE ma.id IS NULL
                """
            )["count"]
        )
        dangling_mail_account_users = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM mail_accounts ma
                LEFT JOIN users u ON u.id = ma.user_id
                WHERE u.id IS NULL
                """
            )["count"]
        )
        dangling_provider_connection_accounts = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM provider_connections pc
                LEFT JOIN mail_accounts ma ON ma.id = pc.mail_account_id
                WHERE ma.id IS NULL
                """
            )["count"]
        )
        missing_provider_connection_mappings = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM gmail_account_connections g
                JOIN accounts a ON a.id = g.account_id
                LEFT JOIN mail_accounts ma
                  ON ma.external_account_email = a.email_address
                 AND ma.provider = a.provider
                LEFT JOIN provider_connections pc
                  ON pc.mail_account_id = ma.id
                 AND pc.provider = a.provider
                WHERE pc.id IS NULL
                """
            )["count"]
        )
        duplicate_provider_connections = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT mail_account_id, provider
                    FROM provider_connections
                    GROUP BY mail_account_id, provider
                    HAVING COUNT(*) > 1
                )
                """
            )["count"]
        )

        missing_message_backfills = fetch_one(
            conn,
            """
            SELECT
                SUM(CASE WHEN mail_account_id IS NULL THEN 1 ELSE 0 END) AS missing_mail_account_id,
                SUM(CASE WHEN provider_message_id IS NULL OR provider_message_id = '' THEN 1 ELSE 0 END) AS missing_provider_message_id,
                SUM(CASE WHEN provider_labels_json IS NULL OR provider_labels_json = '' THEN 1 ELSE 0 END) AS missing_provider_labels_json
            FROM messages
            """
        )
        duplicate_provider_messages = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM (
                    SELECT mail_account_id, provider_message_id
                    FROM messages
                    WHERE mail_account_id IS NOT NULL
                      AND provider_message_id IS NOT NULL
                      AND provider_message_id != ''
                    GROUP BY mail_account_id, provider_message_id
                    HAVING COUNT(*) > 1
                )
                """
            )["count"]
        )
        dangling_message_accounts = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM messages m
                LEFT JOIN mail_accounts ma ON ma.id = m.mail_account_id
                WHERE m.mail_account_id IS NOT NULL
                  AND ma.id IS NULL
                """
            )["count"]
        )

        missing_rule_backfills = fetch_one(
            conn,
            """
            SELECT
                SUM(CASE WHEN user_id IS NULL THEN 1 ELSE 0 END) AS missing_user_id,
                SUM(CASE WHEN account_email IS NOT NULL AND mail_account_id IS NULL THEN 1 ELSE 0 END) AS missing_mail_account_id,
                SUM(CASE WHEN created_from_account IS NOT NULL AND created_from_mail_account_id IS NULL THEN 1 ELSE 0 END) AS missing_created_from_mail_account_id
            FROM rules
            """
        )
        dangling_rule_users = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM rules r
                LEFT JOIN users u ON u.id = r.user_id
                WHERE r.user_id IS NOT NULL
                  AND u.id IS NULL
                """
            )["count"]
        )
        dangling_rule_accounts = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM rules r
                LEFT JOIN mail_accounts ma ON ma.id = r.mail_account_id
                WHERE r.mail_account_id IS NOT NULL
                  AND ma.id IS NULL
                """
            )["count"]
        )

        missing_action_backfills = fetch_one(
            conn,
            """
            SELECT
                SUM(CASE WHEN mail_account_id IS NULL THEN 1 ELSE 0 END) AS missing_mail_account_id,
                SUM(CASE WHEN provider_message_id IS NULL OR provider_message_id = '' THEN 1 ELSE 0 END) AS missing_provider_message_id,
                SUM(CASE WHEN message_id IS NULL THEN 1 ELSE 0 END) AS missing_message_id
            FROM actions_log
            """
        )
        dangling_action_accounts = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM actions_log a
                LEFT JOIN mail_accounts ma ON ma.id = a.mail_account_id
                WHERE a.mail_account_id IS NOT NULL
                  AND ma.id IS NULL
                """
            )["count"]
        )
        dangling_action_messages = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM actions_log a
                LEFT JOIN messages m ON m.id = a.message_id
                WHERE a.message_id IS NOT NULL
                  AND m.id IS NULL
                """
            )["count"]
        )
        action_label_rows = fetch_all(
            conn,
            """
            SELECT provider_labels_added_json, provider_labels_removed_json
            FROM actions_log
            """
        )
        invalid_action_added_labels = _count_invalid_json_array_rows(
            action_label_rows, "provider_labels_added_json"
        )
        invalid_action_removed_labels = _count_invalid_json_array_rows(
            action_label_rows, "provider_labels_removed_json"
        )

        notification_rows = fetch_one(
            conn,
            """
            SELECT COUNT(*) AS count
            FROM notification_settings_by_user ns
            LEFT JOIN users u ON u.id = ns.user_id
            WHERE u.id IS NULL
            """
        )

        queue = get_review_queue()
        queue_account_emails = {account["account_email"] for account in queue["accounts"]}
        expected_enabled_account_emails = {
            row["email_address"]
            for row in fetch_all(
                conn,
                "SELECT email_address FROM accounts WHERE enabled = 1"
            )
        }
        queue_message_count = sum(
            len(group["messages"])
            for account in queue["accounts"]
            for group in account["groups"]
        )
        pending_db_message_count = int(
            fetch_one(
                conn,
                """
                SELECT COUNT(*) AS count
                FROM messages m
                JOIN accounts a ON a.email_address = m.account_email
                WHERE a.enabled = 1
                  AND m.reviewed = 0
                """
            )["count"]
        )

    results.append(
        _check(default_user_id is not None, "default local owner user exists")
    )
    results.append(
        _check(
            mail_account_count >= account_count,
            "mail_accounts table is populated for current accounts",
        )
    )
    results.append(
        _check(
            provider_connection_count >= gmail_connection_count,
            "provider_connections table is populated for Gmail connections",
        )
    )
    results.append(
        _check(
            missing_mail_account_mappings == 0,
            "every legacy account maps to a mail_account row",
        )
    )
    results.append(
        _check(
            dangling_mail_account_users == 0,
            "every mail_account.user_id references an existing user",
        )
    )
    results.append(
        _check(
            dangling_provider_connection_accounts == 0,
            "every provider_connection.mail_account_id references an existing mail_account",
        )
    )
    results.append(
        _check(
            missing_provider_connection_mappings == 0,
            "every legacy Gmail connection maps to a provider_connection row",
        )
    )
    results.append(
        _check(
            duplicate_provider_connections == 0,
            "provider_connections are unique per mail account and provider",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_message_backfills["missing_mail_account_id"]) == 0,
            "messages.mail_account_id is fully backfilled",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_message_backfills["missing_provider_message_id"]) == 0,
            "messages.provider_message_id is fully backfilled",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_message_backfills["missing_provider_labels_json"]) == 0,
            "messages.provider_labels_json is fully backfilled",
        )
    )
    results.append(
        _check(
            dangling_message_accounts == 0,
            "every messages.mail_account_id references an existing mail_account",
        )
    )
    results.append(
        _check(
            duplicate_provider_messages == 0,
            "provider-neutral message identifiers are unique per mail account",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_rule_backfills["missing_user_id"]) == 0,
            "rules.user_id is fully backfilled",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_rule_backfills["missing_mail_account_id"]) == 0,
            "rules.mail_account_id is backfilled when account_email is present",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_rule_backfills["missing_created_from_mail_account_id"])
            == 0,
            "rules.created_from_mail_account_id is backfilled when created_from_account is present",
        )
    )
    results.append(
        _check(
            dangling_rule_users == 0,
            "every rules.user_id references an existing user",
        )
    )
    results.append(
        _check(
            dangling_rule_accounts == 0,
            "every populated rules.mail_account_id references an existing mail_account",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_action_backfills["missing_mail_account_id"]) == 0,
            "actions_log.mail_account_id is fully backfilled",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_action_backfills["missing_provider_message_id"]) == 0,
            "actions_log.provider_message_id is fully backfilled",
        )
    )
    results.append(
        _check(
            _coalesce_count(missing_action_backfills["missing_message_id"]) == 0,
            "actions_log.message_id is fully backfilled",
        )
    )
    results.append(
        _check(
            dangling_action_accounts == 0,
            "every populated actions_log.mail_account_id references an existing mail_account",
        )
    )
    results.append(
        _check(
            dangling_action_messages == 0,
            "every populated actions_log.message_id references an existing message row",
        )
    )
    results.append(
        _check(
            invalid_action_added_labels == 0,
            "actions_log.provider_labels_added_json stores JSON arrays",
        )
    )
    results.append(
        _check(
            invalid_action_removed_labels == 0,
            "actions_log.provider_labels_removed_json stores JSON arrays",
        )
    )
    results.append(
        _check(
            int(notification_rows["count"]) == 0,
            "notification_settings_by_user rows reference existing users",
        )
    )
    results.append(
        _check(
            queue_account_emails == expected_enabled_account_emails,
            "review queue remains compatible with enabled account visibility",
        )
    )
    results.append(
        _check(
            queue_message_count == pending_db_message_count,
            "review queue message count matches pending database state",
        )
    )

    passed = sum(1 for ok, _ in results if ok)
    failed = len(results) - passed
    return {
        "results": results,
        "passed": passed,
        "failed": failed,
        "summary": {
            "default_user_id": default_user_id,
            "account_count": account_count,
            "mail_account_count": mail_account_count,
            "gmail_connection_count": gmail_connection_count,
            "provider_connection_count": provider_connection_count,
            "queue_account_count": len(queue["accounts"]),
            "queue_message_count": queue_message_count,
            "pending_db_message_count": pending_db_message_count,
        },
    }
