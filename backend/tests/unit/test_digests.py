from __future__ import annotations

from datetime import datetime, timezone

from app.db.runtime import execute_sql, fetch_one, get_connection
from app.services.digests import (
    PROCESSED_DIGEST_LIMIT,
    ScheduledDigestService,
    build_processed_digest_payload,
    send_due_processed_digests,
    send_processed_digest,
)
from app.services.mailer import MailDeliveryResult
from app.services.notification_settings import update_notification_settings
from app.services.review_queue import apply_message_action, sync_unread_messages
from app.services.rules import create_rule


def test_processed_digest_payload_summarizes_user_activity(isolated_db):
    sync_unread_messages()
    update_notification_settings(
        {
            "recipient_email": "digest@example.com",
            "digest_enabled": True,
            "digest_time": "18:30",
        }
    )

    apply_message_action(1, "keep")
    apply_message_action(2, "trash")
    create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "example.com",
            "action": "junk_review",
        }
    )

    payload = build_processed_digest_payload(user_id=1)

    assert payload["digest_type"] == "daily_processed"
    assert payload["recipient_email"] == "digest@example.com"
    assert payload["digest_enabled"] is True
    assert payload["digest_time"] == "18:30"
    assert payload["ai_summary_enabled"] is False
    assert payload["ai_summary"] is None
    assert payload["processed_count"] == 2
    assert payload["new_rules_count"] == 1
    assert payload["queue_count"] == 28
    assert payload["counts_by_action"]["keep"] == 1
    assert payload["counts_by_action"]["trash"] == 1
    assert payload["counts_by_action"]["bulk_mail"] == 0
    assert payload["counts_by_source"]["manual"] == 2
    assert len(payload["processed_messages"]) == 2
    assert payload["processed_messages"][0]["action_source_label"] == "Manual"
    assert payload["top_sender_domains"]
    assert "Processed messages: 2" in payload["plain_text_preview"]
    assert "Auto-cleaned messages: 0" in payload["plain_text_preview"]
    assert "Top sender domains:" in payload["plain_text_preview"]
    assert "New rules created: 1" in payload["plain_text_preview"]
    assert "Open Fynish:" in payload["plain_text_preview"]
    assert "html_preview" in payload
    assert "<html" in payload["html_preview"]
    assert "Processed Mail" in payload["html_preview"]
    assert "Top sender domains" in payload["html_preview"]


def test_processed_digest_payload_includes_ai_summary_when_enabled(
    monkeypatch,
    isolated_db,
):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "ai_digest_summary_enabled": True,
        }
    )
    apply_message_action(1, "keep")

    def fake_build_ai_digest_summary(payload, *, user_id, enabled_for_user):
        assert user_id == 1
        assert enabled_for_user is True
        assert payload["processed_messages"][0]["preview"]
        return {
            "generated": True,
            "provider": "openai",
            "model": "gpt-5-mini",
            "headline": "Mostly routine mail.",
            "summary": "Fynish kept one useful-looking message.",
            "key_takeaways": ["One kept message was included."],
            "auto_clean_review": {
                "count": 0,
                "summary": "No messages were auto-cleaned in this digest window.",
                "notable_items": [],
            },
            "notable_kept_messages": [
                {
                    "subject": "Example kept message",
                    "reason": "It was kept for review.",
                }
            ],
            "top_noise_sources": [],
            "caveats": ["Summary is based on digest metadata and snippets."],
        }

    monkeypatch.setattr(
        "app.services.digests.build_ai_digest_summary",
        fake_build_ai_digest_summary,
    )

    payload = build_processed_digest_payload(user_id=1)

    assert payload["ai_summary_enabled"] is True
    assert payload["ai_summary"]["headline"] == "Mostly routine mail."
    assert payload["ai_summary_error"] is None
    assert "Today's inbox briefing:" in payload["plain_text_preview"]
    assert "Mostly routine mail." in payload["html_preview"]


