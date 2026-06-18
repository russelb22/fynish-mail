from __future__ import annotations

import json
from collections.abc import Mapping
from datetime import datetime, timezone

from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id


DEFAULT_LOCAL_OWNER_EMAIL = "local-owner@fynish.local"
DEFAULT_LOCAL_OWNER_NAME = "Local Owner"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _ensure_default_user(conn, now: str) -> int:
    row = fetch_one(
        conn,
        "SELECT id FROM users WHERE email = :email",
        {"email": DEFAULT_LOCAL_OWNER_EMAIL},
    )
    if row is not None:
        return int(row["id"])

    return insert_and_return_id(
        conn,
        """
        INSERT INTO users (email, display_name, status, created_at, updated_at)
        VALUES (:email, :display_name, 'active', :created_at, :updated_at)
        """,
        {
            "email": DEFAULT_LOCAL_OWNER_EMAIL,
            "display_name": DEFAULT_LOCAL_OWNER_NAME,
            "created_at": now,
            "updated_at": now,
        },
    )


def _backfill_mail_accounts(conn, user_id: int, now: str) -> dict[str, int]:
    rows = fetch_all(
        conn,
        """
        SELECT id, email_address, provider, enabled, last_sync_at, created_at, updated_at
        FROM accounts
        ORDER BY id ASC
        """
    )

    mapping: dict[str, int] = {}
    for row in rows:
        existing = fetch_one(
            conn,
            """
            SELECT id
            FROM mail_accounts
            WHERE user_id = :user_id AND provider = :provider AND external_account_email = :email_address
            """,
            {
                "user_id": user_id,
                "provider": row["provider"],
                "email_address": row["email_address"],
            },
        )
        status = "active" if row["enabled"] else "disabled"
        if existing is None:
            mail_account_id = insert_and_return_id(
                conn,
                """
                INSERT INTO mail_accounts (
                    user_id, provider, external_account_email, display_name,
                    enabled, status, last_sync_at, created_at, updated_at
                ) VALUES (
                    :user_id, :provider, :external_account_email, :display_name,
                    :enabled, :status, :last_sync_at, :created_at, :updated_at
                )
                """,
                {
                    "user_id": user_id,
                    "provider": row["provider"],
                    "external_account_email": row["email_address"],
                    "display_name": row["email_address"],
                    "enabled": row["enabled"],
                    "status": status,
                    "last_sync_at": row["last_sync_at"],
                    "created_at": row["created_at"],
                    "updated_at": now,
                },
            )
        else:
            mail_account_id = int(existing["id"])
            execute_sql(
                conn,
                """
                UPDATE mail_accounts
                SET enabled = :enabled, status = :status, last_sync_at = :last_sync_at, updated_at = :updated_at
                WHERE id = :mail_account_id
                """,
                {
                    "enabled": row["enabled"],
                    "status": status,
                    "last_sync_at": row["last_sync_at"],
                    "updated_at": now,
                    "mail_account_id": mail_account_id,
                },
            )
        mapping[row["email_address"]] = mail_account_id
    return mapping


def _backfill_provider_connections(conn, account_mapping: Mapping[str, int], now: str) -> int:
    rows = fetch_all(
        conn,
        """
        SELECT a.email_address, a.provider, g.token_path, g.scopes_json, g.created_at, g.updated_at
        FROM gmail_account_connections g
        JOIN accounts a ON a.id = g.account_id
        ORDER BY g.account_id ASC
        """
    )

    updated = 0
    for row in rows:
        mail_account_id = account_mapping.get(row["email_address"])
        if mail_account_id is None:
            continue
        existing = fetch_one(
            conn,
            """
            SELECT id
            FROM provider_connections
            WHERE mail_account_id = :mail_account_id AND provider = :provider
            """,
            {"mail_account_id": mail_account_id, "provider": row["provider"]},
        )
        if existing is None:
            execute_sql(
                conn,
                """
                INSERT INTO provider_connections (
                    mail_account_id, provider, connection_type, credentials_ref,
                    token_path, scopes_json, metadata_json, created_at, updated_at
                ) VALUES (
                    :mail_account_id, :provider, 'oauth', NULL,
                    :token_path, :scopes_json, '{}', :created_at, :updated_at
                )
                """,
                {
                    "mail_account_id": mail_account_id,
                    "provider": row["provider"],
                    "token_path": row["token_path"],
                    "scopes_json": row["scopes_json"],
                    "created_at": row["created_at"],
                    "updated_at": now,
                },
            )
        else:
            execute_sql(
                conn,
                """
                UPDATE provider_connections
                SET token_path = :token_path, scopes_json = :scopes_json, updated_at = :updated_at
                WHERE id = :provider_connection_id
                """,
                {
                    "token_path": row["token_path"],
                    "scopes_json": row["scopes_json"],
                    "updated_at": now,
                    "provider_connection_id": existing["id"],
                },
            )
        updated += 1
    return updated


