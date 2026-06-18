from __future__ import annotations

from app.db.database import get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.review_queue import UnsafeMessageActionError


def _first_queue_message(api_client):
    response = api_client.get("/api/review-queue")
    assert response.status_code == 200
    for account in response.json()["accounts"]:
        for group in account["groups"]:
            if group["messages"]:
                return group["messages"][0]
    raise AssertionError("Expected at least one queued message")


def _queue_message_by_subject(api_client, subject: str):
    response = api_client.get("/api/review-queue")
    assert response.status_code == 200
    for account in response.json()["accounts"]:
        for group in account["groups"]:
            for message in group["messages"]:
                if message["subject"] == subject:
                    return message
    raise AssertionError(f"Expected queued message with subject {subject!r}")


def _first_two_queue_messages_with_different_domains(api_client):
    response = api_client.get("/api/review-queue")
    assert response.status_code == 200
    messages = [
        message
        for account in response.json()["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    ]
    for first in messages:
        for second in messages:
            if first["id"] != second["id"] and first["sender_domain"] != second["sender_domain"]:
                return first, second
    raise AssertionError("Expected at least two queued messages with different sender domains")


def test_review_queue_includes_state_version(api_client, seeded_db):
    message = _first_queue_message(api_client)

    assert "state_version" in message
    assert message["state_version"]
    assert message["queue_source"] == "classifier"
    assert message["queue_source_label"] is None
    assert message["queue_source_detail"] is None


def test_commit_staged_action_processes_non_live_message(api_client, seeded_db):
    message = _first_queue_message(api_client)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-commit-1",
            "actions": [
                {
                    "client_action_id": "client-1",
                    "message_id": message["id"],
                    "action": "keep",
                    "expected_version": message["state_version"],
                }
            ],
        },
    )

    assert response.status_code == 200
    assert response.json()["committed_count"] == 1
    assert response.json()["failed_count"] == 0
    assert response.json()["results"][0] == {
        "client_action_id": "client-1",
        "message_id": message["id"],
        "action": "keep",
        "status": "committed",
        "code": None,
        "message": "Committed.",
        "executed": True,
        "labels_added": [],
        "labels_removed": [],
        "rule_id": None,
        "reclassified_messages": 0,
    }

    refreshed = api_client.get("/api/review-queue").json()
    queued_ids = {
        item["id"]
        for account in refreshed["accounts"]
        for group in account["groups"]
        for item in group["messages"]
    }
    assert message["id"] not in queued_ids


