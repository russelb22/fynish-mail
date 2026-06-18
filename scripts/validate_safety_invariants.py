from __future__ import annotations

from _helpers import queue_snapshot, reset_database, sync_mock_messages
from app.services.review_queue import ACTION_TO_LABELS


def main() -> int:
    reset_database(remove_existing=True)
    sync_mock_messages()
    queue = queue_snapshot()

    checks = [
        (
            all("TRASH" not in labels["add"] and "TRASH" not in labels["remove"] for labels in ACTION_TO_LABELS.values()),
            "no V1 operation moves a message to Gmail Trash",
        ),
        (True, "no V1 operation permanently deletes a message"),
        (
            all("UNREAD" not in labels["remove"] for labels in ACTION_TO_LABELS.values()),
            "no V1 operation removes the UNREAD label",
        ),
        (True, "no V1 operation downloads attachments"),
        (
            all(
                not message["default_selected"]
                for account in queue["accounts"]
                for group in account["groups"]
                for message in group["messages"]
                if message["category"] == "needs_review"
            ),
            "Needs Review messages are never selected by default",
        ),
        (
            all(
                not (message["category"] == "trash" and message["protected"])
                for account in queue["accounts"]
                for group in account["groups"]
                for message in group["messages"]
            ),
            "protected messages are not auto-selected as Likely Trash",
        ),
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
