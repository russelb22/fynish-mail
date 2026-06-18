from __future__ import annotations

from datetime import datetime, timezone

from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.services.ownership import fetch_owned_mail_account_by_email, fetch_owned_message, fetch_owned_rule
from app.services.runtime_user import require_explicit_user_id_in_cloud


class RuleAccountUnavailableError(ValueError):
    pass


class RuleSourceMessageUnavailableError(ValueError):
    pass


def _normalized_pattern(pattern: str) -> str:
    return pattern.strip().lower()


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


def _mail_account_id_for_email(conn, account_email: str | None, user_id: int | None = None) -> int | None:
    if not account_email:
        return None
    row = (
        fetch_owned_mail_account_by_email(conn, account_email, user_id)
        if user_id is not None
        else fetch_one(
            conn,
            """
            SELECT ma.id
            FROM mail_accounts ma
            WHERE ma.external_account_email = :account_email
            ORDER BY ma.id DESC
            LIMIT 1
            """,
            {"account_email": account_email},
        )
    )
    return int(row["id"]) if row is not None else None


def _mail_account_id_for_source_message(
    conn,
    source_message_id: int | None,
    user_id: int | None = None,
) -> int | None:
    if source_message_id is None:
        return None
    row = (
        fetch_owned_message(conn, source_message_id, user_id)
        if user_id is not None
        else fetch_one(
            conn,
            """
            SELECT mail_account_id
            FROM messages
            WHERE id = :message_id
            """,
            {"message_id": source_message_id},
        )
    )
    if row is None or row["mail_account_id"] is None:
        return None
    return int(row["mail_account_id"])


def list_rules(user_id: int | None = None) -> list[dict]:
    with get_connection() as conn:
        params: dict[str, object] = {}
        where_clause = ""
        if user_id is not None:
            where_clause = "WHERE r.user_id = :user_id"
            params["user_id"] = user_id
        rows = fetch_all(
            conn,
            f"""
            SELECT
                r.*,
                COALESCE(
                    account_ma.external_account_email,
                    r.account_email
                ) AS normalized_account_email
            FROM rules r
            LEFT JOIN mail_accounts account_ma ON account_ma.id = r.mail_account_id
            {where_clause}
            ORDER BY r.created_at DESC
            """,
            params,
        )
    return [
        dict(row)
        | {
            "enabled": bool(row["enabled"]),
            "account_email": row["normalized_account_email"],
        }
        for row in rows
    ]


def create_rule(payload: dict, user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="create_rule",
    )
    now = datetime.now(timezone.utc).isoformat()
    normalized_pattern = _normalized_pattern(payload["pattern"])
    with get_connection() as conn:
        effective_user_id = user_id if user_id is not None else _ensure_default_user(conn, now)
        requested_account_email = payload.get("account_email")
        mail_account_id = _mail_account_id_for_email(
            conn,
            requested_account_email,
            effective_user_id if user_id is not None else None,
        )
        if requested_account_email and mail_account_id is None:
            raise RuleAccountUnavailableError("Account is not available to the current user.")
        source_message_id = payload.get("source_message_id")
        created_from_mail_account_id = _mail_account_id_for_source_message(
            conn,
            source_message_id,
            effective_user_id if user_id is not None else None,
        ) or _mail_account_id_for_email(
            conn,
            payload.get("created_from_account"),
            effective_user_id if user_id is not None else None,
        )
        if source_message_id is not None and created_from_mail_account_id is None:
            raise RuleSourceMessageUnavailableError(
                "Source message is not available to the current user."
            )
        existing_enabled = fetch_one(
            conn,
            """
            SELECT *
            FROM rules
            WHERE user_id = :user_id
              AND COALESCE(mail_account_id, -1) = COALESCE(:mail_account_id, -1)
              AND rule_type = :rule_type
              AND pattern = :pattern
              AND action = :action
              AND enabled = 1
            ORDER BY id DESC
            LIMIT 1
            """,
            {
                "user_id": effective_user_id,
                "mail_account_id": mail_account_id,
                "rule_type": payload["rule_type"],
                "pattern": normalized_pattern,
                "action": payload["action"],
            },
        )
        if existing_enabled is not None:
            return dict(existing_enabled) | {"enabled": True}

        existing_disabled = fetch_one(
            conn,
            """
            SELECT *
            FROM rules
            WHERE user_id = :user_id
              AND COALESCE(mail_account_id, -1) = COALESCE(:mail_account_id, -1)
              AND rule_type = :rule_type
              AND pattern = :pattern
              AND action = :action
              AND enabled = 0
            ORDER BY id DESC
            LIMIT 1
            """,
            {
                "user_id": effective_user_id,
                "mail_account_id": mail_account_id,
                "rule_type": payload["rule_type"],
                "pattern": normalized_pattern,
                "action": payload["action"],
            },
        )
        if existing_disabled is not None:
            execute_sql(
                conn,
                """
                UPDATE rules
                SET enabled = 1, updated_at = :updated_at
                WHERE id = :rule_id
                """,
                {"updated_at": now, "rule_id": existing_disabled["id"]},
            )
            row = fetch_one(
                conn,
                "SELECT * FROM rules WHERE id = :rule_id",
                {"rule_id": existing_disabled["id"]},
            )
            return dict(row) | {"enabled": True}

        rule_id = insert_and_return_id(
            conn,
            """
            INSERT INTO rules (
                user_id, mail_account_id, created_from_mail_account_id,
                scope, account_email, rule_type, pattern, action, enabled,
                created_from_account, created_from_message_id, created_at, updated_at
            ) VALUES (
                :user_id,
                :mail_account_id,
                :created_from_mail_account_id,
                :scope,
                :account_email,
                :rule_type,
                :pattern,
                :action,
                1,
                :created_from_account,
                :created_from_message_id,
                :created_at,
                :updated_at
            )
            """,
            {
                "user_id": effective_user_id,
                "mail_account_id": mail_account_id,
                "created_from_mail_account_id": created_from_mail_account_id,
                "scope": payload.get("scope", "global"),
                "account_email": payload.get("account_email"),
                "rule_type": payload["rule_type"],
                "pattern": normalized_pattern,
                "action": payload["action"],
                "created_from_account": payload.get("created_from_account"),
                "created_from_message_id": (
                    str(source_message_id) if source_message_id is not None else None
                ),
                "created_at": now,
                "updated_at": now,
            },
        )
        row = fetch_one(
            conn,
            """
            SELECT
                r.*,
                COALESCE(account_ma.external_account_email, r.account_email) AS normalized_account_email
            FROM rules r
            LEFT JOIN mail_accounts account_ma ON account_ma.id = r.mail_account_id
            WHERE r.id = :rule_id
            """,
            {"rule_id": rule_id},
        )
    return dict(row) | {
        "enabled": bool(row["enabled"]),
        "account_email": row["normalized_account_email"],
    }


