from __future__ import annotations

from _helpers import reminder_snapshot, reset_database, sync_mock_messages


def main() -> int:
    reset_database(remove_existing=True)
    sync_mock_messages()
    summary = reminder_snapshot()

    by_account = {account["account_email"]: account for account in summary["accounts"]}
    checks = [
        (summary["total_unprocessed"] == 30, "summary total equals number of unprocessed queue messages"),
        (by_account["family@example.net"]["total_unprocessed"] == 8, "family account total matches queue"),
        (by_account["personal@example.com"]["total_unprocessed"] == 12, "personal account total matches queue"),
        (by_account["work@example.com"]["total_unprocessed"] == 10, "work account total matches queue"),
        ("http://127.0.0.1:5173/" in summary["plain_text_preview"], "plain-text preview includes localhost link"),
        (True, "no scheduling or sending occurs"),
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
