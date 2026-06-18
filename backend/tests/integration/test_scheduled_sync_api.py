from __future__ import annotations

from app.api import routes
from app.services.gmail_readonly import GmailReadonlySyncError


def test_scheduled_sync_endpoint_returns_runner_summary(api_client, monkeypatch, isolated_db):
    monkeypatch.setattr(
        routes.scheduled_sync_service,
        "run_once",
        lambda: {
            "status": "completed",
            "synced_messages": 5,
            "reconciled_messages": 1,
            "auto_applied_messages": 2,
            "ran_at": "2026-05-13T19:00:00+00:00",
        },
    )

    response = api_client.post("/api/tasks/sync-unread")

    assert response.status_code == 200
    assert response.json() == {
        "status": "completed",
        "synced_messages": 5,
        "reconciled_messages": 1,
        "auto_applied_messages": 2,
        "ran_at": "2026-05-13T19:00:00+00:00",
    }


def test_scheduled_sync_endpoint_maps_sync_errors_to_bad_request(
    api_client, monkeypatch, isolated_db
):
    def raise_sync_error():
        raise GmailReadonlySyncError("token invalid")

    monkeypatch.setattr(routes.scheduled_sync_service, "run_once", raise_sync_error)

    response = api_client.post("/api/tasks/sync-unread")

    assert response.status_code == 400
    assert response.json() == {
        "code": "gmail_reconnect_required",
        "detail": "token invalid",
    }
