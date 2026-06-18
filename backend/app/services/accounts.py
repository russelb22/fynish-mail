from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import GOOGLE_TOKEN_DIR
from app.core.config import GMAIL_MODIFY_SCOPE, GMAIL_READONLY_SCOPE
from app.data.mock_messages import get_mock_accounts
from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.services.gmail_readonly import build_service_from_token_path, start_oauth_connection
from app.services.gmail_token_store import store_connection_token_json
from app.services.ownership import fetch_mail_account_owner, fetch_owned_mail_account_by_legacy_id
from app.services.provider_models import MailAccountRecord
from app.services.runtime_user import require_explicit_user_id_in_cloud


class GmailAccountOwnershipError(ValueError):
    pass


def seed_mock_accounts() -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        existing = {
            row["email_address"]
            for row in fetch_all(conn, "SELECT email_address FROM accounts")
        }
        for email in get_mock_accounts():
            if email in existing:
                continue
            execute_sql(
                conn,
                """
                INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                VALUES (:email, 1, 'mock_gmail', :created_at, :updated_at)
                """,
                {"email": email, "created_at": now, "updated_at": now},
            )


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


def _sync_mail_account(
    conn,
    *,
    account_email: str,
    provider: str,
    enabled: bool,
    last_sync_at: str | None,
    now: str,
    user_id: int | None = None,
) -> int:
    effective_user_id = user_id if user_id is not None else _ensure_default_user(conn, now)
    row = fetch_one(
        conn,
        """
        SELECT id
        FROM mail_accounts
        WHERE user_id = :user_id AND provider = :provider AND external_account_email = :account_email
        """,
        {
            "user_id": effective_user_id,
            "provider": provider,
            "account_email": account_email,
        },
    )
    status = "active" if enabled else "disabled"
    if row is None:
        return insert_and_return_id(
            conn,
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (
                :user_id, :provider, :account_email, :display_name,
                :enabled, :status, :last_sync_at, :created_at, :updated_at
            )
            """,
            {
                "user_id": effective_user_id,
                "provider": provider,
                "account_email": account_email,
                "display_name": account_email,
                "enabled": 1 if enabled else 0,
                "status": status,
                "last_sync_at": last_sync_at,
                "created_at": now,
                "updated_at": now,
            },
        )

    mail_account_id = int(row["id"])
    execute_sql(
        conn,
        """
        UPDATE mail_accounts
        SET enabled = :enabled, status = :status, last_sync_at = :last_sync_at, updated_at = :updated_at
        WHERE id = :mail_account_id
        """,
        {
            "enabled": 1 if enabled else 0,
            "status": status,
            "last_sync_at": last_sync_at,
            "updated_at": now,
            "mail_account_id": mail_account_id,
        },
    )
    return mail_account_id


def _sync_provider_connection(
    conn,
    *,
    mail_account_id: int,
    provider: str,
    token_path: str | None,
    scopes: list[str],
    now: str,
) -> int:
    execute_sql(
        conn,
        """
        INSERT INTO provider_connections (
            mail_account_id, provider, connection_type, credentials_ref,
            token_path, scopes_json, metadata_json, created_at, updated_at
        ) VALUES (:mail_account_id, :provider, 'oauth', NULL, :token_path, :scopes_json, '{}', :created_at, :updated_at)
        ON CONFLICT DO NOTHING
        """,
        {
            "mail_account_id": mail_account_id,
            "provider": provider,
            "token_path": token_path,
            "scopes_json": json.dumps(scopes),
            "created_at": now,
            "updated_at": now,
        },
    )
    execute_sql(
        conn,
        """
        UPDATE provider_connections
        SET token_path = :token_path,
            scopes_json = :scopes_json,
            metadata_json = '{}',
            updated_at = :updated_at
        WHERE mail_account_id = :mail_account_id AND provider = :provider
        """,
        {
            "token_path": token_path,
            "scopes_json": json.dumps(scopes),
            "updated_at": now,
            "mail_account_id": mail_account_id,
            "provider": provider,
        },
    )
    row = fetch_one(
        conn,
        """
        SELECT id
        FROM provider_connections
        WHERE mail_account_id = :mail_account_id
          AND provider = :provider
        ORDER BY id DESC
        LIMIT 1
        """,
        {
            "mail_account_id": mail_account_id,
            "provider": provider,
        },
    )
    if row is None:
        raise RuntimeError("Provider connection could not be created or updated.")
    return int(row["id"])


def _load_account_payload(conn, account_email: str) -> dict | None:
    row = fetch_one(
        conn,
        """
        SELECT
            a.id,
            COALESCE(ma.external_account_email, a.email_address) AS email_address,
            COALESCE(ma.enabled, a.enabled) AS enabled,
            COALESCE(ma.provider, a.provider) AS provider,
            COALESCE(ma.last_sync_at, a.last_sync_at) AS last_sync_at,
            pc.scopes_json,
            pc.metadata_json,
            ma.id AS mail_account_id,
            ma.user_id,
            ma.external_account_email,
            ma.display_name AS mail_account_display_name,
            ma.status AS mail_account_status
        FROM mail_accounts ma
        LEFT JOIN accounts a
          ON a.email_address = ma.external_account_email
         AND a.provider = ma.provider
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        WHERE ma.external_account_email = :account_email
        ORDER BY a.id DESC
        LIMIT 1
        """,
        {"account_email": account_email},
    )
    if row is None:
        return None
    account = MailAccountRecord.from_row(row)
    legacy_id = row["id"]
    return dict(row) | account.to_legacy_payload(legacy_id=legacy_id)


def list_accounts(user_id: int | None = None) -> list[dict]:
    with get_connection() as conn:
        params: dict[str, object] = {}
        primary_where = ""
        if user_id is not None:
            primary_where = "WHERE ma.user_id = :user_id"
            params["user_id"] = user_id

        primary_rows = fetch_all(
            conn,
            f"""
            SELECT
                a.id,
                ma.external_account_email AS email_address,
                ma.enabled,
                ma.provider,
                ma.last_sync_at,
                pc.scopes_json,
                pc.metadata_json,
                ma.id AS mail_account_id,
                ma.user_id,
                ma.external_account_email,
                ma.display_name AS mail_account_display_name,
                ma.status AS mail_account_status
            FROM mail_accounts ma
            LEFT JOIN accounts a
              ON a.email_address = ma.external_account_email
             AND a.provider = ma.provider
            LEFT JOIN provider_connections pc
              ON pc.id = (
                    SELECT latest_pc.id
                    FROM provider_connections latest_pc
                    WHERE latest_pc.mail_account_id = ma.id
                      AND latest_pc.provider = ma.provider
                    ORDER BY latest_pc.id DESC
                    LIMIT 1
                 )
            {primary_where}
            ORDER BY ma.external_account_email ASC
            """,
            params,
        )

        if user_id is None:
            legacy_only_rows = fetch_all(
                conn,
                """
                SELECT
                    a.id,
                    a.email_address,
                    a.enabled,
                    a.provider,
                    a.last_sync_at,
                    g.scopes_json,
                    NULL AS metadata_json,
                    NULL AS mail_account_id,
                    NULL AS user_id,
                    NULL AS external_account_email,
                    NULL AS mail_account_display_name,
                    NULL AS mail_account_status
                FROM accounts a
                LEFT JOIN gmail_account_connections g ON g.account_id = a.id
                LEFT JOIN mail_accounts ma
                  ON ma.external_account_email = a.email_address
                 AND ma.provider = a.provider
                WHERE ma.id IS NULL
                ORDER BY a.email_address ASC
                """
            )
        else:
            legacy_only_rows = []
    rows = list(primary_rows) + list(legacy_only_rows)
    payload = []
    for row in rows:
        account = MailAccountRecord.from_row(row)
        payload.append(dict(row) | account.to_legacy_payload(legacy_id=row["id"]))
    payload.sort(key=lambda account: account["email_address"])
    return payload


def connect_next_mock_account(user_id: int | None = None) -> dict | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="connect_next_mock_account",
    )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        existing = {
            row["email_address"]
            for row in fetch_all(conn, "SELECT email_address FROM accounts")
        }
        for email in get_mock_accounts():
            if email in existing:
                continue
            execute_sql(
                conn,
                """
                INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                VALUES (:email, 1, 'mock_gmail', :created_at, :updated_at)
                """,
                {"email": email, "created_at": now, "updated_at": now},
            )
            _sync_mail_account(
                conn,
                account_email=email,
                provider="mock_gmail",
                enabled=True,
                last_sync_at=None,
                now=now,
                user_id=user_id,
            )
            return _load_account_payload(conn, email)
    return None


def connect_gmail_readonly_account(user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="connect_gmail_readonly_account",
    )
    return _connect_gmail_account([GMAIL_READONLY_SCOPE], user_id=user_id)


def connect_gmail_modify_account(user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="connect_gmail_modify_account",
    )
    return _connect_gmail_account([GMAIL_MODIFY_SCOPE], user_id=user_id)


def restore_gmail_accounts_from_saved_tokens() -> list[dict]:
    restored: list[dict] = []
    now = datetime.now(timezone.utc).isoformat()
    token_paths = sorted(GOOGLE_TOKEN_DIR.glob("*.json"))
    for token_path in token_paths:
        token_payload = json.loads(token_path.read_text())
        scopes = token_payload.get("scopes") or [GMAIL_READONLY_SCOPE]
        service = build_service_from_token_path(str(token_path), scopes=scopes)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile["emailAddress"].strip().lower()

        with get_connection() as conn:
            row = fetch_one(
                conn,
                "SELECT * FROM accounts WHERE email_address = :email_address",
                {"email_address": email_address},
            )
            if row is None:
                account_id = insert_and_return_id(
                    conn,
                    """
                    INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                    VALUES (:email_address, 1, 'gmail_readonly', :created_at, :updated_at)
                    """,
                    {
                        "email_address": email_address,
                        "created_at": now,
                        "updated_at": now,
                    },
                )
            else:
                account_id = row["id"]
                execute_sql(
                    conn,
                    """
                    UPDATE accounts
                    SET enabled = 1, provider = 'gmail_readonly', updated_at = :updated_at
                    WHERE id = :account_id
                    """,
                    {"updated_at": now, "account_id": account_id},
                )

            execute_sql(
                conn,
                """
                INSERT INTO gmail_account_connections (
                    account_id, token_path, scopes_json, created_at, updated_at
                ) VALUES (:account_id, :token_path, :scopes_json, :created_at, :updated_at)
                ON CONFLICT(account_id) DO UPDATE SET
                    token_path = excluded.token_path,
                    scopes_json = excluded.scopes_json,
                    updated_at = excluded.updated_at
                """,
                {
                    "account_id": account_id,
                    "token_path": str(token_path),
                    "scopes_json": json.dumps(scopes),
                    "created_at": now,
                    "updated_at": now,
                },
            )
            mail_account_id = _sync_mail_account(
                conn,
                account_email=email_address,
                provider="gmail_readonly",
                enabled=True,
                last_sync_at=row["last_sync_at"] if row is not None else None,
                now=now,
            )
            _sync_provider_connection(
                conn,
                mail_account_id=mail_account_id,
                provider="gmail_readonly",
                token_path=str(token_path),
                scopes=scopes,
                now=now,
            )
            account = _load_account_payload(conn, email_address)
        if account is not None:
            restored.append(account)
    return restored


def import_local_gmail_tokens_to_provider_connections() -> dict[str, int]:
    restored = restore_gmail_accounts_from_saved_tokens()
    imported = 0
    token_paths = sorted(GOOGLE_TOKEN_DIR.glob("*.json"))
    for token_path in token_paths:
        token_payload = json.loads(token_path.read_text())
        scopes = token_payload.get("scopes") or [GMAIL_READONLY_SCOPE]
        service = build_service_from_token_path(str(token_path), scopes=scopes)
        profile = service.users().getProfile(userId="me").execute()
        email_address = profile["emailAddress"].strip().lower()
        with get_connection() as conn:
            row = fetch_one(
                conn,
                """
                SELECT pc.id AS provider_connection_id
                FROM provider_connections pc
                JOIN mail_accounts ma ON ma.id = pc.mail_account_id
                WHERE ma.external_account_email = :email_address
                  AND pc.provider = 'gmail_readonly'
                ORDER BY pc.id DESC
                LIMIT 1
                """,
                {"email_address": email_address},
            )
            if row is None:
                continue
            store_connection_token_json(
                int(row["provider_connection_id"]),
                json.dumps(token_payload),
                token_source=f"imported_local_file:{token_path.name}",
                conn=conn,
            )
            imported += 1
    return {"restored_accounts": len(restored), "imported_tokens": imported}


def _connect_gmail_account(requested_scopes: list[str], *, user_id: int | None = None) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    connection = start_oauth_connection(scopes=requested_scopes)

    return _persist_connected_gmail_account(
        email_address=connection.email_address,
        scopes=connection.scopes,
        now=now,
        user_id=user_id,
        token_path=connection.token_path,
    )


def connect_gmail_account_from_web_oauth(
    *,
    email_address: str,
    scopes: list[str],
    token_json: str,
    user_id: int,
) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="connect_gmail_account_from_web_oauth",
    )
    now = datetime.now(timezone.utc).isoformat()
    return _persist_connected_gmail_account(
        email_address=email_address,
        scopes=scopes,
        now=now,
        user_id=user_id,
        token_json=token_json,
    )


def _persist_connected_gmail_account(
    *,
    email_address: str,
    scopes: list[str],
    now: str,
    user_id: int | None,
    token_path: str | None = None,
    token_json: str | None = None,
) -> dict:
    normalized_email = email_address.strip().lower()

    with get_connection() as conn:
        if user_id is not None:
            existing_owner = fetch_mail_account_owner(conn, normalized_email)
            if existing_owner is not None and int(existing_owner["user_id"]) != user_id:
                raise GmailAccountOwnershipError(
                    "This Gmail account is already connected to a different Fynish user."
                )
        row = fetch_one(
            conn,
            "SELECT * FROM accounts WHERE email_address = :email_address",
            {"email_address": normalized_email},
        )

        if row is None:
            account_id = insert_and_return_id(
                conn,
                """
                INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                VALUES (:email_address, 1, 'gmail_readonly', :created_at, :updated_at)
                """,
                {
                    "email_address": normalized_email,
                    "created_at": now,
                    "updated_at": now,
                },
            )
        else:
            account_id = row["id"]
            execute_sql(
                conn,
                """
                UPDATE accounts
                SET enabled = 1, provider = 'gmail_readonly', updated_at = :updated_at
                    WHERE id = :account_id
                    """,
                    {"updated_at": now, "account_id": account_id},
                )

        if token_path:
            execute_sql(
                conn,
                """
                INSERT INTO gmail_account_connections (
                    account_id, token_path, scopes_json, created_at, updated_at
                ) VALUES (:account_id, :token_path, :scopes_json, :created_at, :updated_at)
                ON CONFLICT(account_id) DO UPDATE SET
                    token_path = excluded.token_path,
                    scopes_json = excluded.scopes_json,
                    updated_at = excluded.updated_at
                """,
                {
                    "account_id": account_id,
                    "token_path": token_path,
                    "scopes_json": json.dumps(scopes),
                    "created_at": now,
                    "updated_at": now,
                },
            )
        mail_account_id = _sync_mail_account(
            conn,
            account_email=normalized_email,
            provider="gmail_readonly",
            enabled=True,
            last_sync_at=None,
            now=now,
            user_id=user_id,
        )
        provider_connection_id = _sync_provider_connection(
            conn,
            mail_account_id=mail_account_id,
            provider="gmail_readonly",
            token_path=token_path,
            scopes=scopes,
            now=now,
        )
        if token_json:
            store_connection_token_json(
                provider_connection_id,
                token_json,
                token_source="hosted_web_oauth",
                conn=conn,
            )
        account = _load_account_payload(conn, normalized_email)

    return account


def set_account_enabled(
    account_id: int,
    *,
    enabled: bool,
    user_id: int | None = None,
) -> dict | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="set_account_enabled",
    )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        row = (
            fetch_owned_mail_account_by_legacy_id(conn, account_id, user_id)
            if user_id is not None
            else fetch_one(conn, "SELECT * FROM accounts WHERE id = :account_id", {"account_id": account_id})
        )
        if row is None:
            return None
        execute_sql(
            conn,
            "UPDATE accounts SET enabled = :enabled, updated_at = :updated_at WHERE id = :account_id",
            {
                "enabled": 1 if enabled else 0,
                "updated_at": now,
                "account_id": account_id,
            },
        )
        _sync_mail_account(
            conn,
            account_email=row["email_address"],
            provider=row["provider"],
            enabled=enabled,
            last_sync_at=row["last_sync_at"],
            now=now,
            user_id=user_id,
        )
        updated = _load_account_payload(conn, row["email_address"])
    return updated


def disable_account(account_id: int, user_id: int | None = None) -> dict | None:
    return set_account_enabled(account_id, enabled=False, user_id=user_id)


def enable_account(account_id: int, user_id: int | None = None) -> dict | None:
    return set_account_enabled(account_id, enabled=True, user_id=user_id)
