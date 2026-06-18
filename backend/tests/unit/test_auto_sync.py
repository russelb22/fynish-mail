from __future__ import annotations

import threading

from app.services.auto_sync import AutoSyncService, ScheduledSyncService


def test_run_once_returns_sync_result(monkeypatch):
    monkeypatch.setattr(
        "app.services.auto_sync._run_user_scoped_syncs",
        lambda: {
            "synced_messages": 3,
            "reconciled_messages": 1,
            "auto_applied_messages": 0,
            "failed_accounts": [],
            "users_processed": 1,
            "user_summaries": [],
        },
    )

    service = AutoSyncService(enabled=True, interval_seconds=300)
    result = service.run_once()

    assert result == {
        "synced_messages": 3,
        "reconciled_messages": 1,
        "auto_applied_messages": 0,
        "failed_accounts": [],
        "users_processed": 1,
        "user_summaries": [],
    }


def test_start_runs_periodic_sync_until_stopped(monkeypatch):
    called = threading.Event()

    def fake_sync(**_):
        called.set()
        return {
            "synced_messages": 1,
            "reconciled_messages": 0,
            "auto_applied_messages": 0,
            "failed_accounts": [],
            "users_processed": 1,
            "user_summaries": [],
        }

    monkeypatch.setattr("app.services.auto_sync._run_user_scoped_syncs", fake_sync)

    service = AutoSyncService(enabled=True, interval_seconds=1)
    service.start()
    assert called.wait(1.5) is True
    service.stop()
    assert service._thread is None


def test_scheduled_sync_returns_disabled_when_feature_is_off():
    service = ScheduledSyncService(enabled=False)

    result = service.run_once()

    assert result["status"] == "disabled"
    assert result["synced_messages"] == 0
    assert "disabled" in result["reason"]


def test_scheduled_sync_returns_sync_result_when_enabled(monkeypatch):
    monkeypatch.setattr(
        "app.services.auto_sync._run_user_scoped_syncs",
        lambda: {
            "synced_messages": 7,
            "reconciled_messages": 2,
            "auto_applied_messages": 3,
            "failed_accounts": [{"account_email": "beta.user@example.com", "provider": "gmail_readonly", "reason": "Reconnect required"}],
            "users_processed": 2,
            "user_summaries": [
                {"user_id": 1, "synced_messages": 4, "reconciled_messages": 1, "auto_applied_messages": 2, "failed_accounts": []},
                {"user_id": 2, "synced_messages": 3, "reconciled_messages": 1, "auto_applied_messages": 1, "failed_accounts": [{"account_email": "beta.user@example.com", "provider": "gmail_readonly", "reason": "Reconnect required"}]},
            ],
        },
    )

    service = ScheduledSyncService(enabled=True)
    result = service.run_once()

    assert result == {
        "status": "completed",
        "synced_messages": 7,
        "reconciled_messages": 2,
        "auto_applied_messages": 3,
        "failed_accounts": [{"account_email": "beta.user@example.com", "provider": "gmail_readonly", "reason": "Reconnect required"}],
        "users_processed": 2,
        "user_summaries": [
            {"user_id": 1, "synced_messages": 4, "reconciled_messages": 1, "auto_applied_messages": 2, "failed_accounts": []},
            {"user_id": 2, "synced_messages": 3, "reconciled_messages": 1, "auto_applied_messages": 1, "failed_accounts": [{"account_email": "beta.user@example.com", "provider": "gmail_readonly", "reason": "Reconnect required"}]},
        ],
        "ran_at": result["ran_at"],
    }


def test_scheduled_sync_skips_when_another_run_is_active():
    service = ScheduledSyncService(enabled=True)
    assert service._run_lock.acquire(blocking=False) is True
    try:
        result = service.run_once()
    finally:
        service._run_lock.release()

    assert result["status"] == "skipped"
    assert result["synced_messages"] == 0
    assert "already running" in result["reason"]


def test_run_user_scoped_syncs_aggregates_by_user(monkeypatch):
    monkeypatch.setattr("app.services.auto_sync._scheduled_sync_user_ids", lambda: [11, 22])

    def fake_sync_unread_messages(*, user_id=None, **_):
        if user_id == 11:
            return {"synced_messages": 2, "reconciled_messages": 1, "auto_applied_messages": 0, "failed_accounts": []}
        if user_id == 22:
            return {
                "synced_messages": 5,
                "reconciled_messages": 0,
                "auto_applied_messages": 2,
                "failed_accounts": [
                    {
                        "account_email": "beta.user@example.com",
                        "provider": "gmail_readonly",
                        "reason": "Reconnect required",
                    }
                ],
            }
        raise AssertionError(f"Unexpected user_id {user_id}")

    monkeypatch.setattr("app.services.auto_sync.sync_unread_messages", fake_sync_unread_messages)

    from app.services.auto_sync import _run_user_scoped_syncs

    result = _run_user_scoped_syncs()

    assert result == {
        "synced_messages": 7,
        "reconciled_messages": 1,
        "auto_applied_messages": 2,
        "failed_accounts": [
            {
                "account_email": "beta.user@example.com",
                "provider": "gmail_readonly",
                "reason": "Reconnect required",
            }
        ],
        "users_processed": 2,
        "user_summaries": [
            {"user_id": 11, "synced_messages": 2, "reconciled_messages": 1, "auto_applied_messages": 0, "failed_accounts": []},
            {
                "user_id": 22,
                "synced_messages": 5,
                "reconciled_messages": 0,
                "auto_applied_messages": 2,
                "failed_accounts": [
                    {
                        "account_email": "beta.user@example.com",
                        "provider": "gmail_readonly",
                        "reason": "Reconnect required",
                    }
                ],
            },
        ],
    }


def test_run_user_scoped_syncs_falls_back_to_global_in_local_when_no_users(monkeypatch):
    monkeypatch.setattr("app.services.auto_sync._scheduled_sync_user_ids", lambda: [])
    monkeypatch.setattr("app.services.auto_sync.APP_ENV", "local")
    monkeypatch.setattr(
        "app.services.auto_sync.sync_unread_messages",
        lambda **kwargs: {
            "synced_messages": 4,
            "reconciled_messages": 0,
            "auto_applied_messages": 1,
            "failed_accounts": [],
        }
        if kwargs == {"allow_global": True}
        else (_ for _ in ()).throw(AssertionError(f"Unexpected kwargs {kwargs}")),
    )

    from app.services.auto_sync import _run_user_scoped_syncs

    result = _run_user_scoped_syncs()

    assert result == {
        "synced_messages": 4,
        "reconciled_messages": 0,
        "auto_applied_messages": 1,
        "failed_accounts": [],
    }
