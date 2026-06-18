from __future__ import annotations

import pytest

from app.db.runtime import fetch_one, get_connection
from app.services.ai_digest_attention_notes import (
    AIDigestAttentionNoteValidationError,
    create_ai_digest_attention_note,
    delete_ai_digest_attention_note,
    get_enabled_ai_digest_attention_notes,
    list_ai_digest_attention_notes,
    normalize_domain,
    update_ai_digest_attention_note,
)


def test_normalize_domain_accepts_bare_domains():
    assert normalize_domain(" Example.NET ") == "example.net"
    assert normalize_domain("@TrueCoach.co") == "truecoach.co"


@pytest.mark.parametrize("domain", ["", "https://example.net", "not-a-domain", "example.net/path"])
def test_normalize_domain_rejects_invalid_domains(domain):
    with pytest.raises(AIDigestAttentionNoteValidationError):
        normalize_domain(domain)


def test_list_seeds_default_notes_for_user(empty_db):
    notes = list_ai_digest_attention_notes(user_id=1)

    assert [note["domain"] for note in notes] == ["example.net", "truecoach.co"]
    assert all(note["enabled"] for note in notes)


def test_create_update_disable_and_delete_note(empty_db):
    created = create_ai_digest_attention_note(
        {
            "domain": "Example.COM",
            "label": "Example",
            "note": "Treat these as routine unless the preview shows a direct reply.",
        },
        user_id=1,
    )

    assert created["domain"] == "example.com"
    assert created["enabled"] is True

    updated = update_ai_digest_attention_note(
        created["id"],
        {"enabled": False, "label": "Example Alerts"},
        user_id=1,
    )

    assert updated is not None
    assert updated["enabled"] is False
    assert updated["label"] == "Example Alerts"
    assert created["domain"] not in [
        note["domain"] for note in get_enabled_ai_digest_attention_notes(user_id=1)
    ]

    assert delete_ai_digest_attention_note(created["id"], user_id=1) is True
    assert delete_ai_digest_attention_note(created["id"], user_id=1) is False


def test_create_rejects_duplicate_domain_for_same_user(empty_db):
    create_ai_digest_attention_note(
        {"domain": "example.com", "note": "First note."},
        user_id=1,
    )

    with pytest.raises(AIDigestAttentionNoteValidationError):
        create_ai_digest_attention_note(
            {"domain": "EXAMPLE.com", "note": "Second note."},
            user_id=1,
        )


def test_get_enabled_uses_defaults_when_no_persisted_notes(empty_db):
    notes = get_enabled_ai_digest_attention_notes(user_id=1)

    assert [note["domain"] for note in notes] == ["example.net", "truecoach.co"]
    with get_connection() as conn:
        row = fetch_one(
            conn,
            "SELECT id FROM ai_digest_domain_attention_notes WHERE user_id = 1 LIMIT 1",
        )
    assert row is None
