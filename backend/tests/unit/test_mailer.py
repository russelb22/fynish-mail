from __future__ import annotations

import json
from base64 import urlsafe_b64decode
from email import message_from_bytes
from email import policy

import pytest

from app.services import mailer


class _FakeResponse:
    def __init__(self, body: dict, headers: dict[str, str] | None = None):
        self._body = json.dumps(body).encode("utf-8")
        self.headers = headers or {}

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return None


def test_send_plain_text_email_raises_when_disabled(monkeypatch):
    monkeypatch.setattr(mailer, "MAIL_PROVIDER", "disabled")
    monkeypatch.setattr(mailer, "MAIL_FROM_EMAIL", "")
    monkeypatch.setattr(mailer, "MAIL_API_KEY", "")

    with pytest.raises(mailer.MailerNotConfiguredError):
        mailer.send_plain_text_email(
            to_email="kim@example.com",
            subject="Digest",
            body="Hello",
        )


def test_send_plain_text_email_uses_postmark(monkeypatch):
    monkeypatch.setattr(mailer, "MAIL_PROVIDER", "postmark")
    monkeypatch.setattr(mailer, "MAIL_FROM_EMAIL", "fynish@example.com")
    monkeypatch.setattr(mailer, "MAIL_API_KEY", "postmark-key")

    def fake_urlopen(req, timeout=0):
        assert req.full_url == "https://api.postmarkapp.com/email"
        assert req.headers["X-postmark-server-token"] == "postmark-key"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["To"] == "kim@example.com"
        return _FakeResponse({"MessageID": "pm-123"})

    monkeypatch.setattr(mailer.request, "urlopen", fake_urlopen)

    result = mailer.send_plain_text_email(
        to_email="kim@example.com",
        subject="Digest",
        body="Hello",
    )

    assert result.provider == "postmark"
    assert result.message_id == "pm-123"


def test_send_email_uses_postmark_html_body(monkeypatch):
    monkeypatch.setattr(mailer, "MAIL_PROVIDER", "postmark")
    monkeypatch.setattr(mailer, "MAIL_FROM_EMAIL", "fynish@example.com")
    monkeypatch.setattr(mailer, "MAIL_API_KEY", "postmark-key")

    def fake_urlopen(req, timeout=0):
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["TextBody"] == "Plain fallback"
        assert payload["HtmlBody"] == "<p>HTML</p>"
        return _FakeResponse({"MessageID": "pm-html"})

    monkeypatch.setattr(mailer.request, "urlopen", fake_urlopen)

    result = mailer.send_email(
        to_email="kim@example.com",
        subject="Digest",
        text_body="Plain fallback",
        html_body="<p>HTML</p>",
    )

    assert result.provider == "postmark"
    assert result.message_id == "pm-html"


def test_send_plain_text_email_uses_sendgrid(monkeypatch):
    monkeypatch.setattr(mailer, "MAIL_PROVIDER", "sendgrid")
    monkeypatch.setattr(mailer, "MAIL_FROM_EMAIL", "fynish@example.com")
    monkeypatch.setattr(mailer, "MAIL_API_KEY", "sendgrid-key")

    def fake_urlopen(req, timeout=0):
        assert req.full_url == "https://api.sendgrid.com/v3/mail/send"
        assert req.headers["Authorization"] == "Bearer sendgrid-key"
        payload = json.loads(req.data.decode("utf-8"))
        assert payload["personalizations"][0]["to"][0]["email"] == "kim@example.com"
        assert payload["content"] == [{"type": "text/plain", "value": "Hello"}]
        return _FakeResponse({}, headers={"X-Message-Id": "sg-789"})

    monkeypatch.setattr(mailer.request, "urlopen", fake_urlopen)

    result = mailer.send_plain_text_email(
        to_email="kim@example.com",
        subject="Digest",
        body="Hello",
    )

    assert result.provider == "sendgrid"
    assert result.message_id == "sg-789"


def test_send_email_uses_gmail_digest_sender_with_html_alternative(monkeypatch):
    monkeypatch.setattr(mailer, "MAIL_PROVIDER", "gmail")
    monkeypatch.setattr(mailer, "MAIL_FROM_EMAIL", "")
    monkeypatch.setattr(mailer, "MAIL_API_KEY", "")
    monkeypatch.setattr(mailer, "GMAIL_SENDER_EMAIL", "digest.sender@example.com")

    captured: dict = {}

    class _FakeSendRequest:
        def execute(self):
            return {"id": "gmail-123"}

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
        mailer,
        "build_gmail_digest_sender_service",
        lambda email: _FakeService(),
    )

    result = mailer.send_email(
        to_email="kim@example.com",
        subject="Digest",
        text_body="Hello from Fynish",
        html_body="<h1>Hello from Fynish</h1>",
    )

    assert result.provider == "gmail"
    assert result.message_id == "gmail-123"
    assert captured["userId"] == "me"
    raw = captured["body"]["raw"]
    parsed = message_from_bytes(urlsafe_b64decode(raw.encode("utf-8")), policy=policy.default)
    assert parsed["To"] == "kim@example.com"
    assert parsed["From"] == "digest.sender@example.com"
    assert parsed["Subject"] == "Digest"
    assert parsed.is_multipart()
    assert parsed.get_body(("plain",)).get_content().strip() == "Hello from Fynish"
    assert "<h1>Hello from Fynish</h1>" in parsed.get_body(("html",)).get_content()
