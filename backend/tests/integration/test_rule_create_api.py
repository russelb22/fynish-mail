from __future__ import annotations

from app.db.runtime import fetch_one, get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.review_queue import sync_unread_messages


def _source_message_id() -> int:
    with get_connection() as conn:
        row = fetch_one(
            conn,
            """
            SELECT id
            FROM messages
            WHERE sender_domain = 'fixer-mailer.com'
            ORDER BY id
            LIMIT 1
            """,
        )
    assert row is not None
    return int(row["id"])


def test_create_rule_reports_partial_success_when_source_message_disappears(
    api_client,
    monkeypatch,
):
    sync_unread_messages()
    source_message_id = _source_message_id()
    monkeypatch.setattr("app.api.routes.apply_message_action", lambda *args, **kwargs: None)

    response = api_client.post(
        "/api/rules",
        json={
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "source_message_id": source_message_id,
            "apply_to_source": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rule"]["pattern"] == "fixer-mailer.com"
    assert payload["applied"] is None
    assert payload["apply_error"] == "Source message is no longer available."
    assert payload["reclassified_messages"] >= 0


def test_create_rule_reports_partial_success_when_source_apply_fails(
    api_client,
    monkeypatch,
):
    sync_unread_messages()
    source_message_id = _source_message_id()

    def fail_source_apply(*args, **kwargs):
        raise GmailReadonlySyncError("Stored Gmail credentials were expired or revoked.")

    monkeypatch.setattr("app.api.routes.apply_message_action", fail_source_apply)

    response = api_client.post(
        "/api/rules",
        json={
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "source_message_id": source_message_id,
            "apply_to_source": True,
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["rule"]["pattern"] == "fixer-mailer.com"
    assert payload["applied"] is None
    assert payload["apply_error"] == "Stored Gmail credentials were expired or revoked."
    assert payload["reclassified_messages"] >= 0


def test_create_rule_reports_source_message_unavailable_code(api_client):
    response = api_client.post(
        "/api/rules",
        json={
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "source_message_id": 999999,
            "apply_to_source": True,
        },
    )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Source message is not available to the current user.",
        "code": "rule_source_message_unavailable",
    }
