from __future__ import annotations

import json
from pathlib import Path

from _helpers import queue_snapshot, reset_database, sync_mock_messages


FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "backend"
    / "tests"
    / "fixtures"
    / "expected_queue_snapshot.json"
)


def main() -> int:
    expected = json.loads(FIXTURE_PATH.read_text())
    reset_database(remove_existing=True)
    sync_mock_messages()
    queue = queue_snapshot()
    account_order = [account["account_email"] for account in queue["accounts"]]
    category_order = [group["category"] for group in queue["accounts"][0]["groups"]]

    counts = {
        account["account_email"]: {
            group["category"]: group["count"] for group in account["groups"]
        }
        for account in queue["accounts"]
    }
    message_lookup = {
        message["subject"]: message
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    actual_total = sum(
        group["count"] for account in queue["accounts"] for group in account["groups"]
    )

    failures = []
    if account_order != expected["account_order"]:
        failures.append("account order mismatch")
    if category_order != expected["category_order"]:
        failures.append("category order mismatch")
    if actual_total != expected["total_messages"]:
        failures.append("total message count mismatch")
    for account_email, expected_counts in expected["accounts"].items():
        if counts.get(account_email) != expected_counts:
            failures.append(f"category counts mismatch for {account_email}")

    subject_to_selection = {
        message["subject"]: message["default_selected"]
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    for subject, expected_value in expected["sample_default_selected"].items():
        if subject_to_selection.get(subject) != expected_value:
            failures.append(f"default selected mismatch for {subject}")

    for subject, message_expectation in expected["message_expectations"].items():
        actual = message_lookup.get(subject)
        if actual is None:
            failures.append(f"missing expected subject {subject}")
            continue
        if actual["account_email"] != message_expectation["account_email"]:
            failures.append(f"account mismatch for {subject}")
        if actual["category"] != message_expectation["category"]:
            failures.append(f"category mismatch for {subject}")
        if actual["default_selected"] != message_expectation["default_selected"]:
            failures.append(f"default selected mismatch for {subject}")
        if actual["protected"] != message_expectation["protected"]:
            failures.append(f"protected flag mismatch for {subject}")
        tolerance = message_expectation.get("confidence_tolerance", 0.0)
        if abs(actual["confidence"] - message_expectation["confidence"]) > tolerance:
            failures.append(f"confidence mismatch for {subject}")

    if failures:
        print("FAIL queue snapshot comparison")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("PASS queue snapshot comparison")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
