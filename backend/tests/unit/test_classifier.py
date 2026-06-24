from __future__ import annotations

from collections import Counter

from app.data.mock_messages import get_mock_messages, get_mock_spam_messages
from app.services.classifier import classify_message, classify_spam_rescue_candidate


def _message(account_email: str, gmail_message_id: str) -> dict:
    for message in get_mock_messages(account_email):
        if message["gmail_message_id"] == gmail_message_id:
            return message
    raise AssertionError(f"Unknown mock message {gmail_message_id}")


def _spam_message(account_email: str, gmail_message_id: str) -> dict:
    for message in get_mock_spam_messages(account_email):
        if message["gmail_message_id"] == gmail_message_id:
            return message
    raise AssertionError(f"Unknown mock spam message {gmail_message_id}")


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


def test_spam_rescue_surfaces_protected_invoice_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9001"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is True
    assert result.confidence >= 0.6
    assert result.protection_reasons
    assert any("Protected keywords" in reason for reason in result.reasons)


def test_spam_rescue_suppresses_obvious_prize_spam():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9002"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is False
    assert any("Spam-like urgency" in reason for reason in result.reasons)


def test_spam_rescue_suppresses_promotional_spam_without_rescue_signal():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9003"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is False
    assert any("Bulk-list headers" in reason for reason in result.reasons)


def test_spam_rescue_always_keep_rule_surfaces_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9002"),
        rules=[
            {
                "id": 101,
                "enabled": True,
                "rule_type": "domain",
                "pattern": "winner-promo.top",
                "action": "keep",
            }
        ],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is True
    assert result.matched_rule_ids == [101]
    assert "Explicit Always Keep rule matched" in result.reasons


def test_spam_rescue_prior_keep_history_surfaces_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9004"),
        rules=[],
        history_by_sender=Counter({"aunt.may@example.org:keep": 1}),
        history_by_domain=Counter(),
    )
    assert result.should_surface is True
    assert "Sender previously kept" in result.reasons


def test_spam_rescue_prior_domain_keep_history_surfaces_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9004"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter({"example.org:keep": 1}),
    )
    assert result.should_surface is True
    assert "Sender domain previously kept" in result.reasons


def test_spam_rescue_explicit_junk_rule_suppresses_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9001"),
        rules=[
            {
                "id": 202,
                "enabled": True,
                "rule_type": "domain",
                "pattern": "water.example.gov",
                "action": "junk_review",
            }
        ],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is False
    assert result.confidence == 0.95
    assert result.matched_rule_ids == [202]


def test_spam_rescue_disabled_keep_rule_does_not_surface_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9002"),
        rules=[
            {
                "id": 303,
                "enabled": False,
                "rule_type": "domain",
                "pattern": "winner-promo.top",
                "action": "keep",
            }
        ],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is False
    assert result.matched_rule_ids == []
    assert "Explicit Always Keep rule matched" not in result.reasons


def test_spam_rescue_disabled_junk_rule_does_not_suppress_candidate():
    result = classify_spam_rescue_candidate(
        _spam_message("personal@example.com", "ps-9001"),
        rules=[
            {
                "id": 404,
                "enabled": False,
                "rule_type": "domain",
                "pattern": "water.example.gov",
                "action": "junk_review",
            }
        ],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is True
    assert result.matched_rule_ids == []
    assert any("Protected keywords" in reason for reason in result.reasons)


def test_spam_rescue_surfaces_protected_candidate_with_moderate_risk_signal():
    result = classify_spam_rescue_candidate(
        _spam_message("work@example.com", "ws-9102"),
        rules=[],
        history_by_sender=Counter(),
        history_by_domain=Counter(),
    )
    assert result.should_surface is True
    assert result.protection_reasons
    assert any("Risk signals also present" in reason for reason in result.reasons)
