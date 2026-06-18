from __future__ import annotations

from datetime import datetime, timezone

from app.core.config import FRONTEND_URL
from app.db.runtime import fetch_all, fetch_one, get_connection
from app.services.review_queue import CATEGORY_META


def _build_plain_text_preview(accounts: list[dict], total_unprocessed: int) -> str:
    lines = [
        "Fynish reminder",
        "",
        f"Total unprocessed messages: {total_unprocessed}",
        "",
    ]

    if total_unprocessed == 0:
        lines.append("No unprocessed queue items right now.")
    else:
        for account in accounts:
            lines.append(
                f"{account['account_email']} ({account['total_unprocessed']} unprocessed)"
            )
            for category in account["categories"]:
                if category["count"] > 0:
                    lines.append(f"- {category['display_name']}: {category['count']}")
            lines.append("")

    lines.append(f"Open Fynish: {FRONTEND_URL}")
    return "\n".join(lines).strip()


def get_reminder_summary(user_id: int | None = None) -> dict:
    generated_at = datetime.now(timezone.utc).isoformat()
    accounts_payload: list[dict] = []
    total_unprocessed = 0

    with get_connection() as conn:
        if user_id is None:
            accounts = fetch_all(
                conn,
                "SELECT email_address FROM accounts WHERE enabled = 1 ORDER BY email_address ASC",
            )
        else:
            accounts = fetch_all(
                conn,
                """
                SELECT external_account_email AS email_address
                FROM mail_accounts
                WHERE user_id = :user_id
                  AND enabled = 1
                ORDER BY external_account_email ASC
                """,
                {"user_id": user_id},
            )

        for account in accounts:
            category_summaries = []
            account_total = 0

            for category, display_name in CATEGORY_META:
                row = fetch_one(
                    conn,
                    """
                    SELECT COUNT(*) AS count
                    FROM messages
                    WHERE account_email = :account_email
                      AND reviewed = 0
                      AND current_category = :category
                    """,
                    {"account_email": account["email_address"], "category": category},
                )
                count = int(row["count"])
                account_total += count
                category_summaries.append(
                    {
                        "category": category,
                        "display_name": display_name,
                        "count": count,
                    }
                )

            total_unprocessed += account_total
            accounts_payload.append(
                {
                    "account_email": account["email_address"],
                    "total_unprocessed": account_total,
                    "categories": category_summaries,
                }
            )

    plain_text_preview = _build_plain_text_preview(accounts_payload, total_unprocessed)

    return {
        "generated_at": generated_at,
        "localhost_url": FRONTEND_URL,
        "total_unprocessed": total_unprocessed,
        "accounts": accounts_payload,
        "plain_text_preview": plain_text_preview,
    }
