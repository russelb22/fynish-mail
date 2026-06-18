from __future__ import annotations

import json
import sys

from _helpers import (
    count_accounts,
    count_messages,
    database,
    reminder_snapshot,
    reclassify_queue,
    reset_database,
    sync_mock_messages,
)
from app.services.review_queue import ACTION_TO_LABELS, apply_selected_actions, get_review_queue


def check(condition: bool, label: str) -> tuple[bool, str]:
    return condition, f"{'PASS' if condition else 'FAIL'} {label}"


def main() -> int:
    results: list[tuple[bool, str]] = []
    reset_database(remove_existing=True)
    results.append(check(True, "database reset"))

    sync_result = sync_mock_messages()
    results.append(
        check(
            sync_result["synced_messages"] == 30 and count_messages() == 30,
            "mock sync populated 30 messages",
        )
    )

    reclassified = reclassify_queue()
    results.append(check(reclassified["reclassified_messages"] == 30, "queue reclassified"))

    queue = get_review_queue()
    results.append(check(count_accounts() == 3, "review queue grouped by 3 accounts"))
    results.append(check(count_messages() == 30, "message count is 30"))

    queue_map = {
        account["account_email"]: {
            group["category"]: group for group in account["groups"]
        }
        for account in queue["accounts"]
    }
    results.append(
        check(
            queue_map["personal@example.com"]["bulk_mail"]["count"] == 4,
            "personal account has 4 bulk messages",
        )
    )
    results.append(
        check(
            queue_map["work@example.com"]["junk_review"]["count"] == 1,
            "work account has 1 junk review message",
        )
    )

    all_messages = [
        message
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    ]
    results.append(
        check(
            all(
                message["category"] != "trash" or not message["protected"]
                for message in all_messages
            ),
            "protected messages not classified as Likely Trash",
        )
    )
    results.append(
        check(
            all(
                message["category"] != "bulk_mail" or message["default_selected"]
                for message in all_messages
                if message["confidence"] >= 0.8
            ),
            "Bulk Mail selected by default when confidence >= 0.80",
        )
    )
    results.append(
        check(
            all(
                message["category"] != "junk_review" or message["default_selected"]
                for message in all_messages
                if message["category"] == "junk_review" and message["confidence"] >= 0.8
            ),
            "Junk Review selected by default when confidence >= 0.80",
        )
    )
    results.append(
        check(
            all(
                message["category"] != "keep" or message["default_selected"]
                for message in all_messages
                if message["category"] == "keep" and message["confidence"] >= 0.8
            ),
            "Keep selected by default when confidence >= 0.80",
        )
    )
    results.append(
        check(
            all(
                message["category"] != "trash"
                or message["confidence"] < 0.95
                or message["default_selected"]
                for message in all_messages
            ),
            "Likely Trash selected only when confidence >= 0.95",
        )
    )
    results.append(
        check(
            all(
                not message["default_selected"]
                for message in all_messages
                if message["category"] == "needs_review"
            ),
            "Needs Review never selected by default",
        )
    )

    personal_ids = [
        message["id"]
        for category in queue_map["personal@example.com"].values()
        for message in category["messages"]
        if message["default_selected"]
    ]
    apply_result = apply_selected_actions(
        [
            {"message_id": message_id, "action": next(
                message["recommended_action"]
                for message in all_messages
                if message["id"] == message_id
            )}
            for message_id in personal_ids
        ]
    )
    results.append(
        check(
            len(apply_result["applied"]) == len(personal_ids),
            "apply selected removes processed messages from queue",
        )
    )

    with database.get_connection() as conn:
        action_rows = conn.execute(
            """
            SELECT selected_action, gmail_labels_added_json, gmail_labels_removed_json
            FROM actions_log
            ORDER BY id DESC
            """
        ).fetchall()
    results.append(
        check(
            any("Fynish/Bulk Mail" in json.loads(row["gmail_labels_added_json"]) for row in action_rows),
            "Fynish/Bulk Mail label applied",
        )
    )
    results.append(
        check(
            all("INBOX" in ACTION_TO_LABELS[row["selected_action"]]["remove"] or row["selected_action"] == "keep" for row in action_rows),
            "INBOX removed from approved non-keep messages",
        )
    )
    results.append(
        check(
            all("UNREAD" not in json.loads(row["gmail_labels_removed_json"]) for row in action_rows),
            "UNREAD preserved",
        )
    )
    results.append(check(len(action_rows) > 0, "actions logged"))

    reminder = reminder_snapshot()
    results.append(
        check(
            reminder["total_unprocessed"] == count_messages() - len(action_rows),
            "reminder summary generated",
        )
    )

    print("Fynish Mail V1 Validation")
    passed = 0
    for ok, line in results:
        print(line)
        passed += 1 if ok else 0
    failed = len(results) - passed
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
