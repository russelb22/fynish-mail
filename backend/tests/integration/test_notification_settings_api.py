from __future__ import annotations


def test_notification_settings_endpoint_returns_defaults(api_client):
    response = api_client.get("/api/settings/notifications")
    assert response.status_code == 200
    payload = response.json()["settings"]
    assert payload["timezone"] == "America/Los_Angeles"
    assert payload["morning_time"] == "08:00"
    assert payload["evening_time"] == "16:00"
    assert payload["digest_enabled"] is False
    assert payload["digest_time"] == "17:00"
    assert payload["ai_digest_summary_enabled"] is False


def test_notification_settings_endpoint_updates_values(api_client):
    response = api_client.patch(
        "/api/settings/notifications",
        json={
            "enabled": True,
            "recipient_email": "triage@example.com",
            "morning_time": "07:45",
            "evening_time": "17:05",
            "digest_enabled": True,
            "digest_time": "18:20",
            "ai_digest_summary_enabled": True,
        },
    )
    assert response.status_code == 200
    payload = response.json()["settings"]
    assert payload["enabled"] is True
    assert payload["recipient_email"] == "triage@example.com"
    assert payload["morning_time"] == "07:45"
    assert payload["evening_time"] == "17:05"
    assert payload["digest_enabled"] is True
    assert payload["digest_time"] == "18:20"
    assert payload["ai_digest_summary_enabled"] is True


def test_notification_settings_endpoint_rejects_bad_timezone(api_client):
    response = api_client.patch(
        "/api/settings/notifications",
        json={"timezone": "bad/timezone"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "timezone must be a valid IANA timezone"
    assert response.json()["code"] == "notification_settings_validation_failed"


def test_notification_settings_endpoint_rejects_bad_digest_time(api_client):
    response = api_client.patch(
        "/api/settings/notifications",
        json={"digest_time": "24:00"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "digest_time must use a valid 24-hour time"
    assert response.json()["code"] == "notification_settings_validation_failed"


def test_notification_settings_endpoint_rejects_bad_recipient_email(api_client):
    response = api_client.patch(
        "/api/settings/notifications",
        json={"recipient_email": "not-an-email"},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "recipient_email must be a valid email address"
    assert response.json()["code"] == "notification_settings_validation_failed"
