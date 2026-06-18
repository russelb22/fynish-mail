from __future__ import annotations

from app.api import routes


def test_scheduled_digest_route_returns_service_result(api_client, isolated_db, monkeypatch):
    monkeypatch.setattr(
        routes.scheduled_digest_service,
        "run_once",
        lambda: {
            "status": "completed",
            "users_considered": 1,
            "users_due": 1,
            "sent": 1,
            "skipped": 0,
            "failed": 0,
            "user_summaries": [],
            "ran_at": "2026-05-18T14:00:00+00:00",
        },
    )

    response = api_client.post("/api/tasks/send-digests")

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["sent"] == 1


def test_scheduled_digest_route_returns_disabled_service_result(
    api_client,
    isolated_db,
    monkeypatch,
):
    monkeypatch.setattr(
        routes.scheduled_digest_service,
        "run_once",
        lambda: {
            "status": "disabled",
            "reason": "Hosted scheduled digests are disabled",
            "users_considered": 0,
            "users_due": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "user_summaries": [],
            "ran_at": "2026-05-18T14:00:00+00:00",
        },
    )

    response = api_client.post("/api/tasks/send-digests")

    assert response.status_code == 200
    assert response.json()["status"] == "disabled"
    assert response.json()["failed"] == 0


def test_scheduled_digest_route_returns_already_running_service_result(
    api_client,
    isolated_db,
    monkeypatch,
):
    monkeypatch.setattr(
        routes.scheduled_digest_service,
        "run_once",
        lambda: {
            "status": "skipped",
            "reason": "Scheduled digests are already running",
            "users_considered": 0,
            "users_due": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "user_summaries": [],
            "ran_at": "2026-05-18T14:00:00+00:00",
        },
    )

    response = api_client.post("/api/tasks/send-digests")

    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "Scheduled digests are already running"


def test_scheduled_digest_route_returns_structured_failure_on_unexpected_error(
    api_client,
    isolated_db,
    monkeypatch,
):
    def fail_run_once():
        raise RuntimeError("database connection pool exploded")

    monkeypatch.setattr(routes.scheduled_digest_service, "run_once", fail_run_once)

    response = api_client.post("/api/tasks/send-digests")

    assert response.status_code == 200
    assert response.json() == {
        "status": "failed",
        "reason": "Scheduled digest delivery failed.",
        "users_considered": 0,
        "users_due": 0,
        "sent": 0,
        "skipped": 0,
        "failed": 1,
        "user_summaries": [],
    }
