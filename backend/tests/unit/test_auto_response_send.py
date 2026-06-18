from __future__ import annotations

import json
from base64 import urlsafe_b64decode, urlsafe_b64encode
from datetime import datetime, timezone
from email import message_from_bytes, policy

import pytest

from app.core import config
from app.db import database
from app.services import auto_response_send


def _encoded_body(text: str) -> str:
    return urlsafe_b64encode(text.encode("utf-8")).decode("utf-8")


def _gmail_message(
    message_id: str,
    *,
    sender: str,
    body_text: str,
    internal_date: int,
) -> dict:
    return {
        "id": message_id,
        "threadId": "thread-1",
        "internalDate": str(internal_date),
        "labelIds": ["INBOX"],
        "payload": {
            "mimeType": "text/plain",
            "headers": [
                {"name": "From", "value": sender},
                {"name": "Subject", "value": "Can you confirm?"},
                {"name": "Message-ID", "value": f"<{message_id}@example.com>"},
            ],
            "body": {"data": _encoded_body(body_text)},
        },
        "snippet": body_text[:120],
    }


def _insert_owned_gmail_message(scopes: list[str]) -> int:
    now = datetime.now(timezone.utc).isoformat()
    with database.get_connection() as conn:
        user_id = conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (?, 'Owner', 'active', ?, ?)
            """,
            ("owner@example.com", now, now),
        ).lastrowid
        mail_account_id = conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'owner@example.com', 'Owner Gmail', 1, 'active', ?, ?)
            """,
            (user_id, now, now),
        ).lastrowid
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, token_path, scopes_json, metadata_json,
                created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', '/tmp/fake-token.json', ?, '{}', ?, ?)
            """,
            (mail_account_id, json.dumps(scopes), now, now),
        )
        message_id = conn.execute(
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain, reply_to,
                recipient_to, recipient_cc, subject, received_at, snippet, body_preview,
                gmail_labels_json, provider_labels_json, headers_json, has_attachments,
                current_category, confidence, protected, reviewed, created_at, updated_at
            ) VALUES (
                'gmail-1', 'thread-1', 'owner@example.com', ?,
                'gmail-1', 'thread-1', 'Sender Name <sender@example.com>', 'example.com', '',
                'owner@example.com', '', 'Can you confirm?', ?, 'Snippet', 'Original line one.\nOriginal line two.',
                '["INBOX"]', '["INBOX"]', ?, 0,
                'needs_review', 0.5, 0, 0, ?, ?
            )
            """,
            (
                mail_account_id,
                now,
                json.dumps({"Message-ID": "<original@example.com>"}),
                now,
                now,
            ),
        ).lastrowid
    return int(message_id)


def test_auto_response_send_allowed_for_email_uses_feature_gate(monkeypatch):
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_ENABLED", False)
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS", [])

    assert auto_response_send.auto_response_send_allowed_for_email("owner@example.com") is False

    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_ENABLED", True)
    assert auto_response_send.auto_response_send_allowed_for_email("owner@example.com") is True

    monkeypatch.setattr(
        auto_response_send.config,
        "AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS",
        ["owner@example.com"],
    )
    assert auto_response_send.auto_response_send_allowed_for_email("OWNER@example.com") is True
    assert auto_response_send.auto_response_send_allowed_for_email("friend@example.com") is False