def test_processed_digest_payload_notes_ai_summary_unavailable_when_helper_returns_none(
    monkeypatch,
    isolated_db,
):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "ai_digest_summary_enabled": True,
        }
    )
    apply_message_action(1, "keep")

    monkeypatch.setattr(
        "app.services.digests.build_ai_digest_summary",
        lambda *args, **kwargs: None,
    )

    payload = build_processed_digest_payload(user_id=1)

    assert payload["ai_summary_enabled"] is True
    assert payload["ai_summary"] is None
    assert payload["ai_summary_error"] == (
        "AI summary was unavailable, so this digest was sent with the standard summary only."
    )
    assert payload["ai_summary_error"] in payload["plain_text_preview"]
    assert payload["ai_summary_error"] in payload["html_preview"]
    assert "Processed Mail" in payload["html_preview"]


def test_processed_digest_payload_survives_ai_summary_exception(
    monkeypatch,
    isolated_db,
):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "ai_digest_summary_enabled": True,
        }
    )
    apply_message_action(1, "keep")

    def fail_ai_summary(*args, **kwargs):
        raise RuntimeError("quota exhausted")

    monkeypatch.setattr(
        "app.services.digests.build_ai_digest_summary",
        fail_ai_summary,
    )

    payload = build_processed_digest_payload(user_id=1)

    assert payload["processed_count"] == 1
    assert payload["ai_summary"] is None
    assert payload["ai_summary_error"] == (
        "AI summary was unavailable, so this digest was sent with the standard summary only."
    )
    assert "Processed messages: 1" in payload["plain_text_preview"]


def test_processed_digest_highlights_and_sorts_auto_cleaned_messages(isolated_db):
    sync_unread_messages()

    apply_message_action(1, "keep")
    apply_message_action(2, "trash")

    with get_connection() as conn:
        execute_sql(
            conn,
            """
            UPDATE actions_log
            SET action_source = 'high_confidence_auto_clean',
                created_at = '2026-05-18T12:00:00+00:00'
            WHERE selected_action = 'keep'
            """,
        )
        execute_sql(
            conn,
            """
            UPDATE actions_log
            SET action_source = 'manual',
                created_at = '2026-05-18T12:05:00+00:00'
            WHERE selected_action = 'trash'
            """,
        )

    payload = build_processed_digest_payload(
        user_id=1,
        as_of=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
    )

    assert payload["counts_by_source"]["high_confidence_auto_clean"] == 1
    assert payload["processed_messages"][0]["action_source"] == "high_confidence_auto_clean"
    assert payload["processed_messages"][0]["action_source_label"] == "Auto-clean"
    assert payload["processed_messages"][1]["action_source"] == "manual"
    assert "Auto-cleaned messages: 1" in payload["plain_text_preview"]
    assert "[Auto-clean | Keep]" in payload["plain_text_preview"]
    assert "Auto-cleaned" in payload["html_preview"]
    assert "Auto-clean" in payload["html_preview"]


def test_processed_digest_payload_falls_back_to_user_email_when_recipient_missing(
    isolated_db,
):
    sync_unread_messages()

    payload = build_processed_digest_payload(user_id=1)

    assert payload["recipient_email"] == "local-owner@fynish.local"


def test_processed_digest_payload_caps_processed_rows_at_fifty(isolated_db):
    sync_unread_messages()
    digest_as_of = datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc)
    digest_created_at = "2026-05-18T12:00:00+00:00"

    with get_connection() as conn:
        for index in range(PROCESSED_DIGEST_LIMIT + 5):
            execute_sql(
                conn,
                """
                INSERT INTO actions_log (
                    gmail_message_id,
                    account_email,
                    message_id,
                    selected_action,
                    recommended_action,
                    user_overrode,
                    gmail_labels_added_json,
                    gmail_labels_removed_json,
                    created_at
                ) VALUES (
                    :gmail_message_id,
                    :account_email,
                    :message_id,
                    'keep',
                    'keep',
                    0,
                    '[]',
                    '[]',
                    :created_at
                )
                """,
                {
                    "gmail_message_id": f"overflow-{index}",
                    "account_email": "family@example.net",
                    "message_id": 1,
                    "created_at": digest_created_at,
                },
            )

    payload = build_processed_digest_payload(user_id=1, as_of=digest_as_of)

    assert payload["processed_count"] == PROCESSED_DIGEST_LIMIT + 5
    assert len(payload["processed_messages"]) == PROCESSED_DIGEST_LIMIT
    assert payload["processed_overflow_count"] == 5
    assert "+ 5 more processed messages not shown" in payload["plain_text_preview"]


