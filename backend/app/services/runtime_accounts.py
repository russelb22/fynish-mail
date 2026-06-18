from __future__ import annotations

from app.db.runtime import fetch_one


def fetch_runtime_account_connection(
    conn,
    account_email: str,
    *,
    provider: str | None = None,
):
    params: dict[str, object] = {"account_email": account_email}
    provider_filter = ""
    if provider is not None:
        provider_filter = "AND ma.provider = :provider"
        params["provider"] = provider

    row = fetch_one(
        conn,
        f"""
        SELECT
            ma.provider,
            ma.id AS mail_account_id,
            pc.id AS provider_connection_id,
            pc.token_path,
            COALESCE(pc.scopes_json, '[]') AS scopes_json,
            pc.metadata_json,
            ma.external_account_email AS account_email
        FROM mail_accounts ma
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
          {provider_filter}
        ORDER BY ma.id DESC
        LIMIT 1
        """,
        params,
    )
    if row is not None:
        return row

    legacy_params: dict[str, object] = {"account_email": account_email}
    legacy_provider_filter = ""
    if provider is not None:
        legacy_provider_filter = "AND a.provider = :provider"
        legacy_params["provider"] = provider

    return fetch_one(
        conn,
        f"""
        SELECT
            a.provider,
            NULL AS mail_account_id,
            NULL AS provider_connection_id,
            g.token_path,
            COALESCE(g.scopes_json, '[]') AS scopes_json,
            NULL AS metadata_json,
            a.email_address AS account_email
        FROM accounts a
        LEFT JOIN gmail_account_connections g ON g.account_id = a.id
        WHERE a.email_address = :account_email
          {legacy_provider_filter}
        ORDER BY a.id DESC
        LIMIT 1
        """,
        legacy_params,
    )


def fetch_runtime_message_with_provider(conn, message_id: int):
    return fetch_one(
        conn,
        """
        SELECT
            m.*,
            COALESCE(ma.provider, a.provider, 'unknown') AS provider
        FROM messages m
        LEFT JOIN mail_accounts ma
          ON ma.id = m.mail_account_id
        LEFT JOIN accounts a
          ON a.email_address = m.account_email
         AND (ma.id IS NULL OR a.provider = ma.provider)
        WHERE m.id = :message_id
        """,
        {"message_id": message_id},
    )
