from __future__ import annotations

from app.db.database import get_connection
from app.services.notification_settings import get_notification_settings
from app.services.review_queue import apply_message_action, sync_unread_messages


def test_processed_digest_preview_returns_user_scoped_payload(api_client, isolated_db):
    # Simulate an upgrade from a database whose AI summary setting was enabled.
    get_notification_settings()
    with get_connection() as conn:
        conn.execute("UPDATE notification_settings_by_user SET ai_digest_summary_enabled = 1")
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
    assert "Processed Mail" in digest["html_preview"]
    assert digest["ai_summary_enabled"] is False
    assert digest["ai_summary"] is None
    assert digest["ai_summary_error"] is None
