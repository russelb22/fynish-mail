from __future__ import annotations

import base64

from app.services.gmail_readonly import extract_body_preview, transform_gmail_message


def _encoded(value: str) -> str:
    return base64.urlsafe_b64encode(value.encode("utf-8")).decode("utf-8").rstrip("=")


def test_extract_body_preview_prefers_plain_text_and_flags_attachments():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {
                "mimeType": "multipart/alternative",
                "parts": [
                    {"mimeType": "text/plain", "body": {"data": _encoded("Plain text body")}},
                    {"mimeType": "text/html", "body": {"data": _encoded("<p>HTML body</p>")}},
                ],
            },
            {
                "mimeType": "application/pdf",
                "filename": "statement.pdf",
                "body": {"attachmentId": "att-1"},
            },
        ],
    }

    body_preview, has_attachments = extract_body_preview(payload)

    assert body_preview == "Plain text body"
    assert has_attachments is True


def test_transform_gmail_message_falls_back_to_html_without_downloading_attachments():
    message = {
        "id": "gmail-1",
        "threadId": "thread-1",
        "internalDate": "1770000000000",
        "labelIds": ["INBOX", "UNREAD"],
        "snippet": "Snippet text",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "owner@example.com"},
                {"name": "Subject", "value": "Hello"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {"data": _encoded("<p>Hello <strong>world</strong></p>")},
                }
            ],
        },
    }

    transformed = transform_gmail_message(message)

    assert transformed["gmail_message_id"] == "gmail-1"
    assert transformed["sender"] == "Sender <sender@example.com>"
    assert transformed["subject"] == "Hello"
    assert transformed["body_preview"] == "Hello world"
    assert transformed["has_attachments"] == 0
    assert transformed["gmail_labels"] == ["INBOX", "UNREAD"]


def test_transform_gmail_message_cleans_html_entities_and_tracking_url_lines():
    message = {
        "id": "gmail-1",
        "threadId": "thread-1",
        "internalDate": "1770000000000",
        "labelIds": ["INBOX"],
        "snippet": "Snippet text",
        "payload": {
            "mimeType": "multipart/alternative",
            "headers": [
                {"name": "From", "value": "Sender <sender@example.com>"},
                {"name": "To", "value": "owner@example.com"},
                {"name": "Subject", "value": "Hello"},
            ],
            "parts": [
                {
                    "mimeType": "text/html",
                    "body": {
                        "data": _encoded(
                            "<p>Markiplier&#39;s Iron Lung is available.</p>"
                            "<p>YouTube</p>"
                            "<p>&lt;https://c.gle/tracking-token&gt;</p>"
                            "<p>FIFA World Cup 2026 kicks off on FOX One</p>"
                            "<p>https://example.com/another-tracker</p>"
                        )
                    },
                }
            ],
        },
    }

    transformed = transform_gmail_message(message)

    assert "Markiplier's Iron Lung is available." in transformed["body_preview"]
    assert "FIFA World Cup 2026 kicks off on FOX One" in transformed["body_preview"]
    assert "https://c.gle" not in transformed["body_preview"]
    assert "https://example.com" not in transformed["body_preview"]
