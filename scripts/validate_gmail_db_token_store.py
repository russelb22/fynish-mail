#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import GMAIL_TOKEN_STORAGE_MODE  # noqa: E402
from app.db.runtime import fetch_all, get_connection  # noqa: E402
from app.services.gmail_readonly import build_service_from_token_reference  # noqa: E402
from app.services.gmail_token_store import GmailTokenReference  # noqa: E402


def main() -> int:
    failures: list[str] = []
    checked = 0

    if GMAIL_TOKEN_STORAGE_MODE != "database":
        print(
            "ERROR: FYNISH_GMAIL_TOKEN_STORAGE_MODE must be set to 'database' for DB-token validation."
        )
        return 1

    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT
                pc.id AS provider_connection_id,
                ma.external_account_email AS account_email,
                pc.metadata_json
            FROM provider_connections pc
            JOIN mail_accounts ma ON ma.id = pc.mail_account_id
            WHERE pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = pc.mail_account_id
                  AND latest_pc.provider = pc.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
            )
              AND pc.provider = 'gmail_readonly'
            ORDER BY ma.external_account_email ASC
            """
        )

    for row in rows:
        metadata = json.loads(row["metadata_json"] or "{}")
        if "gmail_authorized_user_json" not in metadata:
            failures.append(f"{row['account_email']}: no DB-backed Gmail token blob present")
            continue

        reference = GmailTokenReference(
            provider_connection_id=int(row["provider_connection_id"]),
            token_path=None,
            metadata_json=row["metadata_json"],
            account_email=row["account_email"],
        )

        try:
            service = build_service_from_token_reference(reference)
            profile = service.users().getProfile(userId="me").execute()
            resolved_email = profile["emailAddress"].strip().lower()
            if resolved_email != row["account_email"].strip().lower():
                failures.append(
                    f"{row['account_email']}: DB-backed token resolved to {resolved_email}"
                )
                continue
            checked += 1
        except Exception as exc:
            failures.append(f"{row['account_email']}: {exc}")

    if failures:
        print("DB-backed Gmail token validation failed:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print(f"DB-backed Gmail token validation passed for {checked} account(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
