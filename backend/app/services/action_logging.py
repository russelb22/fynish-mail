from __future__ import annotations

import json
from collections.abc import Mapping

from app.core.config import APP_ENV
from app.db.runtime import execute_sql, fetch_one, insert_and_return_id
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME


def _ensure_default_user(conn, created_at: str) -> int:
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
            "created_at": created_at,
            "updated_at": created_at,
        },
    )


def _resolve_message_context(conn, message_row: Mapping, created_at: str) -> dict:
    resolved = dict(message_row)
    resolved["provider_message_id"] = (
        resolved.get("provider_message_id") or resolved.get("gmail_message_id")
    )
    resolved["provider_thread_id"] = (
        resolved.get("provider_thread_id") or resolved.get("gmail_thread_id")
    )
    resolved["provider_labels_json"] = (
        resolved.get("provider_labels_json") or resolved.get("gmail_labels_json")
    )
    mail_account_id = resolved.get("mail_account_id")
    if mail_account_id is None and resolved.get("account_email"):
        existing_mail_account = fetch_one(
            conn,
            """
            SELECT id
            FROM mail_accounts
            WHERE external_account_email = :account_email
            ORDER BY id DESC
            LIMIT 1
            """,
            {"account_email": resolved["account_email"]},
        )
        if existing_mail_account is None:
            if APP_ENV == "cloud":
                return resolved
            account_row = fetch_one(
                conn,
                """
                SELECT provider, enabled
                FROM accounts
                WHERE email_address = :account_email
                ORDER BY id DESC
                LIMIT 1
                """,
                {"account_email": resolved["account_email"]},
            )
            user_id = _ensure_default_user(conn, created_at)
            provider = account_row["provider"] if account_row is not None else "mock_gmail"
            enabled = bool(account_row["enabled"]) if account_row is not None else True
            mail_account_id = insert_and_return_id(
                conn,
                """
                INSERT INTO mail_accounts (
                    user_id, provider, external_account_email, display_name,
                    enabled, status, created_at, updated_at
                ) VALUES (
                    :user_id, :provider, :account_email, :display_name,
                    :enabled, :status, :created_at, :updated_at
                )
                """,
                {
                    "user_id": user_id,
                    "provider": provider,
                    "account_email": resolved["account_email"],
                    "display_name": resolved["account_email"],
                    "enabled": 1 if enabled else 0,
                    "status": "active" if enabled else "disabled",
                    "created_at": created_at,
                    "updated_at": created_at,
                },
            )
        else:
            mail_account_id = int(existing_mail_account["id"])
        execute_sql(
            conn,
            """
            UPDATE messages
            SET mail_account_id = :mail_account_id,
                provider_message_id = COALESCE(provider_message_id, :provider_message_id),
                provider_thread_id = COALESCE(provider_thread_id, :provider_thread_id),
                provider_labels_json = COALESCE(provider_labels_json, :provider_labels_json),
                updated_at = :updated_at
            WHERE id = :message_id
            """,
            {
                "mail_account_id": mail_account_id,
                "provider_message_id": resolved["provider_message_id"],
                "provider_thread_id": resolved["provider_thread_id"],
                "provider_labels_json": resolved["provider_labels_json"],
                "updated_at": created_at,
                "message_id": resolved["id"],
            },
        )
        resolved["mail_account_id"] = mail_account_id
    elif resolved.get("provider_message_id") and resolved.get("id") is not None:
        execute_sql(
            conn,
            """
            UPDATE messages
            SET provider_message_id = COALESCE(provider_message_id, :provider_message_id),
                provider_thread_id = COALESCE(provider_thread_id, :provider_thread_id),
                provider_labels_json = COALESCE(provider_labels_json, :provider_labels_json),
                updated_at = :updated_at
            WHERE id = :message_id
            """,
            {
                "provider_message_id": resolved["provider_message_id"],
                "provider_thread_id": resolved["provider_thread_id"],
                "provider_labels_json": resolved["provider_labels_json"],
                "updated_at": created_at,
                "message_id": resolved["id"],
            },
        )
    return resolved


def insert_action_log(
    conn,
    *,
    message_row: Mapping,
    selected_action: str,
    recommended_action: str | None,
    labels_added: list[str],
    labels_removed: list[str],
    created_at: str,
    action_source: str = "manual",
    created_rule_id: int | None = None,
) -> None:
    resolved_message = _resolve_message_context(conn, message_row, created_at)
    provider_message_id = (
        resolved_message["provider_message_id"] or resolved_message["gmail_message_id"]
    )
    user_overrode = 1 if recommended_action != selected_action else 0
    execute_sql(
        conn,
        """
        INSERT INTO actions_log (
            message_id,
            mail_account_id,
            provider_message_id,
            provider_labels_added_json,
            provider_labels_removed_json,
            gmail_message_id,
            account_email,
            selected_action,
            recommended_action,
            user_overrode,
            action_source,
            gmail_labels_added_json,
            gmail_labels_removed_json,
            created_rule_id,
            created_at
        ) VALUES (
            :message_id,
            :mail_account_id,
            :provider_message_id,
            :provider_labels_added_json,
            :provider_labels_removed_json,
            :gmail_message_id,
            :account_email,
            :selected_action,
            :recommended_action,
            :user_overrode,
            :action_source,
            :gmail_labels_added_json,
            :gmail_labels_removed_json,
            :created_rule_id,
            :created_at
        )
        """,
        {
            "message_id": int(resolved_message["id"]),
            "mail_account_id": resolved_message["mail_account_id"],
            "provider_message_id": provider_message_id,
            "provider_labels_added_json": json.dumps(labels_added),
            "provider_labels_removed_json": json.dumps(labels_removed),
            "gmail_message_id": resolved_message["gmail_message_id"],
            "account_email": resolved_message["account_email"],
            "selected_action": selected_action,
            "recommended_action": recommended_action,
            "user_overrode": user_overrode,
            "action_source": action_source,
            "gmail_labels_added_json": json.dumps(labels_added),
            "gmail_labels_removed_json": json.dumps(labels_removed),
            "created_rule_id": created_rule_id,
            "created_at": created_at,
        },
    )
