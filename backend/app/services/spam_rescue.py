from __future__ import annotations

from app.data.mock_messages import get_mock_spam_messages
from app.db.runtime import get_connection
from app.services.classifier import (
    classify_spam_rescue_candidate,
    extract_domain,
)
from app.services.provider_models import MailAccountRecord
from app.services.review_queue import (
    _enabled_mail_accounts,
    _history_counters,
    _load_rules,
)


def _build_candidate_payload(account_email: str, message: dict, result) -> dict:
    return {
        "id": f"{account_email}:{message['gmail_message_id']}",
        "gmail_message_id": message["gmail_message_id"],
        "thread_id": message["gmail_thread_id"],
        "account_email": account_email,
        "sender": message["sender"],
        "sender_domain": extract_domain(message["sender"]),
        "reply_to": message["reply_to"],
        "subject": message["subject"],
        "received_at": message["received_at"],
        "snippet": message["snippet"],
        "body_preview": message["body_preview"],
        "has_attachments": bool(message["has_attachments"]),
        "source_label": "spam",
        "review_surface": "spam_rescue",
        "state_version": message["received_at"],
        "confidence": result.confidence,
        "rescue_reasons": result.reasons,
        "protection_reasons": result.protection_reasons,
        "matched_rule_ids": result.matched_rule_ids,
    }


def get_spam_rescue_queue(user_id: int | None = None) -> dict:
    with get_connection() as conn:
        accounts = _enabled_mail_accounts(conn, user_id=user_id)
        rules = _load_rules(conn)
        if user_id is not None:
            rules = [rule for rule in rules if rule.get("user_id") == user_id]
        history_by_sender, history_by_domain = _history_counters(conn, user_id=user_id)

        result_accounts = []
        total_count = 0
        for account in accounts:
            account_record = MailAccountRecord.from_row(account)
            messages = []
            for message in get_mock_spam_messages(account_record.account_email):
                result = classify_spam_rescue_candidate(
                    message=message,
                    rules=rules,
                    history_by_sender=history_by_sender,
                    history_by_domain=history_by_domain,
                )
                if not result.should_surface:
                    continue
                messages.append(
                    _build_candidate_payload(
                        account_record.account_email,
                        message,
                        result,
                    )
                )

            messages.sort(
                key=lambda item: (item["confidence"], item["received_at"]),
                reverse=True,
            )
            total_count += len(messages)
            result_accounts.append(
                {
                    "account_email": account_record.account_email,
                    "last_sync_at": account_record.last_sync_at,
                    "count": len(messages),
                    "messages": messages,
                }
            )

    return {"accounts": result_accounts, "count": total_count}
