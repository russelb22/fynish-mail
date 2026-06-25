from __future__ import annotations

import json
from datetime import datetime, timezone

from app.db.database import get_connection
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL


def _candidate_by_gmail_id(payload: dict, gmail_message_id: str) -> dict:
    return next(
        message
        for account in payload["accounts"]
        for message in account["messages"]
        if message["gmail_message_id"] == gmail_message_id
    )


def _seed_gmail_account_for_local_owner(email: str = "owner@example.com") -> None:
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        user = conn.execute(
            """
            SELECT id
            FROM users
            WHERE email = ?
            """,
            (DEFAULT_LOCAL_OWNER_EMAIL,),
        ).fetchone()
        assert user is not None
        cursor = conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', ?, ?)
            """,
            (user["id"], email, email, now, now),
        )
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, token_path,
                scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', ?, ?, '{}', ?, ?)
            """,
            (
                cursor.lastrowid,
                "/tmp/fake-token.json",
                json.dumps(["gmail.readonly"]),
                now,
                now,
            ),
        )


def _gmail_spam_message(**overrides) -> dict:
    message = {
        "gmail_message_id": "real-spam-1001",
        "gmail_thread_id": "real-spam-thread-1001",
        "sender": "Clinic Billing <billing@clinic.example>",
        "reply_to": "billing@clinic.example",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "Invoice for your recent appointment",
        "received_at": "2026-06-20T15:30:00+00:00",
        "snippet": "Your invoice is ready for review.",
        "body_preview": "Attached is the invoice for your recent appointment.",
        "gmail_labels": ["SPAM", "UNREAD"],
        "headers": {},
        "has_attachments": 1,
    }
    message.update(overrides)
    return message


class _FakeSpamAdapter:
    provider_name = "gmail_readonly"

    def __init__(self, messages):
        self.messages = messages
        self.calls = []

    def list_unread_inbox_messages(self, token_reference, max_results):
        return []

    def list_unread_spam_messages(self, token_reference, max_results, *, newer_than_days=None):
        self.calls.append(
            {
                "max_results": max_results,
                "newer_than_days": newer_than_days,
            }
        )
        return self.messages

    def modify_message_labels(self, **_):
        return []

    def requires_modify_scope(self):
        return None


def test_spam_rescue_api_returns_mock_candidates(api_client, seeded_db):
    response = api_client.get("/api/spam-rescue")

    assert response.status_code == 200
    payload = response.json()
    candidates = [
        message
        for account in payload["accounts"]
        for message in account["messages"]
    ]
    candidate_ids = {message["gmail_message_id"] for message in candidates}

    assert payload["count"] == len(candidates)
    assert "ps-9001" in candidate_ids
    assert "ps-9002" not in candidate_ids
    assert all(message["source_label"] == "spam" for message in candidates)
    assert all(message["review_surface"] == "spam_rescue" for message in candidates)


