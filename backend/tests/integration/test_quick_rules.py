from __future__ import annotations

from app.db.database import get_connection
from app.services.review_queue import apply_message_action, get_review_queue, reclassify_pending_messages
from app.services.rules import create_rule


def _message_id_by_subject(subject: str) -> int:
    with get_connection() as conn:
        row = conn.execute("SELECT id FROM messages WHERE subject = ?", (subject,)).fetchone()
    return int(row["id"])


def test_quick_rule_like_flow_reclassifies_and_applies_source_message(seeded_db):
    source_subject = "Weekly digest: patio, paint, and repair ideas"
    source_id = _message_id_by_subject(source_subject)
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "created_from_message_id": str(source_id),
        }
    )
    reclassified = reclassify_pending_messages()
    applied = apply_message_action(source_id, "bulk_mail")

    assert rule["rule_type"] == "domain"
    assert applied["selected_action"] == "bulk_mail"
    assert reclassified["reclassified_messages"] == 30

    with get_connection() as conn:
        rule_row = conn.execute(
            "SELECT match_count FROM rules WHERE id = ?",
            (rule["id"],),
        ).fetchone()
    assert rule_row["match_count"] >= 1

    queue = get_review_queue()
    subjects = {
        message["subject"]
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    }
    assert source_subject not in subjects


def test_disabled_rule_does_not_reclassify_future_messages(seeded_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "north-invest.com",
            "action": "trash",
        }
    )
    with get_connection() as conn:
        conn.execute("UPDATE rules SET enabled = 0 WHERE id = ?", (rule["id"],))
    reclassify_pending_messages()
    queue = get_review_queue()
    personal_keep = next(
        group
        for account in queue["accounts"]
        if account["account_email"] == "personal@example.com"
        for group in account["groups"]
        if group["category"] == "keep"
    )
    subjects = [message["subject"] for message in personal_keep["messages"]]
    assert "Account recovery confirmation needed" in subjects