def test_send_auto_response_sends_threaded_gmail_reply(monkeypatch, isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_MODIFY_SCOPE])
    captured: dict = {}

    class _FakeSendRequest:
        def execute(self):
            return {"id": "sent-1", "threadId": "thread-1"}

    class _FakeMessages:
        def send(self, *, userId, body):
            captured["userId"] = userId
            captured["body"] = body
            return _FakeSendRequest()

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(
        auto_response_send,
        "build_service_from_token_reference",
        lambda token_reference, scopes=None: _FakeService(),
    )
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS", 80)

    result = auto_response_send.send_auto_response(
        message_id,
        user_id=1,
        idempotency_key="send-key-1",
        draft_body="Thanks, I can confirm.",
        confirmed=True,
    )

    assert result is not None
    assert result.status == "sent"
    assert result.gmail_sent_message_id == "sent-1"
    assert captured["userId"] == "me"
    assert captured["body"]["threadId"] == "thread-1"

    parsed = message_from_bytes(
        urlsafe_b64decode(captured["body"]["raw"].encode("utf-8")),
        policy=policy.default,
    )
    assert parsed["To"] == "sender@example.com"
    assert parsed["From"] == "owner@example.com"
    assert parsed["Subject"] == "Re: Can you confirm?"
    assert parsed["In-Reply-To"] == "<original@example.com>"
    content = parsed.get_content().strip()
    assert content.startswith("Thanks, I can confirm.")
    assert "Sender Name <sender@example.com> wrote:" in content
    assert "> Original line one." in content
    assert "> Original line two." in content


def test_send_auto_response_quotes_bounded_gmail_thread_history(monkeypatch, isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_MODIFY_SCOPE])
    captured: dict = {}

    class _FakeExecute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _FakeThreads:
        def get(self, *, userId, id, format):
            assert userId == "me"
            assert id == "thread-1"
            assert format == "full"
            return _FakeExecute(
                {
                    "messages": [
                        _gmail_message(
                            "gmail-0",
                            sender="Prior Sender <prior@example.com>",
                            body_text="Earlier context from the same thread.",
                            internal_date=1,
                        ),
                        _gmail_message(
                            "gmail-1",
                            sender="Sender Name <sender@example.com>",
                            body_text="Current source message from Gmail thread.",
                            internal_date=2,
                        ),
                        _gmail_message(
                            "gmail-2",
                            sender="Later Sender <later@example.com>",
                            body_text="This later message should not be quoted.",
                            internal_date=3,
                        ),
                    ]
                }
            )

    class _FakeMessages:
        def send(self, *, userId, body):
            captured["body"] = body
            return _FakeExecute({"id": "sent-thread", "threadId": "thread-1"})

    class _FakeUsers:
        def threads(self):
            return _FakeThreads()

        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(
        auto_response_send,
        "build_service_from_token_reference",
        lambda token_reference, scopes=None: _FakeService(),
    )
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES", 2)
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS", 500)

    result = auto_response_send.send_auto_response(
        message_id,
        user_id=1,
        idempotency_key="send-key-thread",
        draft_body="Thanks, here is the answer.",
        confirmed=True,
    )

    assert result is not None
    parsed = message_from_bytes(
        urlsafe_b64decode(captured["body"]["raw"].encode("utf-8")),
        policy=policy.default,
    )
    content = parsed.get_content()
    assert "Recent Gmail thread context:" in content
    assert "Earlier context from the same thread." in content
    assert "Current source message from Gmail thread." in content
    assert "This later message should not be quoted." not in content
    assert "Original line one" not in content


def test_preview_auto_response_send_returns_final_body_with_context(monkeypatch, isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_MODIFY_SCOPE])

    class _FakeExecute:
        def __init__(self, payload):
            self.payload = payload

        def execute(self):
            return self.payload

    class _FakeThreads:
        def get(self, *, userId, id, format):
            return _FakeExecute(
                {
                    "messages": [
                        _gmail_message(
                            "gmail-1",
                            sender="Sender Name <sender@example.com>",
                            body_text="Current source message from Gmail thread.",
                            internal_date=2,
                        )
                    ]
                }
            )

    class _FakeUsers:
        def threads(self):
            return _FakeThreads()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(
        auto_response_send,
        "build_service_from_token_reference",
        lambda token_reference, scopes=None: _FakeService(),
    )

    result = auto_response_send.preview_auto_response_send(
        message_id,
        user_id=1,
        draft_body="Preview draft.",
    )

    assert result is not None
    assert result.body_text.startswith("Preview draft.")
    assert "Recent Gmail thread context:" in result.body_text
    assert "Current source message from Gmail thread." in result.body_text
    assert result.context_source == "gmail_thread_history"


