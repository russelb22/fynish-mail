from __future__ import annotations

import json
import os
import sys
from urllib.error import URLError
from urllib.request import Request, urlopen


BASE_URL = os.getenv("FYNISH_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def request_json(path: str, method: str = "GET", payload: dict | None = None) -> dict:
    data = None if payload is None else json.dumps(payload).encode()
    request = Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    with urlopen(request) as response:
        return json.loads(response.read().decode())


def main() -> int:
    try:
        health = request_json("/api/health")
        sync = request_json("/api/sync/unread", method="POST")
        queue = request_json("/api/review-queue")
        reminders = request_json("/api/reminders/summary")
        notification_settings = request_json("/api/settings/notifications")
        rules = request_json("/api/rules")
    except URLError as exc:
        print(f"FAIL backend unreachable: {exc}")
        return 1

    checks = [
        (health.get("status") == "ok", "health endpoint reachable"),
        (sync.get("synced_messages") == 30, "sync endpoint returned success"),
        (len(queue.get("accounts", [])) >= 1, "review queue returned accounts"),
        (
            all("groups" in account for account in queue.get("accounts", [])),
            "review queue returned grouped categories",
        ),
        ("total_unprocessed" in reminders, "reminder summary returned total count"),
        ("settings" in notification_settings, "notification settings endpoint returned payload"),
        (isinstance(rules.get("rules"), list), "rules endpoint returned list"),
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
