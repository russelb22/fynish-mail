from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

from app.core import config
from app.db.runtime import execute_sql, fetch_one, get_connection
from app.services.gmail_token_store import (
    GMAIL_TOKEN_JSON_METADATA_KEY,
    GMAIL_TOKEN_SOURCE_METADATA_KEY,
)


class DigestSenderNotConfiguredError(RuntimeError):
    pass


class DigestSenderAuthError(RuntimeError):
    pass


class DigestSenderValidationError(ValueError):
    pass


@dataclass(frozen=True)
class DigestSenderConnection:
    id: int
    provider: str
    email_address: str
    scopes: list[str]
    token_json: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_json_dict(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item) for item in parsed]


def _connection_from_row(row) -> DigestSenderConnection:
    metadata = _parse_json_dict(row["metadata_json"])
    token_json = metadata.get(GMAIL_TOKEN_JSON_METADATA_KEY)
    return DigestSenderConnection(
        id=int(row["id"]),
        provider=str(row["provider"]),
        email_address=str(row["email_address"]).strip().lower(),
        scopes=_parse_json_list(row["scopes_json"]),
        token_json=token_json if isinstance(token_json, str) and token_json else None,
    )


def _fetch_digest_sender_connection(
    conn,
    *,
    email_address: str | None = None,
) -> DigestSenderConnection | None:
    normalized_email = (email_address or config.GMAIL_SENDER_EMAIL).strip().lower()
    if normalized_email:
        row = fetch_one(
            conn,
            """
            SELECT id, provider, email_address, scopes_json, metadata_json
            FROM digest_sender_connections
            WHERE provider = 'gmail' AND email_address = :email_address
            ORDER BY id DESC
            LIMIT 1
            """,
            {"email_address": normalized_email},
        )
    else:
        row = fetch_one(
            conn,
            """
            SELECT id, provider, email_address, scopes_json, metadata_json
            FROM digest_sender_connections
            WHERE provider = 'gmail'
            ORDER BY updated_at DESC, id DESC
            LIMIT 1
            """,
        )
    return _connection_from_row(row) if row is not None else None


def _update_digest_sender_token(
    conn,
    *,
    sender_id: int,
    token_json: str,
    token_source: str,
) -> None:
    row = fetch_one(
        conn,
        "SELECT metadata_json FROM digest_sender_connections WHERE id = :sender_id",
        {"sender_id": sender_id},
    )
    if row is None:
        raise DigestSenderAuthError("Digest sender connection disappeared while refreshing credentials.")
    metadata = _parse_json_dict(row["metadata_json"])
    metadata[GMAIL_TOKEN_JSON_METADATA_KEY] = token_json
    metadata[GMAIL_TOKEN_SOURCE_METADATA_KEY] = token_source
    execute_sql(
        conn,
        """
        UPDATE digest_sender_connections
        SET metadata_json = :metadata_json,
            updated_at = :updated_at
        WHERE id = :sender_id
        """,
        {
            "metadata_json": json.dumps(metadata, sort_keys=True),
            "updated_at": _now_iso(),
            "sender_id": sender_id,
        },
    )


def persist_gmail_digest_sender(
    *,
    email_address: str,
    scopes: list[str],
    token_json: str,
) -> dict:
    normalized_email = email_address.strip().lower()
    if not normalized_email:
        raise DigestSenderValidationError("Digest sender email address is required.")
    if config.GMAIL_SEND_SCOPE not in scopes:
        raise DigestSenderValidationError(
            "Digest sender OAuth credentials must include Gmail send access."
        )

    now = _now_iso()
    metadata = {
        GMAIL_TOKEN_JSON_METADATA_KEY: token_json,
        GMAIL_TOKEN_SOURCE_METADATA_KEY: "hosted_web_oauth",
    }
    with get_connection() as conn:
        execute_sql(
            conn,
            """
            INSERT INTO digest_sender_connections (
                provider,
                email_address,
                connection_type,
                token_path,
                scopes_json,
                metadata_json,
                created_at,
                updated_at
            ) VALUES (
                'gmail',
                :email_address,
                'oauth',
                NULL,
                :scopes_json,
                :metadata_json,
                :created_at,
                :updated_at
            )
            ON CONFLICT(provider, email_address) DO UPDATE SET
                scopes_json = excluded.scopes_json,
                metadata_json = excluded.metadata_json,
                updated_at = excluded.updated_at
            """,
            {
                "email_address": normalized_email,
                "scopes_json": json.dumps(scopes),
                "metadata_json": json.dumps(metadata, sort_keys=True),
                "created_at": now,
                "updated_at": now,
            },
        )
        connection = _fetch_digest_sender_connection(conn, email_address=normalized_email)
    if connection is None:
        raise RuntimeError("Digest sender connection could not be stored.")
    return digest_sender_connection_status(connection)


