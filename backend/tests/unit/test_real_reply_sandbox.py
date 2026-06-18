from __future__ import annotations

from app.services.real_reply_sandbox import render_real_reply_packet, score_reply_candidate


def _row(**overrides):
    data = {
        "id": 42,
        "account_email": "personal@example.com",
        "sender": "Sender <sender@example.com>",
        "sender_domain": "example.com",
        "subject": "Can you review this?",
        "received_at": "2026-06-08T12:00:00+00:00",
        "body_preview": (
            "Could you please review the latest notes before Friday and let me know "
            "if the scope makes sense or if anything should be pulled out?"
        ),
        "current_category": "keep",
        "gmail_labels_json": '["INBOX","UNREAD"]',
    }
    data.update(overrides)
    return data


def test_score_reply_candidate_keeps_reply_worthy_message():
    candidate = score_reply_candidate(_row())

    assert candidate is not None
    assert candidate.score >= 80
    assert "reply_intent_marker" in candidate.reasons


def test_score_reply_candidate_rejects_bulk_message():
    candidate = score_reply_candidate(
        _row(
            subject="Weekly newsletter",
            body_preview="This newsletter has discount details and an unsubscribe link.",
            current_category="bulk_mail",
        )
    )

    assert candidate is None


def test_score_reply_candidate_rejects_link_heavy_investment_promo():
    candidate = score_reply_candidate(
        _row(
            sender="Promo <your@exclusive.premiumretiring.com>",
            sender_domain="exclusive.premiumretiring.com",
            subject="The 4-Day Countdown to SpaceX Wealth",
            body_preview=(
                "Click here for the largest IPO in stock market history. "
                "This urgent video reveals the ticker symbol. "
                "https://example.com https://example.com/2 https://example.com/3"
            ),
        )
    )

    assert candidate is None


def test_render_real_reply_packet_has_do_not_send_safety():
    candidate = score_reply_candidate(_row())
    assert candidate is not None

    packet = render_real_reply_packet(
        style_account="owner@example.com",
        style_profile="# Style\n\nBe clear.",
        candidate=candidate,
    )

    assert "Do not send anything" in packet
    assert "From: Sender <sender@example.com>" in packet
    assert "Return only a draft email body" in packet
