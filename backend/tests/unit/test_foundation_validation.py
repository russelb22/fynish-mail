from __future__ import annotations

from app.db.foundation_migration import migrate_foundation_schema
from app.db.foundation_validation import validate_foundation_migration
from app.services.review_queue import sync_unread_messages


def test_foundation_validation_passes_after_migration(seeded_db):
    migrate_foundation_schema()

    payload = validate_foundation_migration()

    assert payload["failed"] == 0
    assert payload["passed"] >= 10


def test_foundation_validation_catches_missing_provider_message_id(isolated_db):
    sync_unread_messages()
    migrate_foundation_schema()

    from app.db.database import get_connection

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE messages
            SET provider_message_id = NULL
            WHERE id = (SELECT id FROM messages ORDER BY id ASC LIMIT 1)
            """
        )

    payload = validate_foundation_migration()
    lines = [line for _ok, line in payload["results"]]

    assert payload["failed"] >= 1
    assert any(
        "FAIL messages.provider_message_id is fully backfilled" == line for line in lines
    )
