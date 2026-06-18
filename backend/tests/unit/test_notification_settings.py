from __future__ import annotations

import pytest

from app.db.database import get_connection
from app.services.notification_settings import (
    get_notification_settings,
    update_notification_settings,
)


def test_notification_settings_defaults_are_seeded(isolated_db):
    settings = get_notification_settings()
    assert settings["enabled"] is False
    assert settings["recipient_email"] is None
    assert settings["timezone"] == "America/Los_Angeles"
    assert settings["morning_enabled"] is True
    assert settings["morning_time"] == "08:00"
    assert settings["evening_enabled"] is True
    assert settings["evening_time"] == "16:00"
    assert settings["send_only_if_queue_nonempty"] is True
    assert settings["digest_enabled"] is False
    assert settings["digest_time"] == "17:00"
    assert settings["ai_digest_summary_enabled"] is False

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT ns.user_id, u.email
            FROM notification_settings_by_user ns
            JOIN users u ON u.id = ns.user_id
            """
        ).fetchone()
    assert row is not None
    assert row["email"] == "local-owner@fynish.local"


def test_notification_settings_update_persists_changes(isolated_db):
    updated = update_notification_settings(
        {
            "enabled": True,
            "recipient_email": " Owner@Example.com ",
            "timezone": "America/New_York",
            "morning_time": "09:15",
            "evening_enabled": False,
            "send_only_if_queue_nonempty": False,
            "digest_enabled": True,
            "digest_time": "18:30",
            "ai_digest_summary_enabled": True,
        }
    )
    assert updated["enabled"] is True
    assert updated["recipient_email"] == "owner@example.com"
    assert updated["timezone"] == "America/New_York"
    assert updated["morning_time"] == "09:15"
    assert updated["evening_enabled"] is False
    assert updated["send_only_if_queue_nonempty"] is False
    assert updated["digest_enabled"] is True
    assert updated["digest_time"] == "18:30"
    assert updated["ai_digest_summary_enabled"] is True

    reloaded = get_notification_settings()
    assert reloaded == updated

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT recipient_email, timezone, morning_time, evening_enabled,
                   digest_enabled, digest_time, ai_digest_summary_enabled
            FROM notification_settings_by_user
            """
        ).fetchone()
    assert row["recipient_email"] == "owner@example.com"
    assert row["timezone"] == "America/New_York"
    assert row["morning_time"] == "09:15"
    assert int(row["evening_enabled"]) == 0
    assert int(row["digest_enabled"]) == 1
    assert row["digest_time"] == "18:30"
    assert int(row["ai_digest_summary_enabled"]) == 1


def test_notification_settings_reject_invalid_timezone(isolated_db):
    with pytest.raises(ValueError, match="valid IANA timezone"):
        update_notification_settings({"timezone": "Mars/Olympus"})


def test_notification_settings_reject_invalid_time(isolated_db):
    with pytest.raises(ValueError, match="morning_time"):
        update_notification_settings({"morning_time": "25:00"})


def test_notification_settings_reject_invalid_digest_time(isolated_db):
    with pytest.raises(ValueError, match="digest_time"):
        update_notification_settings({"digest_time": "99:00"})


def test_notification_settings_reject_invalid_recipient_email(isolated_db):
    with pytest.raises(ValueError, match="recipient_email"):
        update_notification_settings({"recipient_email": "not-an-email"})
