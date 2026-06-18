from __future__ import annotations

import json

from app.db.database import get_connection
from app.db.provider_connection_cleanup import deduplicate_provider_connections


def test_deduplicate_provider_connections_keeps_latest_and_merges_metadata(isolated_db):
    now = "2026-05-11T00:00:00+00:00"
    with get_connection() as conn:
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
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, ?, ?, ?, ?, ?)
            """,
            (
                mail_account_id,
                "/tmp/old-token.json",
                '["scope-a"]',
                json.dumps({"old_only": "yes"}),
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, ?, ?, ?, ?, ?)
            """,
            (
                mail_account_id,
                "/tmp/new-token.json",
                '["scope-b"]',
                json.dumps({"gmail_authorized_user_json": '{"refresh_token":"abc"}'}),
                now,
                now,
            ),
        )

    result = deduplicate_provider_connections()

    assert result["groups_processed"] == 1
    assert result["rows_deleted"] == 1
    assert result["remaining_duplicate_groups"] == 0

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT token_path, scopes_json, metadata_json
            FROM provider_connections
            WHERE mail_account_id = ?
            ORDER BY id ASC
            """,
            (mail_account_id,),
        ).fetchall()

    assert len(rows) == 1
    assert rows[0]["token_path"] == "/tmp/new-token.json"
    assert rows[0]["scopes_json"] == '["scope-b"]'
    metadata = json.loads(rows[0]["metadata_json"])
    assert metadata["old_only"] == "yes"
    assert "gmail_authorized_user_json" in metadata