def get_gmail_digest_sender(email_address: str | None = None) -> dict | None:
    with get_connection() as conn:
        connection = _fetch_digest_sender_connection(conn, email_address=email_address)
    if connection is None:
        return None
    return digest_sender_connection_status(connection)


def digest_sender_admin_allowed_for_email(email_address: str) -> bool:
    allowed_emails = set(config.DIGEST_SENDER_ADMIN_EMAILS)
    if not allowed_emails:
        return True
    return email_address.strip().lower() in allowed_emails


def digest_sender_connection_status(connection: DigestSenderConnection) -> dict:
    status = {
        "provider": connection.provider,
        "email_address": connection.email_address,
        "has_send_scope": config.GMAIL_SEND_SCOPE in connection.scopes,
        "has_token": bool(connection.token_json),
        "auth_status": "connected",
        "auth_status_reason": None,
    }
    if not status["has_send_scope"]:
        status["auth_status"] = "reconnect_required"
        status["auth_status_reason"] = (
            "Digest sender credentials do not include Gmail send access. Reconnect the digest sender."
        )
    elif not status["has_token"]:
        status["auth_status"] = "reconnect_required"
        status["auth_status_reason"] = "Digest sender credentials are missing. Reconnect the digest sender."
    return status


def validate_gmail_digest_sender(email_address: str | None = None) -> dict | None:
    with get_connection() as conn:
        connection = _fetch_digest_sender_connection(conn, email_address=email_address)
        if connection is None:
            return None
        status = digest_sender_connection_status(connection)
        if status["auth_status"] != "connected":
            return status

        try:
            credentials = _credentials_for_connection(conn, connection)
        except DigestSenderAuthError as error:
            status["auth_status"] = "reconnect_required"
            status["auth_status_reason"] = str(error)
            return status

    status["auth_status"] = "connected" if credentials.valid else "reconnect_required"
    return status


def _credentials_for_connection(conn, connection: DigestSenderConnection):
    if config.GMAIL_SEND_SCOPE not in connection.scopes:
        raise DigestSenderAuthError(
            "Gmail digest sender credentials do not include send access. Reconnect the digest sender."
        )
    if not connection.token_json:
        raise DigestSenderAuthError(
            "Gmail digest sender credentials are missing. Reconnect the digest sender."
        )

    credentials = Credentials.from_authorized_user_info(
        json.loads(connection.token_json),
        [config.GMAIL_SEND_SCOPE],
    )
    if not credentials.valid:
        if not (credentials.expired and credentials.refresh_token):
            raise DigestSenderAuthError(
                "Gmail digest sender credentials are no longer valid. Reconnect the digest sender."
            )
        try:
            credentials.refresh(Request())
        except RefreshError as error:
            raise DigestSenderAuthError(
                "Gmail digest sender credentials were expired or revoked. Reconnect the digest sender."
            ) from error
        _update_digest_sender_token(
            conn,
            sender_id=connection.id,
            token_json=credentials.to_json(),
            token_source="database_refreshed",
        )
    return credentials


def build_gmail_digest_sender_service(email_address: str | None = None):
    with get_connection() as conn:
        connection = _fetch_digest_sender_connection(conn, email_address=email_address)
        if connection is None:
            expected = (email_address or config.GMAIL_SENDER_EMAIL).strip().lower()
            suffix = f" for {expected}" if expected else ""
            raise DigestSenderNotConfiguredError(
                f"Gmail digest sender has not been connected{suffix}."
            )
        credentials = _credentials_for_connection(conn, connection)

    return build("gmail", "v1", credentials=credentials)