def test_spam_rescue_sync_imports_gmail_spam_candidates(api_client, isolated_db, monkeypatch):
    api_client.get("/api/features")
    _seed_gmail_account_for_local_owner()
    adapter = _FakeSpamAdapter([_gmail_spam_message()])
    monkeypatch.setattr("app.services.spam_rescue.get_mail_provider_adapter", lambda _: adapter)
    monkeypatch.setattr(
        "app.services.mail_provider_adapter.fetch_unread_inbox_messages",
        lambda token_reference, max_results: [],
    )

    response = api_client.post("/api/spam-rescue/sync")

    assert response.status_code == 200
    assert response.json()["synced_messages"] == 1
    assert response.json()["surfaced_candidates"] == 1
    assert adapter.calls == [{"max_results": 50, "newer_than_days": 30}]

    spam_queue = api_client.get("/api/spam-rescue").json()
    candidate = _candidate_by_gmail_id(spam_queue, "real-spam-1001")
    assert candidate["account_email"] == "owner@example.com"
    assert candidate["source_label"] == "spam"
    assert candidate["state_version"]

    review_queue = api_client.get("/api/review-queue").json()
    review_ids = {
        message["gmail_message_id"]
        for account in review_queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    assert "real-spam-1001" not in review_ids

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed, current_category, queue_source, provider_labels_json
            FROM messages
            WHERE provider_message_id = 'real-spam-1001'
            """
        ).fetchone()
    assert row["reviewed"] == 0
    assert row["current_category"] == "spam_rescue"
    assert row["queue_source"] == "spam_rescue"
    assert json.loads(row["provider_labels_json"]) == ["SPAM", "UNREAD"]

    inbox_sync = api_client.post("/api/sync/unread")
    assert inbox_sync.status_code == 200
    assert _candidate_by_gmail_id(api_client.get("/api/spam-rescue").json(), "real-spam-1001")

    adapter.messages = []
    second_response = api_client.post("/api/spam-rescue/sync")
    assert second_response.status_code == 200
    assert second_response.json()["reconciled_candidates"] == 1
    refreshed_ids = {
        message["gmail_message_id"]
        for account in api_client.get("/api/spam-rescue").json()["accounts"]
        for message in account["messages"]
    }
    assert "real-spam-1001" not in refreshed_ids


def test_spam_rescue_sync_suppresses_obvious_gmail_spam(api_client, isolated_db, monkeypatch):
    api_client.get("/api/features")
    _seed_gmail_account_for_local_owner()
    adapter = _FakeSpamAdapter(
        [
            _gmail_spam_message(
                gmail_message_id="obvious-spam-1001",
                subject="YOU WON A PRIZE",
                sender="Prize Team <winner@prizes.example>",
                body_preview="Click now to claim your free prize and exclusive deal.",
                snippet="Click now to claim your prize.",
                has_attachments=0,
            )
        ]
    )
    monkeypatch.setattr("app.services.spam_rescue.get_mail_provider_adapter", lambda _: adapter)

    response = api_client.post("/api/spam-rescue/sync")

    assert response.status_code == 200
    assert response.json()["synced_messages"] == 1
    assert response.json()["surfaced_candidates"] == 0

    spam_queue = api_client.get("/api/spam-rescue").json()
    candidate_ids = {
        message["gmail_message_id"]
        for account in spam_queue["accounts"]
        for message in account["messages"]
    }
    assert "obvious-spam-1001" not in candidate_ids


def test_feature_flags_include_spam_rescue(api_client, isolated_db):
    response = api_client.get("/api/features")

    assert response.status_code == 200
    assert response.json()["features"]["spam_rescue"] is True


def test_spam_rescue_restore_to_inbox_commits_and_hides_candidate(api_client, seeded_db):
    queue = api_client.get("/api/spam-rescue").json()
    candidate = _candidate_by_gmail_id(queue, "ps-9001")

    response = api_client.post(
        "/api/spam-rescue/staged-actions/commit",
        json={
            "idempotency_key": "spam-rescue-restore-1",
            "actions": [
                {
                    "client_action_id": "client-restore-1",
                    "account_email": candidate["account_email"],
                    "gmail_message_id": candidate["gmail_message_id"],
                    "action": "restore_to_inbox",
                    "expected_version": candidate["state_version"],
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["committed_count"] == 1
    result = payload["results"][0]
    assert result["status"] == "committed"
    assert result["labels_added"] == ["INBOX"]
    assert result["labels_removed"] == ["SPAM"]

    refreshed = api_client.get("/api/spam-rescue").json()
    refreshed_ids = {
        message["gmail_message_id"]
        for account in refreshed["accounts"]
        for message in account["messages"]
    }
    assert "ps-9001" not in refreshed_ids

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT selected_action, recommended_action, action_source,
                   gmail_labels_added_json, gmail_labels_removed_json
            FROM actions_log
            WHERE gmail_message_id = 'ps-9001'
            """
        ).fetchone()
    assert row["selected_action"] == "restore_to_inbox"
    assert row["recommended_action"] == "spam_rescue"
    assert row["action_source"] == "spam_rescue"
    assert row["gmail_labels_added_json"] == '["INBOX"]'
    assert row["gmail_labels_removed_json"] == '["SPAM"]'