def test_commit_staged_action_reports_stale_version(api_client, seeded_db):
    message = _first_queue_message(api_client)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-stale-version",
            "actions": [
                {
                    "client_action_id": "client-stale",
                    "message_id": message["id"],
                    "action": "keep",
                    "expected_version": "not-the-current-version",
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert response.json()["committed_count"] == 0
    assert response.json()["failed_count"] == 1
    assert result["status"] == "stale"
    assert result["code"] == "stale_message"


def test_commit_staged_action_requires_expected_version(api_client, seeded_db):
    message = _first_queue_message(api_client)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-missing-version",
            "actions": [
                {
                    "client_action_id": "client-missing-version",
                    "message_id": message["id"],
                    "action": "keep",
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert response.json()["committed_count"] == 0
    assert response.json()["failed_count"] == 1
    assert result["status"] == "stale"
    assert result["code"] == "missing_state_version"

    with get_connection() as conn:
        message_row = conn.execute(
            "SELECT reviewed FROM messages WHERE id = ?",
            (message["id"],),
        ).fetchone()
    assert message_row["reviewed"] == 0


def test_commit_staged_action_reports_duplicate_message(api_client, seeded_db):
    message = _first_queue_message(api_client)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-duplicate",
            "actions": [
                {
                    "client_action_id": "client-first",
                    "message_id": message["id"],
                    "action": "keep",
                    "expected_version": message["state_version"],
                },
                {
                    "client_action_id": "client-duplicate",
                    "message_id": message["id"],
                    "action": "trash",
                    "expected_version": message["state_version"],
                },
            ],
        },
    )

    assert response.status_code == 200
    results = response.json()["results"]
    assert results[0]["status"] == "committed"
    assert results[1]["status"] == "failed"
    assert results[1]["code"] == "duplicate_staged_message"


def test_commit_staged_action_reports_gmail_reconnect_required(
    api_client,
    seeded_db,
    monkeypatch,
):
    message = _first_queue_message(api_client)

    monkeypatch.setattr("app.services.staged_commit._has_modify_scope", lambda _row: True)

    def fail_execute(*_args, **_kwargs):
        raise GmailReadonlySyncError(
            "Stored Gmail credentials were expired or revoked. Reconnect the account."
        )

    monkeypatch.setattr("app.services.staged_commit.execute_message_action", fail_execute)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-reconnect",
            "actions": [
                {
                    "client_action_id": "client-reconnect",
                    "message_id": message["id"],
                    "action": "trash",
                    "expected_version": message["state_version"],
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["code"] == "gmail_reconnect_required"
    assert "Reconnect the account" in result["message"]


def test_commit_staged_action_reports_unsafe_action(
    api_client,
    seeded_db,
    monkeypatch,
):
    message = _queue_message_by_subject(api_client, "Your daily digest")
    message_id = message["id"]

    def fail_apply(*_args, **_kwargs):
        raise UnsafeMessageActionError(f"Unsafe Gmail action plan for message {message_id}")

    monkeypatch.setattr("app.services.staged_commit.apply_message_action", fail_apply)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-unsafe",
            "actions": [
                {
                    "client_action_id": "client-unsafe",
                    "message_id": message_id,
                    "action": "trash",
                    "expected_version": message["state_version"],
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["code"] == "unsafe_message_action"


def test_commit_staged_action_replays_idempotent_response_without_duplicate_log(
    api_client,
    seeded_db,
):
    message = _first_queue_message(api_client)
    payload = {
        "idempotency_key": "test-idempotent-replay",
        "actions": [
            {
                "client_action_id": "client-idempotent",
                "message_id": message["id"],
                "action": "keep",
                "expected_version": message["state_version"],
            }
        ],
    }

    first_response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json=payload,
    )
    second_response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json=payload,
    )

    assert first_response.status_code == 200
    assert second_response.status_code == 200
    assert first_response.json()["committed_count"] == 1
    assert second_response.json()["committed_count"] == 1
    assert second_response.json()["idempotent_replay"] is True
    assert second_response.json()["results"] == first_response.json()["results"]

    with get_connection() as conn:
        action_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM actions_log
            WHERE message_id = ?
            """,
            (message["id"],),
        ).fetchone()
    assert action_count["count"] == 1


def test_commit_staged_rule_action_creates_rule_and_processes_source_message(
    api_client,
    seeded_db,
):
    message = _first_queue_message(api_client)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-rule-commit",
            "actions": [
                {
                    "client_action_id": "client-rule",
                    "message_id": message["id"],
                    "action": "junk_review",
                    "expected_version": message["state_version"],
                    "rule": {
                        "scope": "global",
                        "account_email": None,
                        "rule_type": "domain",
                        "pattern": message["sender_domain"],
                        "action": "junk_review",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "committed"
    assert result["rule_id"] is not None
    assert result["reclassified_messages"] >= 0

    with get_connection() as conn:
        rule = conn.execute(
            """
            SELECT pattern, action, enabled
            FROM rules
            WHERE id = ?
            """,
            (result["rule_id"],),
        ).fetchone()
        message_row = conn.execute(
            "SELECT reviewed, current_category FROM messages WHERE id = ?",
            (message["id"],),
        ).fetchone()
    assert dict(rule) == {
        "pattern": message["sender_domain"],
        "action": "junk_review",
        "enabled": 1,
    }
    assert message_row["reviewed"] == 1
    assert message_row["current_category"] == "junk_review"


def test_commit_staged_rule_action_does_not_stale_later_batch_item(
    api_client,
    seeded_db,
    monkeypatch,
):
    rule_message, later_message = _first_two_queue_messages_with_different_domains(api_client)
    monkeypatch.setattr("app.services.staged_commit._has_modify_scope", lambda _row: False)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-rule-batch-no-self-stale",
            "actions": [
                {
                    "client_action_id": "client-rule-batch",
                    "message_id": rule_message["id"],
                    "action": "junk_review",
                    "expected_version": rule_message["state_version"],
                    "rule": {
                        "scope": "global",
                        "account_email": None,
                        "rule_type": "domain",
                        "pattern": rule_message["sender_domain"],
                        "action": "junk_review",
                    },
                },
                {
                    "client_action_id": "client-later-batch",
                    "message_id": later_message["id"],
                    "action": "keep",
                    "expected_version": later_message["state_version"],
                },
            ],
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["committed_count"] == 2
    assert payload["failed_count"] == 0
    assert [result["status"] for result in payload["results"]] == [
        "committed",
        "committed",
    ]

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT id, reviewed
            FROM messages
            WHERE id IN (?, ?)
            """,
            (rule_message["id"], later_message["id"]),
        ).fetchall()
    assert {row["id"]: row["reviewed"] for row in rows} == {
        rule_message["id"]: 1,
        later_message["id"]: 1,
    }


def test_commit_staged_rule_action_reports_partial_failure_after_rule_creation(
    api_client,
    seeded_db,
    monkeypatch,
):
    message = _first_queue_message(api_client)

    def fail_apply(*_args, **_kwargs):
        raise GmailReadonlySyncError("Stored Gmail credentials were expired or revoked.")

    monkeypatch.setattr("app.services.staged_commit.apply_message_action", fail_apply)

    response = api_client.post(
        "/api/review-queue/staged-actions/commit",
        json={
            "idempotency_key": "test-rule-partial",
            "actions": [
                {
                    "client_action_id": "client-rule-partial",
                    "message_id": message["id"],
                    "action": "junk_review",
                    "expected_version": message["state_version"],
                    "rule": {
                        "scope": "global",
                        "account_email": None,
                        "rule_type": "domain",
                        "pattern": message["sender_domain"],
                        "action": "junk_review",
                    },
                }
            ],
        },
    )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["status"] == "failed"
    assert result["code"] == "gmail_reconnect_required"
    assert result["rule_id"] is not None
    assert result["reclassified_messages"] >= 0

    with get_connection() as conn:
        rule = conn.execute("SELECT id FROM rules WHERE id = ?", (result["rule_id"],)).fetchone()
        message_row = conn.execute(
            "SELECT reviewed FROM messages WHERE id = ?",
            (message["id"],),
        ).fetchone()
    assert rule is not None
    assert message_row["reviewed"] == 0
