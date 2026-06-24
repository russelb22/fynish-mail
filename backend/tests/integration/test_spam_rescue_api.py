from __future__ import annotations

from app.db.database import get_connection


def _candidate_by_gmail_id(payload: dict, gmail_message_id: str) -> dict:
    return next(
        message
        for account in payload["accounts"]
        for message in account["messages"]
        if message["gmail_message_id"] == gmail_message_id
    )


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