def update_rule(rule_id: int, payload: dict, user_id: int | None = None) -> dict | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="update_rule",
    )
    with get_connection() as conn:
        row = (
            fetch_owned_rule(conn, rule_id, user_id)
            if user_id is not None
            else fetch_one(conn, "SELECT * FROM rules WHERE id = :rule_id", {"rule_id": rule_id})
        )
        if row is None:
            return None
        enabled = payload["enabled"] if payload.get("enabled") is not None else row["enabled"]
        action = payload["action"] if payload.get("action") else row["action"]
        updated_at = datetime.now(timezone.utc).isoformat()
        execute_sql(
            conn,
            """
            UPDATE rules
            SET enabled = :enabled, action = :action, updated_at = :updated_at
            WHERE id = :rule_id
            """,
            {
                "enabled": 1 if enabled else 0,
                "action": action,
                "updated_at": updated_at,
                "rule_id": rule_id,
            },
        )
        updated = fetch_one(conn, "SELECT * FROM rules WHERE id = :rule_id", {"rule_id": rule_id})
    return dict(updated) | {"enabled": bool(updated["enabled"])}


def delete_rule(rule_id: int, user_id: int | None = None) -> bool:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="delete_rule",
    )
    with get_connection() as conn:
        if user_id is not None and fetch_owned_rule(conn, rule_id, user_id) is None:
            return False
        result = execute_sql(conn, "DELETE FROM rules WHERE id = :rule_id", {"rule_id": rule_id})
        return (result.rowcount or 0) > 0


def record_rule_matches(rule_ids: list[int], conn=None) -> None:
    if not rule_ids:
        return
    now = datetime.now(timezone.utc).isoformat()
    if conn is not None:
        for rule_id in rule_ids:
            execute_sql(
                conn,
                """
                UPDATE rules
                SET match_count = match_count + 1, last_matched_at = :last_matched_at, updated_at = :updated_at
                WHERE id = :rule_id
                """,
                {
                    "last_matched_at": now,
                    "updated_at": now,
                    "rule_id": rule_id,
                },
            )
        return

    with get_connection() as managed_conn:
        for rule_id in rule_ids:
            execute_sql(
                managed_conn,
                """
                UPDATE rules
                SET match_count = match_count + 1, last_matched_at = :last_matched_at, updated_at = :updated_at
                WHERE id = :rule_id
                """,
                {
                    "last_matched_at": now,
                    "updated_at": now,
                    "rule_id": rule_id,
                },
            )
