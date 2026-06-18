from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.runtime import execute_sql, fetch_one, get_connection


GMAIL_TOKEN_JSON_METADATA_KEY = "gmail_authorized_user_json"
GMAIL_TOKEN_SOURCE_METADATA_KEY = "gmail_token_source"


def _parse_metadata(metadata_json: str | None) -> dict[str, Any]:
    if not metadata_json:
        return {}
    try:
        value = json.loads(metadata_json)
    except json.JSONDecodeError:
        return {}
    return value if isinstance(value, dict) else {}


def _serialize_metadata(metadata: dict[str, Any]) -> str:
    return json.dumps(metadata, sort_keys=True)


def _load_connection_metadata(
    provider_connection_id: int,
    *,
    conn,
) -> dict[str, Any]:
    row = fetch_one(
        conn,
        "SELECT metadata_json FROM provider_connections WHERE id = :provider_connection_id",
        {"provider_connection_id": provider_connection_id},
    )
    if row is None:
        raise RuntimeError(
            f"Provider connection {provider_connection_id} not found for Gmail token storage."
        )
    return _parse_metadata(row["metadata_json"])


@dataclass(frozen=True)
class GmailTokenReference:
    provider_connection_id: int | None
    token_path: str | None
    metadata_json: str | None = None
    account_email: str | None = None

    @classmethod
    def from_row(cls, row: Any) -> "GmailTokenReference":
        provider_connection_id = row["provider_connection_id"] if "provider_connection_id" in row.keys() else None
        token_path = row["token_path"] if "token_path" in row.keys() else None
        metadata_json = row["metadata_json"] if "metadata_json" in row.keys() else None
        account_email = row["account_email"] if "account_email" in row.keys() else None
        return cls(
            provider_connection_id=int(provider_connection_id) if provider_connection_id is not None else None,
            token_path=str(token_path) if token_path else None,
            metadata_json=str(metadata_json) if metadata_json else None,
            account_email=str(account_email) if account_email else None,
        )

    def metadata(self) -> dict[str, Any]:
        return _parse_metadata(self.metadata_json)

    def token_json(self) -> str | None:
        metadata = self.metadata()
        token_json = metadata.get(GMAIL_TOKEN_JSON_METADATA_KEY)
        return token_json if isinstance(token_json, str) and token_json else None


def load_connection_token_json(reference: GmailTokenReference) -> str | None:
    return reference.token_json()


def store_connection_token_json(
    provider_connection_id: int,
    token_json: str,
    *,
    token_source: str = "database",
    conn=None,
) -> None:
    if conn is None:
        with get_connection() as owned_conn:
            store_connection_token_json(
                provider_connection_id,
                token_json,
                token_source=token_source,
                conn=owned_conn,
            )
        return

    metadata = _load_connection_metadata(provider_connection_id, conn=conn)
    metadata[GMAIL_TOKEN_JSON_METADATA_KEY] = token_json
    metadata[GMAIL_TOKEN_SOURCE_METADATA_KEY] = token_source
    execute_sql(
        conn,
        """
        UPDATE provider_connections
        SET metadata_json = :metadata_json
        WHERE id = :provider_connection_id
        """,
        {
            "metadata_json": _serialize_metadata(metadata),
            "provider_connection_id": provider_connection_id,
        },
    )


def update_connection_metadata(
    provider_connection_id: int,
    values: dict[str, Any],
    *,
    conn=None,
) -> None:
    if conn is None:
        with get_connection() as owned_conn:
            update_connection_metadata(
                provider_connection_id,
                values,
                conn=owned_conn,
            )
        return

    metadata = _load_connection_metadata(provider_connection_id, conn=conn)
    metadata.update(values)
    execute_sql(
        conn,
        """
        UPDATE provider_connections
        SET metadata_json = :metadata_json
        WHERE id = :provider_connection_id
        """,
        {
            "metadata_json": _serialize_metadata(metadata),
            "provider_connection_id": provider_connection_id,
        },
    )


def load_file_token_json(token_path: str) -> str:
    return Path(token_path).read_text(encoding="utf-8")
