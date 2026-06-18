from __future__ import annotations

import json
from collections.abc import Mapping

from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection


def _parse_json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _coalesce_text(*values) -> str | None:
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return None


def deduplicate_provider_connections(conn=None) -> dict[str, int]:
    owned = conn is None
    if owned:
        with get_connection() as owned_conn:
            return deduplicate_provider_connections(owned_conn)

    duplicate_groups = fetch_all(
        conn,
        """
        SELECT mail_account_id, provider, COUNT(*) AS row_count
        FROM provider_connections
        GROUP BY mail_account_id, provider
        HAVING COUNT(*) > 1
        ORDER BY mail_account_id ASC, provider ASC
        """,
    )

    groups_processed = 0
    rows_deleted = 0

    for group in duplicate_groups:
        rows = fetch_all(
            conn,
            """
            SELECT *
            FROM provider_connections
            WHERE mail_account_id = :mail_account_id
              AND provider = :provider
            ORDER BY id ASC
            """,
            {
                "mail_account_id": group["mail_account_id"],
                "provider": group["provider"],
            },
        )
        if len(rows) < 2:
            continue

        keep_row = rows[-1]
        delete_rows = rows[:-1]

        merged_metadata: dict = {}
        for row in rows:
            merged_metadata.update(_parse_json_object(row["metadata_json"]))

        token_path = _coalesce_text(
            keep_row["token_path"],
            *[row["token_path"] for row in reversed(delete_rows)],
        )
        scopes_json = _coalesce_text(
            keep_row["scopes_json"],
            *[row["scopes_json"] for row in reversed(delete_rows)],
            "[]",
        )

        execute_sql(
            conn,
            """
            UPDATE provider_connections
            SET token_path = :token_path,
                scopes_json = :scopes_json,
                metadata_json = :metadata_json
            WHERE id = :provider_connection_id
            """,
            {
                "token_path": token_path,
                "scopes_json": scopes_json,
                "metadata_json": json.dumps(merged_metadata, sort_keys=True),
                "provider_connection_id": keep_row["id"],
            },
        )

        for row in delete_rows:
            execute_sql(
                conn,
                "DELETE FROM provider_connections WHERE id = :provider_connection_id",
                {"provider_connection_id": row["id"]},
            )
            rows_deleted += 1

        groups_processed += 1

    remaining_duplicates = int(
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
            """,
        )["count"]
    )

    return {
        "groups_processed": groups_processed,
        "rows_deleted": rows_deleted,
        "remaining_duplicate_groups": remaining_duplicates,
    }
