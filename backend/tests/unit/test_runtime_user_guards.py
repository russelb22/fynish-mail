from __future__ import annotations

import pytest

from app.core import config
from app.services import runtime_user
from app.services.notification_settings import ensure_notification_settings
from app.services.review_queue import sync_unread_messages


def test_require_explicit_user_id_in_cloud_returns_explicit_user(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(runtime_user, "APP_ENV", "cloud")

    assert runtime_user.require_explicit_user_id_in_cloud(42, operation="demo") == 42


def test_require_explicit_user_id_in_cloud_rejects_missing_user(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(runtime_user, "APP_ENV", "cloud")

    with pytest.raises(RuntimeError, match="requires an explicit user_id"):
        runtime_user.require_explicit_user_id_in_cloud(None, operation="demo")


def test_require_explicit_user_id_in_local_allows_missing_user(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "local")
    monkeypatch.setattr(runtime_user, "APP_ENV", "local")

    assert runtime_user.require_explicit_user_id_in_cloud(None, operation="demo") is None


def test_notification_settings_requires_explicit_user_in_cloud(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(runtime_user, "APP_ENV", "cloud")

    with pytest.raises(RuntimeError, match="ensure_notification_settings requires an explicit user_id"):
        ensure_notification_settings()


def test_sync_unread_messages_requires_explicit_user_in_cloud(monkeypatch):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(runtime_user, "APP_ENV", "cloud")

    with pytest.raises(RuntimeError, match="sync_unread_messages requires an explicit user_id"):
        sync_unread_messages()


def test_sync_unread_messages_allows_global_scheduler_mode_in_cloud(
    isolated_db, monkeypatch
):
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(runtime_user, "APP_ENV", "cloud")

    result = sync_unread_messages(allow_global=True)

    assert set(result.keys()) == {
        "synced_messages",
        "reconciled_messages",
        "auto_applied_messages",
        "failed_accounts",
    }
