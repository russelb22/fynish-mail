from __future__ import annotations

import pytest

from app.db.runtime import execute_sql, get_connection
from app.services.writing_style_cards import (
    WritingStyleCardValidationError,
    approve_writing_style_card,
    create_starter_writing_style_card,
    disable_writing_style_card,
    get_approved_writing_style_card,
    list_writing_style_cards,
    sample_sent_mail_writing_style_card,
    update_writing_style_card,
    writing_style_cards_allowed_for_email,
)


def _seed_user_and_account(
    *,
    user_id: int = 1,
    account_id: int = 10,
    user_email: str | None = None,
    account_email: str | None = None,
):
    user_email = user_email or f"owner{user_id}@example.com"
    account_email = account_email or user_email
    with get_connection() as conn:
        execute_sql(
            conn,
            """
            INSERT INTO users (id, email, display_name, status, created_at, updated_at)
            VALUES (:id, :email, :name, 'active', '2026-06-08T00:00:00+00:00', '2026-06-08T00:00:00+00:00')
            """,
            {"id": user_id, "email": user_email, "name": "Owner"},
        )
        execute_sql(
            conn,
            """
            INSERT INTO mail_accounts (
                id, user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (
                :id, :user_id, 'gmail', :email, :email,
                1, 'active', '2026-06-08T00:00:00+00:00', '2026-06-08T00:00:00+00:00'
            )
            """,
            {"id": account_id, "user_id": user_id, "email": account_email},
        )


def _seed_provider_connection(*, account_id: int = 10):
    with get_connection() as conn:
        execute_sql(
            conn,
            """
            INSERT INTO provider_connections (
                id, mail_account_id, provider, connection_type, token_path,
                scopes_json, metadata_json, created_at, updated_at
            ) VALUES (
                100, :account_id, 'gmail', 'oauth', '/tmp/fake-token.json',
                '[]', '{}', '2026-06-08T00:00:00+00:00', '2026-06-08T00:00:00+00:00'
            )
            """,
            {"account_id": account_id},
        )


def test_writing_style_cards_allowed_for_email_uses_feature_gate(monkeypatch):
    monkeypatch.setattr("app.services.writing_style_cards.config.WRITING_STYLE_CARDS_ENABLED", False)
    monkeypatch.setattr("app.services.writing_style_cards.config.WRITING_STYLE_ALLOWED_USER_EMAILS", [])

    assert writing_style_cards_allowed_for_email("owner@example.com") is False

    monkeypatch.setattr("app.services.writing_style_cards.config.WRITING_STYLE_CARDS_ENABLED", True)
    assert writing_style_cards_allowed_for_email("owner@example.com") is True

    monkeypatch.setattr(
        "app.services.writing_style_cards.config.WRITING_STYLE_ALLOWED_USER_EMAILS",
        ["owner@example.com"],
    )
    assert writing_style_cards_allowed_for_email("OWNER@example.com") is True
    assert writing_style_cards_allowed_for_email("friend@example.com") is False


def test_create_update_approve_and_disable_style_card(empty_db):
    _seed_user_and_account()

    created = create_starter_writing_style_card(user_id=1, mail_account_id=10)
    assert created["status"] == "draft"
    assert created["account_email"] == "owner1@example.com"
    assert created["user_edited"] is False

    updated = update_writing_style_card(
        created["id"],
        {
            "style_card_markdown": (
                "# Writing Style Card\n\n"
                "Use a practical, warm, direct style. Keep paragraphs short, "
                "avoid over-explaining, and mention uncertainty clearly when facts are missing."
            )
        },
        user_id=1,
    )
    assert updated is not None
    assert updated["user_edited"] is True
    assert updated["status"] == "draft"

    approved = approve_writing_style_card(created["id"], user_id=1)
    assert approved is not None
    assert approved["status"] == "approved"

    active = get_approved_writing_style_card(
        user_id=1,
        account_email="owner1@example.com",
        mail_account_id=10,
    )
    assert active is not None
    assert active["id"] == created["id"]

    disabled = disable_writing_style_card(created["id"], user_id=1)
    assert disabled is not None
    assert disabled["status"] == "disabled"
    assert get_approved_writing_style_card(
        user_id=1,
        account_email="owner1@example.com",
        mail_account_id=10,
    ) is None


def test_create_user_owned_style_card_without_mail_account(empty_db):
    _seed_user_and_account()

    created = create_starter_writing_style_card(
        user_id=1,
        account_email="owner1@example.com",
    )

    assert created["status"] == "draft"
    assert created["mail_account_id"] is None
    assert created["account_email"] == "owner1@example.com"


