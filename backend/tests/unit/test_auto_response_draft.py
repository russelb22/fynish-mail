from __future__ import annotations

from pathlib import Path

import pytest

from app.services import auto_response_draft


def _message_row() -> dict:
    return {
        "id": 42,
        "account_email": "owner@example.com",
        "sender": "Mongie <mongie@example.com>",
        "sender_domain": "example.com",
        "reply_to": "",
        "subject": "Address field update",
        "received_at": "2026-06-08T21:16:52+00:00",
        "snippet": "Has there been any progress?",
        "body_preview": "Has there been any progress or updates on the UKG data fix for the Address fields?",
    }


def test_build_auto_response_input_bounds_user_guidance():
    draft_input = auto_response_draft.build_auto_response_input(
        _message_row(),
        user_guidance="x" * 2000,
        writing_style_card="Be practical.",
    )

    assert draft_input["message"]["subject"] == "Address field update"
    assert draft_input["output_constraints"]["do_not_send"] is True
    assert draft_input["user_guidance"].endswith("...")
    assert len(draft_input["user_guidance"]) == auto_response_draft.MAX_USER_GUIDANCE_LENGTH


def test_load_writing_style_card_uses_local_file(monkeypatch, tmp_path: Path):
    monkeypatch.setattr(auto_response_draft.config, "DATA_DIR", tmp_path)
    style_dir = tmp_path / "writing_samples" / "owner_example.com"
    style_dir.mkdir(parents=True)
    (style_dir / "writing_style_card.md").write_text("Write like owner.", encoding="utf-8")

    style_card, path, card_id = auto_response_draft.load_writing_style_card("owner@example.com")

    assert style_card == "Write like owner."
    assert path is not None
    assert card_id is None


def test_auto_response_drafts_allowed_for_email_uses_feature_gate(monkeypatch):
    monkeypatch.setattr(auto_response_draft.config, "AUTO_RESPONSE_DRAFTS_ENABLED", False)
    monkeypatch.setattr(auto_response_draft.config, "AUTO_RESPONSE_DRAFT_ALLOWED_USER_EMAILS", [])

    assert auto_response_draft.auto_response_drafts_allowed_for_email("owner@example.com") is False

    monkeypatch.setattr(auto_response_draft.config, "AUTO_RESPONSE_DRAFTS_ENABLED", True)
    assert auto_response_draft.auto_response_drafts_allowed_for_email("owner@example.com") is True

    monkeypatch.setattr(
        auto_response_draft.config,
        "AUTO_RESPONSE_DRAFT_ALLOWED_USER_EMAILS",
        ["owner@example.com"],
    )
    assert auto_response_draft.auto_response_drafts_allowed_for_email("OWNER@example.com") is True
    assert auto_response_draft.auto_response_drafts_allowed_for_email("friend@example.com") is False


def test_generate_auto_response_draft_uses_fake_provider(monkeypatch):
    monkeypatch.setattr(auto_response_draft.config, "AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setattr(auto_response_draft.config, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(auto_response_draft.config, "OPENAI_AUTO_RESPONSE_MODEL", "gpt-test")
    monkeypatch.setattr(
        auto_response_draft,
        "_fetch_message",
        lambda message_id, user_id: _message_row(),
    )
    monkeypatch.setattr(
        auto_response_draft,
        "load_writing_style_card",
        lambda account_email, user_id=None, style_owner_email=None, mail_account_id=None: (
            "Be concise.",
            "/tmp/style.md",
            None,
        ),
    )

    def fake_provider(draft_input):
        assert draft_input["user_guidance"] == "Mention that I will check."
        return {
            "draft_body": "Hi Mongie,\n\nThanks for checking in. I will check and send back an update.",
            "caveats": ["No confirmed status was provided."],
        }

    monkeypatch.setattr(auto_response_draft, "_call_openai_auto_response", fake_provider)

    result = auto_response_draft.generate_auto_response_draft(
        42,
        user_id=1,
        user_email="owner@example.com",
        user_guidance="Mention that I will check.",
    )

    assert result is not None
    assert result["draft_body"].startswith("Hi Mongie")
    assert result["model"] == "gpt-test"
    assert result["draft_only"] is True


def test_generate_auto_response_draft_requires_openai_key(monkeypatch):
    monkeypatch.setattr(auto_response_draft.config, "AI_DIGEST_PROVIDER", "openai")
    monkeypatch.setattr(auto_response_draft.config, "OPENAI_API_KEY", "")

    with pytest.raises(auto_response_draft.AutoResponseDraftNotConfiguredError):
        auto_response_draft.generate_auto_response_draft(
            42,
            user_id=1,
            user_guidance="",
        )
