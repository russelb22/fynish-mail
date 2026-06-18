from __future__ import annotations

import json
from pathlib import Path

from _helpers import database
from app.core.config import GOOGLE_CLIENT_SECRETS_PATH
from app.services.review_queue import get_review_queue, sync_unread_messages


def check(condition: bool, label: str) -> tuple[bool, str]:
    return condition, f"{'PASS' if condition else 'FAIL'} {label}"


def main() -> int:
    results: list[tuple[bool, str]] = []

    results.append(
        check(
            GOOGLE_CLIENT_SECRETS_PATH.exists(),
            f"Google OAuth client file exists at {GOOGLE_CLIENT_SECRETS_PATH}",
        )
    )

    with database.get_connection() as conn:
        gmail_accounts = conn.execute(
            """
            SELECT a.id, a.email_address, a.enabled, a.last_sync_at, g.token_path
            FROM accounts a
            JOIN gmail_account_connections g ON g.account_id = a.id
            WHERE a.provider = 'gmail_readonly'
            ORDER BY a.email_address ASC
            """
        ).fetchall()

        before_action_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM actions_log
                WHERE account_email IN (
                    SELECT email_address FROM accounts WHERE provider = 'gmail_readonly'
                )
                """
            ).fetchone()["count"]
        )
    results.append(check(len(gmail_accounts) >= 1, "at least one Gmail read-only account is connected"))

    if not gmail_accounts:
        print("Fynish Gmail Read-Only Validation")
        for ok, line in results:
            print(line)
        print("Result: 1 passed, 1 failed")
        return 1

    results.append(
        check(
            all(bool(row["enabled"]) for row in gmail_accounts),
            "connected Gmail read-only accounts are enabled",
        )
    )
    results.append(
        check(
            all(bool(row["token_path"]) for row in gmail_accounts),
            "connected Gmail read-only accounts have stored token paths",
        )
    )
    results.append(
        check(
            all(Path(row["token_path"]).exists() for row in gmail_accounts),
            "stored Gmail token files exist locally",
        )
    )

    sync_result = sync_unread_messages()
    queue = get_review_queue()

    with database.get_connection() as conn:
        after_action_count = int(
            conn.execute(
                """
                SELECT COUNT(*) AS count
                FROM actions_log
                WHERE account_email IN (
                    SELECT email_address FROM accounts WHERE provider = 'gmail_readonly'
                )
                """
            ).fetchone()["count"]
        )
        duplicates = conn.execute(
            """
            SELECT account_email, gmail_message_id, COUNT(*) AS duplicate_count
            FROM messages
            WHERE account_email IN (
                SELECT email_address FROM accounts WHERE provider = 'gmail_readonly'
            )
            GROUP BY account_email, gmail_message_id
            HAVING COUNT(*) > 1
            """
        ).fetchall()
        imported_rows = conn.execute(
            """
            SELECT account_email, gmail_message_id, sender, subject, snippet, body_preview, gmail_labels_json
            FROM messages
            WHERE account_email IN (
                SELECT email_address FROM accounts WHERE provider = 'gmail_readonly'
            )
            ORDER BY account_email ASC, received_at DESC
            """
        ).fetchall()

    results.append(check(sync_result["synced_messages"] >= len(gmail_accounts), "sync completed for Gmail read-only accounts"))
    results.append(check(after_action_count == before_action_count, "sync does not create Gmail action-log entries"))
    results.append(check(len(imported_rows) >= 1, "at least one real Gmail message is stored locally"))
    results.append(check(len(duplicates) == 0, "repeat sync does not create duplicate Gmail message rows"))
    results.append(
        check(
            all("INBOX" in json.loads(row["gmail_labels_json"]) for row in imported_rows),
            "imported Gmail rows preserve the INBOX label in stored state",
        )
    )
    results.append(
        check(
            all("UNREAD" in json.loads(row["gmail_labels_json"]) for row in imported_rows),
            "imported Gmail rows preserve the UNREAD label in stored state",
        )
    )
    results.append(
        check(
            all(bool(row["sender"]) and bool(row["subject"]) for row in imported_rows),
            "imported Gmail rows include sender and subject",
        )
    )
    results.append(
        check(
            all(bool((row["snippet"] or "").strip()) or bool((row["body_preview"] or "").strip()) for row in imported_rows),
            "imported Gmail rows include snippet or body preview text",
        )
    )

    gmail_queue_accounts = [
        account
        for account in queue["accounts"]
        if any(account["account_email"] == row["email_address"] for row in gmail_accounts)
    ]
    results.append(
        check(
            len(gmail_queue_accounts) == len(gmail_accounts),
            "review queue includes each connected Gmail read-only account",
        )
    )

    print("Fynish Gmail Read-Only Validation")
    passed = 0
    for ok, line in results:
        print(line)
        passed += 1 if ok else 0
    failed = len(results) - passed
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
