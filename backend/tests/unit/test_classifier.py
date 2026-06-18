from __future__ import annotations

from collections import Counter

from app.data.mock_messages import get_mock_messages
from app.services.classifier import classify_message


def _message(account_email: str, gmail_message_id: str) -> dict:
    for message in get_mock_messages(account_email):
        if message["gmail_message_id"] == gmail_message_id:
            return message
    raise AssertionError(f"Unknown mock message {gmail_message_id}")


def test_newsletter_with_list_unsubscribe_becomes_bulk_mail():
    result = classify_message(
        _message("personal@example.com", "p-1001"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.category == "bulk_mail"
    assert result.confidence >= 0.9


def test_suspicious_sender_becomes_likely_trash():
    result = classify_message(
        _message("personal@example.com", "p-1003"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.category == "trash"
    assert result.protected is False


def test_protected_message_is_not_classified_as_trash_without_rule():
    result = classify_message(
        _message("family@example.net", "f-3008"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.category in {"keep", "needs_review"}
    assert result.category != "trash"
    assert result.protected is True


def test_explicit_keep_rule_overrides_other_signals():
    result = classify_message(
        _message("personal@example.com", "p-1003"),
        rules=[
            {
                "id": 99,
                "enabled": True,
                "rule_type": "domain",
                "pattern": "sh1p-track-now.biz",
                "action": "keep",
            }
        ],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.category == "keep"
    assert result.matched_rule_ids == [99]
