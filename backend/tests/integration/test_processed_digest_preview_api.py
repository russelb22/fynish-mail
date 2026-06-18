from __future__ import annotations

from app.services.notification_settings import update_notification_settings
from app.services.review_queue import apply_message_action, sync_unread_messages


def test_processed_digest_preview_returns_user_scoped_payload(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "keep")

    response = api_client.get("/api/digests/processed/preview")

    assert response.status_code == 200
    digest = response.json()["digest"]
    assert digest["digest_type"] == "daily_processed"
    assert digest["processed_count"] == 1
    assert digest["counts_by_action"]["keep"] == 1
    assert "plain_text_preview" in digest
    assert "Processed Mail:" in digest["plain_text_preview"]


def test_processed_digest_preview_survives_ai_summary_failure(
    api_client,
    isolated_db,
    monkeypatch,
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
        raise RuntimeError("OpenAI quota unavailable")

    monkeypatch.setattr(
        "app.services.digests.build_ai_digest_summary",
        fail_ai_summary,
    )

    response = api_client.get("/api/digests/processed/preview")

    assert response.status_code == 200
    digest = response.json()["digest"]
    assert digest["processed_count"] == 1
    assert digest["ai_summary"] is None
    assert digest["ai_summary_error"] == (
        "AI summary was unavailable, so this digest was sent with the standard summary only."
    )