def test_spam_rescue_leave_in_spam_commits_without_label_mutation(api_client, seeded_db):
    queue = api_client.get("/api/spam-rescue").json()
    candidate = _candidate_by_gmail_id(queue, "ps-9004")

    response = api_client.post(
        "/api/spam-rescue/staged-actions/commit",
        json={
            "idempotency_key": "spam-rescue-leave-1",
            "actions": [
                {
                    "client_action_id": "client-leave-1",
                    "account_email": candidate["account_email"],
                    "gmail_message_id": candidate["gmail_message_id"],
                    "action": "leave_in_spam",
                    "expected_version": candidate["state_version"],
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["committed_count"] == 1
    result = payload["results"][0]
    assert result["status"] == "committed"
    assert result["labels_added"] == []
    assert result["labels_removed"] == []

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT selected_action, gmail_labels_added_json, gmail_labels_removed_json
            FROM actions_log
            WHERE gmail_message_id = 'ps-9004'
            """
        ).fetchone()
    assert row["selected_action"] == "leave_in_spam"
    assert row["gmail_labels_added_json"] == "[]"
    assert row["gmail_labels_removed_json"] == "[]"


def test_spam_rescue_commit_rejects_stale_state_version(api_client, seeded_db):
    queue = api_client.get("/api/spam-rescue").json()
    candidate = _candidate_by_gmail_id(queue, "ws-9101")

    response = api_client.post(
        "/api/spam-rescue/staged-actions/commit",
        json={
            "idempotency_key": "spam-rescue-stale-1",
            "actions": [
                {
                    "client_action_id": "client-stale-1",
                    "account_email": candidate["account_email"],
                    "gmail_message_id": candidate["gmail_message_id"],
                    "action": "restore_to_inbox",
                    "expected_version": "2026-01-01T00:00:00Z",
                }
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["committed_count"] == 0
    result = payload["results"][0]
    assert result["status"] == "stale"
    assert result["code"] == "stale_spam_rescue_message"


def test_spam_rescue_idempotency_replay_does_not_apply_second_payload(api_client, seeded_db):
    queue = api_client.get("/api/spam-rescue").json()
    restore_candidate = _candidate_by_gmail_id(queue, "ps-9001")
    leave_candidate = _candidate_by_gmail_id(queue, "ps-9004")

    first_response = api_client.post(
        "/api/spam-rescue/staged-actions/commit",
        json={
            "idempotency_key": "same-key",
            "actions": [
                {
                    "client_action_id": "client-idempotent-restore",
                    "account_email": restore_candidate["account_email"],
                    "gmail_message_id": restore_candidate["gmail_message_id"],
                    "action": "restore_to_inbox",
                    "expected_version": restore_candidate["state_version"],
                }
            ],
        },
    )

    assert first_response.status_code == 200
    first_payload = first_response.json()
    assert first_payload["committed_count"] == 1
    assert first_payload.get("idempotent_replay") is None

    second_response = api_client.post(
        "/api/spam-rescue/staged-actions/commit",
        json={
            "idempotency_key": "same-key",
            "actions": [
                {
                    "client_action_id": "client-idempotent-leave",
                    "account_email": leave_candidate["account_email"],
                    "gmail_message_id": leave_candidate["gmail_message_id"],
                    "action": "leave_in_spam",
                    "expected_version": leave_candidate["state_version"],
                }
            ],
        },
    )

    assert second_response.status_code == 200
    second_payload = second_response.json()
    assert second_payload["idempotent_replay"] is True
    assert second_payload["results"][0]["gmail_message_id"] == "ps-9001"
    assert second_payload["results"][0]["action"] == "restore_to_inbox"

    with get_connection() as conn:
        action_rows = conn.execute(
            """
            SELECT gmail_message_id, selected_action
            FROM actions_log
            WHERE action_source = 'spam_rescue'
            ORDER BY id
            """
        ).fetchall()

    assert [dict(row) for row in action_rows] == [
        {
            "gmail_message_id": "ps-9001",
            "selected_action": "restore_to_inbox",
        }
    ]

    refreshed = api_client.get("/api/spam-rescue").json()
    refreshed_ids = {
        message["gmail_message_id"]
        for account in refreshed["accounts"]
        for message in account["messages"]
    }
    assert "ps-9001" not in refreshed_ids
    assert "ps-9004" in refreshed_ids
