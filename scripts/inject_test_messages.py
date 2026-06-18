from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from _helpers import database
from app.data.test_message_scenarios import build_bundle, build_scenario, bundle_names, scenario_names
from app.services.review_queue import (
    _auto_apply_rule_match,
    _history_counters,
    _load_rules,
    _should_auto_apply_rule_match,
    _upsert_classified_message,
)


def ensure_mock_account(account_email: str) -> dict:
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        row = conn.execute(
            "SELECT * FROM accounts WHERE email_address = ?",
            (account_email,),
        ).fetchone()
        if row is None:
            conn.execute(
                """
                INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
                VALUES (?, 1, 'mock_gmail', ?, ?)
                """,
                (account_email, now, now),
            )
            row = conn.execute(
                "SELECT * FROM accounts WHERE email_address = ?",
                (account_email,),
            ).fetchone()
    return dict(row)


def build_message(account_email: str, scenario: dict, sequence: int) -> dict:
    received_at = (datetime.now(timezone.utc) - timedelta(minutes=sequence)).isoformat()
    suffix = uuid4().hex[:10]
    return {
        "gmail_message_id": f"t-{suffix}-{sequence}",
        "gmail_thread_id": f"tt-{suffix}-{sequence}",
        "sender": scenario["sender"],
        "reply_to": scenario["reply_to"],
        "recipient_to": account_email,
        "recipient_cc": "",
        "subject": scenario["subject"],
        "received_at": received_at,
        "snippet": scenario["snippet"],
        "body_preview": scenario["body_preview"],
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": scenario["headers"],
        "has_attachments": scenario["has_attachments"],
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Inject made-up test emails into a mock account using the real classifier and rule path."
    )
    parser.add_argument(
        "--account",
        default="test-lab@example.local",
        help="Mock account to inject into. Created automatically if missing.",
    )
    parser.add_argument(
        "--scenario",
        choices=scenario_names(),
        help="Single named scenario to inject.",
    )
    parser.add_argument(
        "--bundle",
        choices=bundle_names(),
        default="mixed",
        help="Scenario bundle to inject when --scenario is not used. Defaults to mixed.",
    )
    parser.add_argument(
        "--repeat",
        type=int,
        default=1,
        help="How many copies of the selected scenario or bundle to inject.",
    )
    args = parser.parse_args()

    if args.repeat < 1:
        raise SystemExit("--repeat must be at least 1")

    if args.scenario:
        base_messages = [build_scenario(args.scenario)]
    else:
        base_messages = build_bundle(args.bundle)

    account = ensure_mock_account(args.account)
    now = datetime.now(timezone.utc).isoformat()

    with database.get_connection() as conn:
        rules = _load_rules(conn)
        history_by_sender, history_by_domain = _history_counters(conn)
        inserted = 0
        auto_applied = 0
        categories: dict[str, int] = {}

        sequence = 0
        for _ in range(args.repeat):
            for scenario in base_messages:
                message = build_message(args.account, scenario, sequence)
                sequence += 1
                message_id, classification, preserve_reviewed = _upsert_classified_message(
                    conn=conn,
                    account_email=args.account,
                    message=message,
                    now=now,
                    rules=rules,
                    history_by_sender=history_by_sender,
                    history_by_domain=history_by_domain,
                    reset_reviewed=False,
                )
                inserted += 1
                categories[classification.category] = categories.get(classification.category, 0) + 1
                if _should_auto_apply_rule_match(classification, preserve_reviewed):
                    if _auto_apply_rule_match(account, message_id, classification, conn):
                        auto_applied += 1

        conn.execute(
            "UPDATE accounts SET last_sync_at = ?, updated_at = ? WHERE email_address = ?",
            (now, now, args.account),
        )

    print("Fynish Synthetic Email Injection")
    print(f"Account: {args.account}")
    print(f"Inserted: {inserted}")
    print(f"Auto-applied by rules: {auto_applied}")
    print("Categories:")
    for category, count in sorted(categories.items()):
        print(f"  - {category}: {count}")
    print("Done.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
