from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app.db.database import get_connection
from app.services.review_queue import apply_message_action, sync_unread_messages


def test_processed_messages_prioritizes_recent_auto_cleaned_then_recent(api_client, isolated_db):
    sync_unread_messages()

    apply_message_action(1, "keep")
    apply_message_action(2, "trash")
    recent_auto_cleaned_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    newer_manual_at = datetime.now(UTC).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE actions_log
            SET action_source = 'high_confidence_auto_clean',
                created_at = ?
            WHERE selected_action = 'keep'
            """,
            (recent_auto_cleaned_at,),
        )
        conn.execute(
            """
            UPDATE actions_log
            SET action_source = 'manual',
                created_at = ?
            WHERE selected_action = 'trash'
            """,
            (newer_manual_at,),
        )

    response = api_client.get("/api/messages/processed")
    assert response.status_code == 200

    payload = response.json()["messages"]
    assert len(payload) >= 2
    assert payload[0]["selected_action"] == "keep"
    assert payload[0]["action_source"] == "high_confidence_auto_clean"
    assert payload[1]["selected_action"] == "trash"
    assert payload[1]["action_source"] == "manual"
    assert payload[0]["account_email"]
    assert payload[0]["sender"]
    assert payload[0]["sender_email"]
    assert payload[0]["sender_domain"]
    assert payload[0]["subject"]
    assert "preview" in payload[0]


def test_processed_messages_does_not_prioritize_old_auto_cleaned(api_client, isolated_db):
    sync_unread_messages()

    apply_message_action(1, "keep")
    apply_message_action(2, "trash")
    old_auto_cleaned_at = (datetime.now(UTC) - timedelta(days=4)).isoformat()
    recent_manual_at = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE actions_log
            SET action_source = 'high_confidence_auto_clean',
                created_at = ?
            WHERE selected_action = 'keep'
            """,
            (old_auto_cleaned_at,),
        )
        conn.execute(
            """
            UPDATE actions_log
            SET action_source = 'manual',
                created_at = ?
            WHERE selected_action = 'trash'
            """,
            (recent_manual_at,),
        )

    response = api_client.get("/api/messages/processed")
    assert response.status_code == 200

    payload = response.json()["messages"]
    assert len(payload) >= 2
    assert payload[0]["selected_action"] == "trash"
    assert payload[0]["action_source"] == "manual"
    assert payload[1]["selected_action"] == "keep"
    assert payload[1]["action_source"] == "high_confidence_auto_clean"


def test_processed_messages_respects_limit(api_client, isolated_db):
    sync_unread_messages()
    apply_message_action(1, "keep")
    apply_message_action(2, "trash")

    response = api_client.get("/api/messages/processed?limit=1")
    assert response.status_code == 200
    payload = response.json()["messages"]
    assert len(payload) == 1


def test_processed_messages_exposes_longer_preview_for_expanded_ui(api_client, isolated_db):
    sync_unread_messages()

    with get_connection() as conn:
      conn.execute(
          """
          UPDATE messages
          SET snippet = ?, body_preview = ?
          WHERE id = 1
          """,
          (
              "Short snippet",
              "This is a much longer body preview intended to confirm that the processed mail "
              "view receives enough text to expand into multiple visible lines when the row is opened.\n\n"
              "The second paragraph should remain separated for the expanded preview.",
          ),
      )

    apply_message_action(1, "keep")

    response = api_client.get("/api/messages/processed")
    assert response.status_code == 200
    payload = response.json()["messages"]
    assert len(payload[0]["preview"]) > 88
    assert "\n\nThe second paragraph" in payload[0]["preview"]


def test_processed_messages_decodes_html_entities_and_hides_tracking_urls(api_client, isolated_db):
    sync_unread_messages()

    with get_connection() as conn:
      conn.execute(
          """
          UPDATE messages
          SET snippet = ?, body_preview = ?
          WHERE id = 1
          """,
          (
              "Markiplier&#39;s Iron Lung is available",
              "YouTube\n"
              "<https://c.gle/AOPyDKRxUNTrUTjAuW83Uwx-lpDZUi38Ufp5ScgZa0eoMROJ0Qy81vaNO1t1zgaw0PpEykL>\n"
              "FIFA World Cup 2026 kicks off on FOX One\n"
              "https://example.com/tracking-token\n"
              "Then $19.99/mo. New users only.",
          ),
      )

    apply_message_action(1, "bulk_mail")

    response = api_client.get("/api/messages/processed")
    assert response.status_code == 200
    preview = response.json()["messages"][0]["preview"]
    assert "Markiplier's Iron Lung" in preview
    assert "FIFA World Cup 2026 kicks off on FOX One" in preview
    assert "https://c.gle" not in preview
    assert "https://example.com" not in preview