def _backfill_messages(conn, account_mapping: Mapping[str, int]) -> int:
    result = execute_sql(
        conn,
        """
        UPDATE messages
        SET
            mail_account_id = COALESCE(
                mail_account_id,
                (SELECT ma.id FROM mail_accounts ma WHERE ma.external_account_email = messages.account_email LIMIT 1)
            ),
            provider_message_id = COALESCE(provider_message_id, gmail_message_id),
            provider_thread_id = COALESCE(provider_thread_id, gmail_thread_id),
            provider_labels_json = CASE
                WHEN provider_labels_json IS NULL
                  OR provider_labels_json = ''
                  OR (
                      provider_labels_json = '[]'
                      AND COALESCE(gmail_labels_json, '[]') != '[]'
                  )
                    THEN COALESCE(gmail_labels_json, '[]')
                ELSE provider_labels_json
            END
        """
    )
    return int(result.rowcount or 0)


def _backfill_rules(conn, user_id: int) -> int:
    result = execute_sql(
        conn,
        """
        UPDATE rules
        SET
            user_id = COALESCE(user_id, :user_id),
            mail_account_id = COALESCE(
                mail_account_id,
                CASE
                    WHEN account_email IS NOT NULL
                    THEN (SELECT ma.id FROM mail_accounts ma WHERE ma.external_account_email = rules.account_email LIMIT 1)
                    ELSE NULL
                END
            ),
            created_from_mail_account_id = COALESCE(
                created_from_mail_account_id,
                CASE
                    WHEN created_from_account IS NOT NULL
                    THEN (SELECT ma.id FROM mail_accounts ma WHERE ma.external_account_email = rules.created_from_account LIMIT 1)
                    ELSE NULL
                END
            )
        """,
        {"user_id": user_id},
    )
    return int(result.rowcount or 0)


def _backfill_actions_log(conn) -> int:
    result = execute_sql(
        conn,
        """
        UPDATE actions_log
        SET
            mail_account_id = COALESCE(
                mail_account_id,
                (SELECT ma.id FROM mail_accounts ma WHERE ma.external_account_email = actions_log.account_email LIMIT 1)
            ),
            provider_message_id = COALESCE(provider_message_id, gmail_message_id),
            message_id = COALESCE(
                message_id,
                (
                    SELECT m.id
                    FROM messages m
                    WHERE m.account_email = actions_log.account_email
                      AND m.gmail_message_id = actions_log.gmail_message_id
                    LIMIT 1
                )
            ),
            provider_labels_added_json = CASE
                WHEN provider_labels_added_json IS NULL
                  OR provider_labels_added_json = ''
                  OR (
                      provider_labels_added_json = '[]'
                      AND COALESCE(gmail_labels_added_json, '[]') != '[]'
                  )
                    THEN COALESCE(gmail_labels_added_json, '[]')
                ELSE provider_labels_added_json
            END,
            provider_labels_removed_json = CASE
                WHEN provider_labels_removed_json IS NULL
                  OR provider_labels_removed_json = ''
                  OR (
                      provider_labels_removed_json = '[]'
                      AND COALESCE(gmail_labels_removed_json, '[]') != '[]'
                  )
                    THEN COALESCE(gmail_labels_removed_json, '[]')
                ELSE provider_labels_removed_json
            END
        """
    )
    return int(result.rowcount or 0)