def test_send_auto_response_can_send_exact_preview_body_without_adding_context(monkeypatch, isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_SEND_SCOPE])
    captured: dict = {}

    class _FakeSendRequest:
        def execute(self):
            return {"id": "sent-exact", "threadId": "thread-1"}

    class _FakeMessages:
        def send(self, *, userId, body):
            captured["body"] = body
            return _FakeSendRequest()

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(
        auto_response_send,
        "build_service_from_token_reference",
        lambda token_reference, scopes=None: _FakeService(),
    )

    exact_body = "Reply body.\n\nAlready quoted context."
    result = auto_response_send.send_auto_response(
        message_id,
        user_id=1,
        idempotency_key="send-key-exact",
        draft_body=exact_body,
        confirmed=True,
        include_context=False,
    )

    assert result is not None
    parsed = message_from_bytes(
        urlsafe_b64decode(captured["body"]["raw"].encode("utf-8")),
        policy=policy.default,
    )
    assert parsed.get_content().strip() == exact_body
    assert "Original line one" not in parsed.get_content()


def test_send_auto_response_blocks_missing_send_scope(isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_READONLY_SCOPE])

    with pytest.raises(auto_response_send.AutoResponseSendNotConfiguredError):
        auto_response_send.send_auto_response(
            message_id,
            user_id=1,
            idempotency_key="send-key-2",
            draft_body="Thanks.",
            confirmed=True,
        )


def test_send_auto_response_replays_idempotent_result(monkeypatch, isolated_db):
    message_id = _insert_owned_gmail_message([config.GMAIL_SEND_SCOPE])
    send_count = 0

    class _FakeSendRequest:
        def execute(self):
            nonlocal send_count
            send_count += 1
            return {"id": "sent-2", "threadId": "thread-1"}

    class _FakeMessages:
        def send(self, *, userId, body):
            return _FakeSendRequest()

    class _FakeUsers:
        def messages(self):
            return _FakeMessages()

    class _FakeService:
        def users(self):
            return _FakeUsers()

    monkeypatch.setattr(
        auto_response_send,
        "build_service_from_token_reference",
        lambda token_reference, scopes=None: _FakeService(),
    )

    first = auto_response_send.send_auto_response(
        message_id,
        user_id=1,
        idempotency_key="send-key-3",
        draft_body="First body.",
        confirmed=True,
    )
    second = auto_response_send.send_auto_response(
        message_id,
        user_id=1,
        idempotency_key="send-key-3",
        draft_body="First body.",
        confirmed=True,
    )

    assert first is not None
    assert second is not None
    assert first.gmail_sent_message_id == second.gmail_sent_message_id == "sent-2"
    assert send_count == 1


def test_build_outbound_body_limits_quoted_original(monkeypatch):
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS", 12)
    message_row = {
        "sender": "Sender <sender@example.com>",
        "received_at": "2026-06-11T12:00:00+00:00",
        "body_preview": "abcdefghijklmnopqrstuvwxyz",
        "snippet": "",
    }

    result = auto_response_send._build_outbound_body("Reply body.", message_row)

    assert result.startswith("Reply body.")
    assert "> abcdefghijk…" in result
    assert "mnopqrstuvwxyz" not in result


def test_build_thread_history_quote_limits_total_chars(monkeypatch):
    monkeypatch.setattr(auto_response_send.config, "AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS", 10)
    result = auto_response_send._build_thread_history_quote(
        [
            auto_response_send.ThreadHistoryMessage(
                gmail_message_id="gmail-1",
                sender="Sender <sender@example.com>",
                received_at="2026-06-11T12:00:00+00:00",
                body_text="abcdefghijklmnopqrstuvwxyz",
            )
        ]
    )

    assert "Recent Gmail thread context:" in result
    assert "> abcdefghi…" in result
    assert "klmnopqrstuvwxyz" not in result
