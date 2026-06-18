from __future__ import annotations

import argparse

from _helpers import database
from app.services.gmail_write_planner import (
    plan_gmail_readonly_account_actions,
    plan_message_action,
)


def _print_plan(plan: dict) -> None:
    print(f"Account: {plan['account_email']}")
    print(f"Provider: {plan['provider']}")
    print(f"Message ID: {plan['message_id']}")
    print(f"Gmail Message ID: {plan['gmail_message_id']}")
    print(f"Subject: {plan['subject']}")
    print(f"Recommended action: {plan['recommended_action']}")
    print(f"Selected action: {plan['selected_action']}")
    print(f"Current labels: {', '.join(plan['current_labels']) or '(none)'}")
    print(f"Would add labels: {', '.join(plan['labels_to_add']) or '(none)'}")
    print(f"Would remove labels: {', '.join(plan['labels_to_remove']) or '(none)'}")
    print(f"Would preserve labels: {', '.join(plan['labels_to_preserve']) or '(none)'}")
    print(f"Protected: {'yes' if plan['protected'] else 'no'}")
    print(f"Allowed: {'yes' if plan['allowed'] else 'no'}")
    print("Safety notes:")
    for note in plan["safety_notes"]:
        print(f"  - {note}")
    print()


def _load_message_action_pairs_for_account(account_email: str) -> list[tuple[int, str]]:
    with database.get_connection() as conn:
        rows = conn.execute(
            """
            SELECT m.id, m.current_category
            FROM messages m
            JOIN accounts a ON a.email_address = m.account_email
            WHERE a.provider = 'gmail_readonly'
              AND m.account_email = ?
              AND m.reviewed = 0
            ORDER BY m.received_at DESC
            """,
            (account_email,),
        ).fetchall()
    return [(int(row["id"]), row["current_category"]) for row in rows]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Dry-run Gmail label/archive plans without making any Gmail writes."
    )
    parser.add_argument("--account", help="Limit dry-run output to one Gmail account email")
    parser.add_argument("--message-id", type=int, help="Plan a single message by local message id")
    parser.add_argument(
        "--action",
        choices=["keep", "bulk_mail", "junk_review", "trash", "needs_review"],
        help="Override action for --message-id",
    )
    args = parser.parse_args()

    if args.message_id is not None:
        if args.action is None:
            parser.error("--action is required when using --message-id")
        plan = plan_message_action(args.message_id, args.action)
        if plan is None:
            print(f"FAIL message {args.message_id} not found")
            return 1
        print("Fynish Gmail Write Dry Run")
        _print_plan(plan.to_dict())
        print("Result: 1 plan generated, 0 Gmail writes executed")
        return 0

    plans_payload = plan_gmail_readonly_account_actions(account_email=args.account)
    plans = plans_payload["plans"]

    print("Fynish Gmail Write Dry Run")
    if not plans:
        account_label = args.account or "all connected Gmail accounts"
        print(f"No unreviewed Gmail read-only messages found for {account_label}.")
        print("Result: 0 plans generated, 0 Gmail writes executed")
        return 0

    for plan in plans:
        _print_plan(plan)

    allowed_count = sum(1 for plan in plans if plan["allowed"])
    disallowed_count = len(plans) - allowed_count
    print(
        f"Result: {len(plans)} plans generated, {allowed_count} allowed, {disallowed_count} blocked, 0 Gmail writes executed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
