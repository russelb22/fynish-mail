from __future__ import annotations

from app.db.runtime import fetch_one


def fetch_owned_mail_account_by_legacy_id(conn, account_id: int, user_id: int):
    return fetch_one(
        conn,
        """
        SELECT
            a.*,
            ma.id AS mail_account_id,
            ma.user_id,
            ma.external_account_email,
            ma.provider AS normalized_provider
        FROM accounts a
        JOIN mail_accounts ma
          ON ma.external_account_email = a.email_address
         AND ma.provider = a.provider
        WHERE a.id = :account_id
          AND ma.user_id = :user_id
        ORDER BY ma.id DESC
        LIMIT 1
        """,
        {"account_id": account_id, "user_id": user_id},
    )


def fetch_owned_mail_account_by_email(conn, account_email: str, user_id: int):
    return fetch_one(
        conn,
        """
        SELECT *
        FROM mail_accounts
        WHERE external_account_email = :account_email
          AND user_id = :user_id
        ORDER BY id DESC
        LIMIT 1
        """,
        {"account_email": account_email, "user_id": user_id},
    )


def fetch_mail_account_owner(conn, account_email: str):
    return fetch_one(
        conn,
        """
        SELECT user_id, id, external_account_email
        FROM mail_accounts
        WHERE external_account_email = :account_email
        ORDER BY id DESC
        LIMIT 1
        """,
        {"account_email": account_email},
    )


def fetch_owned_message(conn, message_id: int, user_id: int):
    return fetch_one(
        conn,
        """
        SELECT m.*
        FROM messages m
        JOIN mail_accounts ma ON ma.id = m.mail_account_id
        WHERE m.id = :message_id
          AND ma.user_id = :user_id
        LIMIT 1
        """,
        {"message_id": message_id, "user_id": user_id},
    )


def fetch_owned_rule(conn, rule_id: int, user_id: int):
    return fetch_one(
        conn,
        """
        SELECT *
        FROM rules
        WHERE id = :rule_id
          AND user_id = :user_id
        LIMIT 1
        """,
        {"rule_id": rule_id, "user_id": user_id},
    )
