from __future__ import annotations

from app.db.database import get_connection
from app.services.review_queue import get_review_queue
from app.services.spam_rescue import get_spam_rescue_queue


def _all_candidates(queue: dict) -> list[dict]:
    return [
        message
        for account in queue["accounts"]
        for message in account["messages"]
    ]


def test_spam_rescue_queue_surfaces_only_mock_rescue_candidates(seeded_db):
    queue = get_spam_rescue_queue()
    candidates = _all_candidates(queue)
    candidate_ids = {message["gmail_message_id"] for message in candidates}

    assert queue["count"] == len(candidates)
    assert "ps-9001" in candidate_ids
    assert "ps-9004" in candidate_ids
    assert "ws-9101" in candidate_ids
    assert "ws-9102" in candidate_ids
    assert "fs-9201" in candidate_ids
    assert "ps-9002" not in candidate_ids
    assert "ps-9003" not in candidate_ids
    assert "fs-9202" not in candidate_ids


def test_spam_rescue_candidate_payload_includes_source_and_reasons(seeded_db):
    queue = get_spam_rescue_queue()
    invoice = next(
        message
        for message in _all_candidates(queue)
        if message["gmail_message_id"] == "ps-9001"
    )

    assert invoice["id"] == "personal@example.com:ps-9001"
    assert invoice["source_label"] == "spam"
    assert invoice["review_surface"] == "spam_rescue"
    assert invoice["state_version"] == invoice["received_at"]
    assert invoice["confidence"] >= 0.6
    assert invoice["rescue_reasons"]
    assert invoice["protection_reasons"]


def test_spam_rescue_queue_does_not_change_review_queue_or_persist_spam_messages(seeded_db):
    before_queue = get_review_queue()
    spam_queue = get_spam_rescue_queue()
    after_queue = get_review_queue()

    assert spam_queue["count"] > 0
    assert after_queue == before_queue

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE provider_labels_json LIKE '%SPAM%'
               OR gmail_labels_json LIKE '%SPAM%'
            """
        ).fetchone()
    assert row["count"] == 0
