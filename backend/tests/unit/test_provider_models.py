from __future__ import annotations

import json

from app.services.provider_models import (
    MailAccountRecord,
    ProviderMessageRecord,
    account_email_from_row,
    provider_labels_from_row,
    provider_message_id_from_row,
)


def test_provider_message_helpers_prefer_provider_neutral_columns():
    row = {
        "id": 7,
        "account_email": "legacy@gmail.com",
        "provider": "gmail_readonly",
        "mail_account_id": 12,
        "provider_message_id": "provider-123",
        "gmail_message_id": "gmail-legacy-123",
        "provider_thread_id": "provider-thread-1",
        "gmail_thread_id": "gmail-thread-1",
        "provider_labels_json": json.dumps(["INBOX", "UNREAD"]),
        "gmail_labels_json": json.dumps(["OLD"]),
        "sender": "Sender <sender@example.com>",
        "subject": "Subject",
        "has_attachments": 1,
        "current_category": "keep",
        "confidence": 0.91,
        "protected": 1,
    }

    message = ProviderMessageRecord.from_row(row)

    assert provider_message_id_from_row(row) == "provider-123"
    assert provider_labels_from_row(row) == ["INBOX", "UNREAD"]
    assert message.provider_message_id == "provider-123"
    assert message.provider_thread_id == "provider-thread-1"
    assert message.account_email == "legacy@gmail.com"
    assert message.mail_account_id == 12
    assert message.has_attachments is True
    assert message.protected is True


def test_provider_message_helpers_fall_back_to_legacy_gmail_columns():
    row = {
        "id": 9,
        "email_address": "legacy@gmail.com",
        "provider": "gmail_readonly",
        "gmail_message_id": "gmail-legacy-456",
        "gmail_thread_id": "gmail-thread-2",
        "gmail_labels_json": json.dumps(["CATEGORY_UPDATES"]),
    }

    message = ProviderMessageRecord.from_row(row)

    assert account_email_from_row(row) == "legacy@gmail.com"
    assert message.provider_message_id == "gmail-legacy-456"
    assert message.provider_thread_id == "gmail-thread-2"
    assert message.provider_labels == ["CATEGORY_UPDATES"]


def test_mail_account_record_preserves_legacy_payload_shape():
    row = {
        "id": 4,
        "email_address": "person@example.com",
        "provider": "gmail_readonly",
        "enabled": 1,
        "last_sync_at": "2026-05-09T10:00:00+00:00",
        "mail_account_id": 14,
        "user_id": 1,
        "external_account_email": "person@example.com",
        "mail_account_display_name": "Person",
        "mail_account_status": "active",
        "scopes_json": json.dumps(["https://www.googleapis.com/auth/gmail.modify"]),
        "metadata_json": json.dumps(
            {
                "reconnect_required": 1,
                "last_sync_error": "Stored Gmail credentials were expired or revoked. Reconnect the account.",
            }
        ),
    }

    account = MailAccountRecord.from_row(row)
    payload = account.to_legacy_payload(legacy_id=row["id"])

    assert account.account_email == "person@example.com"
    assert account.mail_account_id == 14
    assert account.oauth_scopes == ["https://www.googleapis.com/auth/gmail.modify"]
    assert payload["id"] == 4
    assert payload["email_address"] == "person@example.com"
    assert payload["enabled"] is True
    assert payload["provider"] == "gmail_readonly"
    assert payload["oauth_scopes"] == ["https://www.googleapis.com/auth/gmail.modify"]
    assert payload["auth_status"] == "reconnect_required"
    assert payload["auth_status_label"] == "Reconnect required"
    assert payload["auth_status_reason"] == (
        "Stored Gmail credentials were expired or revoked. Reconnect the account."
    )