def _backfill_notification_settings(conn, user_id: int, now: str) -> bool:
    source = fetch_one(
        conn,
        """
        SELECT enabled, recipient_email, timezone, morning_enabled, morning_time,
               evening_enabled, evening_time, send_only_if_queue_nonempty,
               created_at, updated_at
        FROM notification_settings
        WHERE id = 1
        """
    )
    if source is None:
        return False

    existing = fetch_one(
        conn,
        "SELECT id FROM notification_settings_by_user WHERE user_id = :user_id",
        {"user_id": user_id},
    )
    if existing is None:
        execute_sql(
            conn,
            """
            INSERT INTO notification_settings_by_user (
                user_id, enabled, recipient_email, timezone, morning_enabled,
                morning_time, evening_enabled, evening_time, send_only_if_queue_nonempty,
                created_at, updated_at
            ) VALUES (
                :user_id, :enabled, :recipient_email, :timezone, :morning_enabled,
                :morning_time, :evening_enabled, :evening_time, :send_only_if_queue_nonempty,
                :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "enabled": source["enabled"],
                "recipient_email": source["recipient_email"],
                "timezone": source["timezone"],
                "morning_enabled": source["morning_enabled"],
                "morning_time": source["morning_time"],
                "evening_enabled": source["evening_enabled"],
                "evening_time": source["evening_time"],
                "send_only_if_queue_nonempty": source["send_only_if_queue_nonempty"],
                "created_at": source["created_at"],
                "updated_at": now,
            },
        )
    else:
        execute_sql(
            conn,
            """
            UPDATE notification_settings_by_user
            SET
                enabled = :enabled,
                recipient_email = :recipient_email,
                timezone = :timezone,
                morning_enabled = :morning_enabled,
                morning_time = :morning_time,
                evening_enabled = :evening_enabled,
                evening_time = :evening_time,
                send_only_if_queue_nonempty = :send_only_if_queue_nonempty,
                updated_at = :updated_at
            WHERE user_id = :user_id
            """,
            {
                "enabled": source["enabled"],
                "recipient_email": source["recipient_email"],
                "timezone": source["timezone"],
                "morning_enabled": source["morning_enabled"],
                "morning_time": source["morning_time"],
                "evening_enabled": source["evening_enabled"],
                "evening_time": source["evening_time"],
                "send_only_if_queue_nonempty": source["send_only_if_queue_nonempty"],
                "updated_at": now,
                "user_id": user_id,
            },
        )
    return True


def migrate_foundation_schema() -> dict:
    now = _now_iso()
    with get_connection() as conn:
        user_id = _ensure_default_user(conn, now)
        account_mapping = _backfill_mail_accounts(conn, user_id, now)
        provider_connection_count = _backfill_provider_connections(conn, account_mapping, now)
        messages_updated = _backfill_messages(conn, account_mapping)
        rules_updated = _backfill_rules(conn, user_id)
        actions_updated = _backfill_actions_log(conn)
        notification_settings_backfilled = _backfill_notification_settings(conn, user_id, now)

        summary = {
            "default_user_id": user_id,
            "mail_accounts_total": int(
                fetch_one(conn, "SELECT COUNT(*) AS count FROM mail_accounts")["count"]
            ),
            "provider_connections_total": int(
                fetch_one(conn, "SELECT COUNT(*) AS count FROM provider_connections")["count"]
            ),
            "messages_total": int(fetch_one(conn, "SELECT COUNT(*) AS count FROM messages")["count"]),
            "rules_total": int(fetch_one(conn, "SELECT COUNT(*) AS count FROM rules")["count"]),
            "actions_log_total": int(fetch_one(conn, "SELECT COUNT(*) AS count FROM actions_log")["count"]),
            "notification_settings_by_user_total": int(
                fetch_one(
                    conn,
                    "SELECT COUNT(*) AS count FROM notification_settings_by_user",
                )["count"]
            ),
            "mail_accounts_backfilled": len(account_mapping),
            "provider_connections_backfilled": provider_connection_count,
            "messages_updated": messages_updated,
            "rules_updated": rules_updated,
            "actions_updated": actions_updated,
            "notification_settings_backfilled": notification_settings_backfilled,
        }
    return summary
