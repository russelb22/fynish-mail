from __future__ import annotations

import json

from app.db.database import get_connection
from app.services.gmail_token_store import (
    GMAIL_TOKEN_JSON_METADATA_KEY,
    GmailTokenReference,
    load_connection_token_json,
    store_connection_token_json,
)


def test_load_connection_token_json_reads_metadata_blob():
    reference = GmailTokenReference(
        provider_connection_id=7,
        token_path=None,
        metadata_json=json.dumps({GMAIL_TOKEN_JSON_METADATA_KEY: '{"access_token":"abc"}'}),
        account_email="owner@example.com",
    )

    assert load_connection_token_json(reference) == '{"access_token":"abc"}'


def test_store_connection_token_json_updates_provider_connection_metadata(isolated_db):
    with get_connection() as conn:
        now = "2026-05-11T00:00:00+00:00"
        conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            ("owner@example.com", "Owner", now, now),
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            ("owner@example.com",),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', NULL, ?, ?)
            """,
            (user_id, "owner@example.com", "owner@example.com", now, now),
        )
        mail_account_id = conn.execute(
            "SELECT id FROM mail_accounts WHERE external_account_email = ?",
            ("owner@example.com",),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, ?, '[]', '{}', ?, ?)
            """,
            (mail_account_id, "/tmp/token.json", now, now),
        )
        provider_connection_id = conn.execute(
            "SELECT id FROM provider_connections WHERE mail_account_id = ?",
            (mail_account_id,),
        ).fetchone()["id"]

    store_connection_token_json(provider_connection_id, '{"refresh_token":"xyz"}')

    with get_connection() as conn:
        row = conn.execute(
            "SELECT metadata_json FROM provider_connections WHERE id = ?",
            (provider_connection_id,),
        ).fetchone()

    metadata = json.loads(row["metadata_json"])
    assert metadata[GMAIL_TOKEN_JSON_METADATA_KEY] == '{"refresh_token":"xyz"}'