def test_sample_sent_mail_style_card_saves_derived_profile(monkeypatch, empty_db):
    _seed_user_and_account()
    _seed_provider_connection()

    sample_records = [
        {
            "account_email": "owner1@example.com",
            "bucket": "2025",
            "gmail_message_id": "m1",
            "gmail_thread_id": "t1",
            "sent_at": "2025-01-01T00:00:00+00:00",
            "subject": "Checking in",
            "to": "friend@example.com",
            "cc": "",
            "word_count": 44,
            "char_count": 240,
            "text": "Hi there,\n\nThanks for checking in. I think this sounds good, and I can take a closer look tomorrow. Let me know if that works for you.",
        },
        {
            "account_email": "owner1@example.com",
            "bucket": "2026",
            "gmail_message_id": "m2",
            "gmail_thread_id": "t2",
            "sent_at": "2026-01-01T00:00:00+00:00",
            "subject": "Next step",
            "to": "colleague@example.com",
            "cc": "",
            "word_count": 42,
            "char_count": 230,
            "text": "Hi,\n\nGreat, thank you. The next step is probably to confirm the address source and then update the directory field. I would be happy to help.",
        },
    ]
    monkeypatch.setattr(
        "app.services.writing_style_cards.build_service_from_token_reference",
        lambda reference: object(),
    )
    monkeypatch.setattr(
        "app.services.writing_style_cards._sample_sent_mail_records",
        lambda service, account_email: (sample_records, [{"bucket": "2025"}, {"bucket": "2026"}], "2016-06-08", "2026-06-09"),
    )

    card = sample_sent_mail_writing_style_card(
        user_id=1,
        account_email="owner1@example.com",
    )

    assert card["status"] == "draft"
    assert card["source_provider"] == "gmail_sent_sampler"
    assert card["sampled_message_count"] == 2
    assert card["sample_bucket_count"] == 2
    assert card["sampled_word_count"] == 86
    assert "Writing Style Profile: owner1@example.com" in card["style_card_markdown"]


def test_sample_sent_mail_style_card_uses_single_connected_gmail_for_nonmatching_login(monkeypatch, empty_db):
    _seed_user_and_account(
        user_email="kim@example.test",
        account_email="kim.gmail@example.com",
    )
    _seed_provider_connection()

    sample_records = [
        {
            "account_email": "kim.gmail@example.com",
            "bucket": "2026",
            "gmail_message_id": "m1",
            "gmail_thread_id": "t1",
            "sent_at": "2026-01-01T00:00:00+00:00",
            "subject": "Thanks",
            "to": "friend@example.com",
            "cc": "",
            "word_count": 44,
            "char_count": 240,
            "text": "Hi there,\n\nThanks for checking in. I think this sounds good, and I can take a closer look tomorrow. Let me know if that works for you.",
        },
        {
            "account_email": "kim.gmail@example.com",
            "bucket": "2026",
            "gmail_message_id": "m2",
            "gmail_thread_id": "t2",
            "sent_at": "2026-02-01T00:00:00+00:00",
            "subject": "Next step",
            "to": "colleague@example.com",
            "cc": "",
            "word_count": 42,
            "char_count": 230,
            "text": "Hi,\n\nGreat, thank you. The next step is probably to confirm the address source and then update the directory field. I would be happy to help.",
        },
    ]
    monkeypatch.setattr(
        "app.services.writing_style_cards.build_service_from_token_reference",
        lambda reference: object(),
    )
    monkeypatch.setattr(
        "app.services.writing_style_cards._sample_sent_mail_records",
        lambda service, account_email: (sample_records, [{"bucket": "2026"}], "2016-06-08", "2026-06-09"),
    )

    card = sample_sent_mail_writing_style_card(
        user_id=1,
        account_email="kim@example.test",
    )

    assert card["account_email"] == "kim@example.test"
    assert card["mail_account_id"] == 10
    assert card["source_provider"] == "gmail_sent_sampler"
    assert "Writing Style Profile: kim@example.test" in card["style_card_markdown"]


def test_approving_new_card_supersedes_old_approved_card(empty_db):
    _seed_user_and_account()

    first = create_starter_writing_style_card(user_id=1, mail_account_id=10)
    approve_writing_style_card(first["id"], user_id=1)
    second = create_starter_writing_style_card(user_id=1, mail_account_id=10)
    approved = approve_writing_style_card(second["id"], user_id=1)

    assert approved is not None
    cards = list_writing_style_cards(user_id=1)
    statuses = {card["id"]: card["status"] for card in cards}
    assert statuses[first["id"]] == "superseded"
    assert statuses[second["id"]] == "approved"


def test_style_card_rejects_other_users_and_short_edits(empty_db):
    _seed_user_and_account(user_id=1, account_id=10)
    _seed_user_and_account(user_id=2, account_id=20)
    created = create_starter_writing_style_card(user_id=1, mail_account_id=10)

    assert update_writing_style_card(
        created["id"],
        {"style_card_markdown": "This is long enough to pass maybe but belongs elsewhere." * 2},
        user_id=2,
    ) is None

    with pytest.raises(WritingStyleCardValidationError):
        update_writing_style_card(
            created["id"],
            {"style_card_markdown": "Too short."},
            user_id=1,
        )
