from __future__ import annotations

from app.services import ai_digest_summary


def _payload() -> dict:
    return {
        "window_display": "Jun 01, 2026 12:00 AM PDT to Jun 01, 2026 08:10 AM PDT",
        "processed_count": 1,
        "counts_by_action": {"keep": 1},
        "counts_by_source": {"manual": 1},
        "new_rules_count": 0,
        "queue_count": 2,
        "top_sender_domains": [
            {
                "sender_domain": "example.com",
                "message_count": 1,
                "counts_by_action": {"keep": 1},
                "counts_by_source": {"manual": 1},
                "sample_subjects": ["A useful message"],
            }
        ],
        "processed_messages": [
            {
                "account_email": "user@example.com",
                "sender": "Example Sender <sender@example.com>",
                "sender_domain": "example.com",
                "subject": "A useful message",
                "selected_action": "keep",
                "selected_action_label": "Keep",
                "action_source": "manual",
                "action_source_label": "Manual",
                "processed_at": "2026-06-01T15:10:00+00:00",
                "preview": "This is a short body preview.",
            }
        ],
    }


def test_build_digest_summary_input_includes_truncated_preview(monkeypatch):
    monkeypatch.setattr(ai_digest_summary.config, "OPENAI_DIGEST_MAX_INPUT_MESSAGES", 50)
    payload = _payload()
    payload["processed_messages"][0]["preview"] = "x" * 700

    summary_input = ai_digest_summary.build_digest_summary_input(
        payload,
        include_snippets=True,
    )

    message = summary_input["processed_messages"][0]
    assert message["preview"].endswith("…")
    assert len(message["preview"]) == ai_digest_summary.MAX_SNIPPET_LENGTH


def test_build_digest_summary_input_can_exclude_preview():
    summary_input = ai_digest_summary.build_digest_summary_input(
        _payload(),
        include_snippets=False,
    )

    assert "preview" not in summary_input["processed_messages"][0]


def test_build_digest_summary_input_includes_matching_domain_attention_notes():
    payload = _payload()
    payload["processed_messages"] = [
        {
            **payload["processed_messages"][0],
            "sender": "Example Security <alerts@example.net>",
            "sender_domain": "example.net",
            "subject": "Low Battery alert",
        },
        {
            **payload["processed_messages"][0],
            "sender": "Example Security <alerts@example.net>",
            "sender_domain": "example.net",
            "subject": "End-of-Bypass report",
        },
        {
            **payload["processed_messages"][0],
            "sender": "Example Security <alerts@example.net>",
            "sender_domain": "example.net",
            "subject": "Status update",
        },
        {
            **payload["processed_messages"][0],
            "sender": "Example Security <alerts@example.net>",
            "sender_domain": "example.net",
            "subject": "Fourth sample should be capped",
        },
    ]

    summary_input = ai_digest_summary.build_digest_summary_input(
        payload,
        include_snippets=False,
    )

    assert summary_input["domain_attention_notes"] == [
        {
            "domain": "example.net",
            "label": "Example Security",
            "note": (
                "Highlight only alarm/security conditions more severe than routine "
                "End-of-Bypass, Low Battery, status, or informational messages."
            ),
            "matched_message_count": 4,
            "sample_subjects": [
                "Low Battery alert",
                "End-of-Bypass report",
                "Status update",
            ],
        }
    ]


def test_build_digest_summary_input_omits_unmatched_domain_attention_notes():
    summary_input = ai_digest_summary.build_digest_summary_input(
        _payload(),
        include_snippets=True,
    )

    assert summary_input["domain_attention_notes"] == []


def test_build_ai_digest_summary_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(ai_digest_summary.config, "AI_DIGEST_SUMMARIES_ENABLED", False)

    result = ai_digest_summary.build_ai_digest_summary(
        _payload(),
        user_id=1,
        enabled_for_user=True,
    )

    assert result is None


def test_build_ai_digest_summary_returns_none_on_provider_failure(monkeypatch):
    monkeypatch.setattr(ai_digest_summary.config, "AI_DIGEST_SUMMARIES_ENABLED", True)
    monkeypatch.setattr(ai_digest_summary.config, "AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setattr(ai_digest_summary.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(
        ai_digest_summary,
        "get_enabled_ai_digest_attention_notes",
        lambda user_id: [],
    )

    def fail_provider(summary_input):
        raise RuntimeError("provider failed")

    monkeypatch.setattr(ai_digest_summary, "_call_openai_digest_summary", fail_provider)

    result = ai_digest_summary.build_ai_digest_summary(
        _payload(),
        user_id=1,
        enabled_for_user=True,
    )

    assert result is None


def test_build_ai_digest_summary_returns_structured_summary(monkeypatch):
    monkeypatch.setattr(ai_digest_summary.config, "AI_DIGEST_SUMMARIES_ENABLED", True)
    monkeypatch.setattr(ai_digest_summary.config, "AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setattr(ai_digest_summary.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ai_digest_summary.config, "OPENAI_DIGEST_MODEL", "gpt-5-mini")
    monkeypatch.setattr(
        ai_digest_summary,
        "get_enabled_ai_digest_attention_notes",
        lambda user_id: [],
    )

    def fake_provider(summary_input):
        assert summary_input["processed_messages"][0]["preview"]
        return {
            "headline": "Mostly routine mail.",
            "summary": "Fynish processed one kept message.",
            "key_takeaways": ["One useful-looking message was kept."],
            "auto_clean_review": {
                "count": 0,
                "summary": "No messages were auto-cleaned.",
                "notable_items": [],
            },
            "notable_kept_messages": [],
            "top_noise_sources": [],
            "caveats": ["Based on digest metadata and snippets."],
        }

    monkeypatch.setattr(ai_digest_summary, "_call_openai_digest_summary", fake_provider)

    result = ai_digest_summary.build_ai_digest_summary(
        _payload(),
        user_id=1,
        enabled_for_user=True,
    )

    assert result["provider"] == "openai"
    assert result["model"] == "gpt-5-mini"
    assert result["headline"] == "Mostly routine mail."
