from __future__ import annotations

from app.api import routes
from app.core import config
from app.db.runtime import fetch_one, get_connection


def test_local_mode_accounts_route_uses_default_user_context(api_client, isolated_db, monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "local")

    response = api_client.get("/api/accounts")

    assert response.status_code == 200
    payload = response.json()
    assert "accounts" in payload


def test_cloud_mode_accounts_route_requires_authenticated_user_header(
    api_client, isolated_db, monkeypatch
):
    monkeypatch.setattr(config, "APP_ENV", "cloud")

    response = api_client.get("/api/accounts")

    assert response.status_code == 401
    assert response.json() == {"detail": "Authenticated user context is required."}


def test_cloud_mode_accounts_route_creates_or_resolves_backend_user_from_header(
    api_client, isolated_db, monkeypatch
):
    monkeypatch.setattr(config, "APP_ENV", "cloud")

    response = api_client.get(
        "/api/accounts",
        headers={
            "X-Fynish-Authenticated-Email": "friend@example.com",
            "X-Fynish-Authenticated-Name": "Friend User",
            "X-Fynish-Authenticated-Sub": "google-oauth-subject-123",
        },
    )

    assert response.status_code == 200

    with get_connection() as conn:
        row = fetch_one(
            conn,
            "SELECT email, display_name, status FROM users WHERE email = :email",
            {"email": "friend@example.com"},
        )

    assert row is not None
    assert row["email"] == "friend@example.com"
    assert row["display_name"] == "Friend User"
    assert row["status"] == "active"


def test_scheduled_sync_route_remains_available_without_user_context_in_cloud_mode(
    api_client, isolated_db, monkeypatch
):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(routes.scheduled_sync_service, "run_once", lambda: {"status": "completed"})

    response = api_client.post("/api/tasks/sync-unread")

    assert response.status_code == 200
    assert response.json() == {"status": "completed"}
