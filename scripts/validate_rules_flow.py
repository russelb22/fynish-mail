from __future__ import annotations

from _helpers import database, queue_snapshot, reclassify_queue, reset_database, sync_mock_messages
from app.services.review_queue import apply_message_action
from app.services.rules import create_rule


def main() -> int:
    reset_database(remove_existing=True)
    sync_mock_messages()

    with database.get_connection() as conn:
        source = conn.execute(
            """
            SELECT id, subject
            FROM messages
            WHERE sender_domain = 'fixer-mailer.com'
            LIMIT 1
            """
        ).fetchone()

    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "created_from_message_id": str(source["id"]),
        }
    )
    reclassified = reclassify_queue()
    applied = apply_message_action(int(source["id"]), "bulk_mail")
    queue = queue_snapshot()

    subjects = {
        message["subject"]
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }

    with database.get_connection() as conn:
        rule_row = conn.execute(
            "SELECT match_count, last_matched_at FROM rules WHERE id = ?",
            (rule["id"],),
        ).fetchone()
        log_row = conn.execute(
            "SELECT COUNT(*) AS count FROM actions_log WHERE gmail_message_id = ?",
            ("f-3007",),
        ).fetchone()

    checks = [
        (rule["rule_type"] == "domain", "quick rules default to domain matching"),
        (applied["selected_action"] == "bulk_mail", "source message is acted upon"),
        (source["subject"] not in subjects, "source message disappears from queue"),
        (reclassified["reclassified_messages"] == 30, "pending queue is reclassified"),
        (rule_row["match_count"] >= 1, "rule match_count updates"),
        (rule_row["last_matched_at"] is not None, "rule last_matched_at updates"),
        (log_row["count"] >= 1, "action is logged"),
    ]

    passed = 0
    for ok, label in checks:
        print(f"{'PASS' if ok else 'FAIL'} {label}")
        passed += 1 if ok else 0
    failed = len(checks) - passed
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