def test_send_processed_digest_records_sent_delivery(monkeypatch, isolated_db):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "digest_time": "08:00",
            "recipient_email": "digest@example.com",
        }
    )
    apply_message_action(1, "keep")

    def fake_send_email(**kwargs):
        assert kwargs["html_body"].startswith("<!doctype html>")
        assert "Processed Mail" in kwargs["html_body"]
        return MailDeliveryResult(
            provider="postmark",
            to_email=kwargs["to_email"],
            subject=kwargs["subject"],
            message_id="pm-123",
        )

    monkeypatch.setattr("app.services.digests.send_email", fake_send_email)

    result = send_processed_digest(1)

    assert result["status"] == "sent"
    assert result["provider"] == "postmark"
    assert result["recipient_email"] == "digest@example.com"

    with get_connection() as conn:
        row = fetch_one(
            conn,
            """
            SELECT status, recipient_email, processed_count
            FROM digest_delivery_log
            WHERE user_id = 1
            ORDER BY id DESC
            LIMIT 1
            """,
        )

    assert row["status"] == "sent"
    assert row["recipient_email"] == "digest@example.com"
    assert int(row["processed_count"]) == 1


def test_send_processed_digest_skips_second_send_for_same_local_day(monkeypatch, isolated_db):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "digest_time": "08:00",
            "recipient_email": "digest@example.com",
        }
    )
    apply_message_action(1, "keep")

    sent_count = 0

    def fake_send_email(**kwargs):
        nonlocal sent_count
        sent_count += 1
        return MailDeliveryResult(
            provider="postmark",
            to_email=kwargs["to_email"],
            subject=kwargs["subject"],
            message_id=f"pm-{sent_count}",
        )

    monkeypatch.setattr("app.services.digests.send_email", fake_send_email)

    first = send_processed_digest(
        1,
        as_of=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
    )
    second = send_processed_digest(
        1,
        as_of=datetime(2026, 5, 18, 14, 5, tzinfo=timezone.utc),
    )

    assert first["status"] == "sent"
    assert second["status"] == "skipped"
    assert second["reason"] == "Digest already sent for this local day"
    assert sent_count == 1


def test_send_due_processed_digests_only_sends_due_users(monkeypatch, isolated_db):
    sync_unread_messages()
    update_notification_settings(
        {
            "digest_enabled": True,
            "digest_time": "07:00",
            "recipient_email": "digest@example.com",
        }
    )
    apply_message_action(1, "trash")

    captured_user_ids: list[int] = []

    def fake_send_processed_digest(user_id: int, as_of=None):
        captured_user_ids.append(user_id)
        return {
            "user_id": user_id,
            "status": "sent",
            "recipient_email": "digest@example.com",
            "processed_count": 1,
            "new_rules_count": 0,
            "queue_count": 29,
            "provider": "postmark",
            "message_id": "pm-456",
            "sent_at": "2026-05-18T14:00:00+00:00",
        }

    monkeypatch.setattr(
        "app.services.digests.validate_gmail_digest_sender",
        lambda: {"auth_status": "connected"},
    )
    monkeypatch.setattr("app.services.digests.send_processed_digest", fake_send_processed_digest)

    result = send_due_processed_digests(
        as_of=datetime(2026, 5, 18, 14, 0, tzinfo=timezone.utc),
    )

    assert captured_user_ids == [1]
    assert result["status"] == "completed"
    assert result["users_considered"] >= 1
    assert result["users_due"] == 1
    assert result["sent"] == 1
    assert result["failed"] == 0


def test_scheduled_digest_service_returns_disabled_when_feature_is_off():
    service = ScheduledDigestService(enabled=False)

    result = service.run_once()

    assert result["status"] == "disabled"
    assert result["sent"] == 0


def test_scheduled_digest_service_returns_scheduler_result_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.digests.send_due_processed_digests",
        lambda: {
            "status": "completed",
            "users_considered": 2,
            "users_due": 1,
            "sent": 1,
            "skipped": 1,
            "failed": 0,
            "user_summaries": [],
            "ran_at": "2026-05-18T14:00:00+00:00",
        },
    )

    service = ScheduledDigestService(enabled=True)
    result = service.run_once()

    assert result["status"] == "completed"
    assert result["sent"] == 1
