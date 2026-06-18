from __future__ import annotations

import logging
import threading
from datetime import datetime, timezone

from app.core.config import (
    APP_ENV,
    AUTO_SYNC_ENABLED,
    AUTO_SYNC_INTERVAL_SECONDS,
    SCHEDULED_SYNC_ENABLED,
)
from app.db.runtime import fetch_all, get_connection
from app.services.review_queue import sync_unread_messages


logger = logging.getLogger(__name__)


def _utc_now_isoformat() -> str:
    return datetime.now(timezone.utc).isoformat()


def _scheduled_sync_user_ids() -> list[int]:
    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT DISTINCT ma.user_id
            FROM mail_accounts ma
            JOIN users u ON u.id = ma.user_id
            WHERE ma.enabled = 1
              AND u.status = 'active'
            ORDER BY ma.user_id ASC
            """,
        )
    return [int(row["user_id"]) for row in rows if row["user_id"] is not None]


def _run_user_scoped_syncs() -> dict:
    user_ids = _scheduled_sync_user_ids()
    if not user_ids:
        if APP_ENV != "cloud":
            return sync_unread_messages(allow_global=True)
        return {
            "synced_messages": 0,
            "reconciled_messages": 0,
            "auto_applied_messages": 0,
            "users_processed": 0,
            "user_summaries": [],
        }

    synced_messages = 0
    reconciled_messages = 0
    auto_applied_messages = 0
    failed_accounts: list[dict] = []
    user_summaries: list[dict] = []

    for user_id in user_ids:
        result = sync_unread_messages(user_id=user_id)
        synced_messages += result.get("synced_messages", 0)
        reconciled_messages += result.get("reconciled_messages", 0)
        auto_applied_messages += result.get("auto_applied_messages", 0)
        user_failed_accounts = list(result.get("failed_accounts", []))
        failed_accounts.extend(user_failed_accounts)
        user_summaries.append(
            {
                "user_id": user_id,
                "synced_messages": result.get("synced_messages", 0),
                "reconciled_messages": result.get("reconciled_messages", 0),
                "auto_applied_messages": result.get("auto_applied_messages", 0),
                "failed_accounts": user_failed_accounts,
            }
        )

    return {
        "synced_messages": synced_messages,
        "reconciled_messages": reconciled_messages,
        "auto_applied_messages": auto_applied_messages,
        "failed_accounts": failed_accounts,
        "users_processed": len(user_ids),
        "user_summaries": user_summaries,
    }


class AutoSyncService:
    def __init__(self, *, enabled: bool, interval_seconds: int) -> None:
        self.enabled = enabled
        self.interval_seconds = max(1, interval_seconds)
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if not self.enabled:
            logger.info("Auto-sync disabled")
            return
        if self._thread is not None and self._thread.is_alive():
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_loop,
            name="fynish-auto-sync",
            daemon=True,
        )
        self._thread.start()
        logger.info("Auto-sync started with %s second interval", self.interval_seconds)

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=5)
        self._thread = None

    def run_once(self) -> dict | None:
        try:
            result = _run_user_scoped_syncs()
            logger.info(
                "Auto-sync complete: users=%s synced=%s reconciled=%s auto_applied=%s",
                result.get("users_processed", 0),
                result.get("synced_messages", 0),
                result.get("reconciled_messages", 0),
                result.get("auto_applied_messages", 0),
            )
            return result
        except Exception:
            logger.exception("Auto-sync failed")
            return None

    def _run_loop(self) -> None:
        while not self._stop_event.wait(self.interval_seconds):
            self.run_once()


class ScheduledSyncService:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._run_lock = threading.Lock()

    def run_once(self) -> dict:
        ran_at = _utc_now_isoformat()
        if not self.enabled:
            logger.info("Scheduled sync skipped: disabled")
            return {
                "status": "disabled",
                "reason": "Hosted scheduled sync is disabled",
                "synced_messages": 0,
                "reconciled_messages": 0,
                "auto_applied_messages": 0,
                "failed_accounts": [],
                "ran_at": ran_at,
            }

        if not self._run_lock.acquire(blocking=False):
            logger.info("Scheduled sync skipped: already running")
            return {
                "status": "skipped",
                "reason": "Scheduled sync is already running",
                "synced_messages": 0,
                "reconciled_messages": 0,
                "auto_applied_messages": 0,
                "failed_accounts": [],
                "ran_at": ran_at,
            }

        try:
            result = _run_user_scoped_syncs()
            logger.info(
                "Scheduled sync complete: users=%s synced=%s reconciled=%s auto_applied=%s",
                result.get("users_processed", 0),
                result.get("synced_messages", 0),
                result.get("reconciled_messages", 0),
                result.get("auto_applied_messages", 0),
            )
            return {
                "status": "completed",
                "synced_messages": result.get("synced_messages", 0),
                "reconciled_messages": result.get("reconciled_messages", 0),
                "auto_applied_messages": result.get("auto_applied_messages", 0),
                "failed_accounts": result.get("failed_accounts", []),
                "users_processed": result.get("users_processed", 0),
                "user_summaries": result.get("user_summaries", []),
                "ran_at": ran_at,
            }
        except Exception:
            logger.exception("Scheduled sync failed")
            raise
        finally:
            self._run_lock.release()


auto_sync_service = AutoSyncService(
    enabled=AUTO_SYNC_ENABLED,
    interval_seconds=AUTO_SYNC_INTERVAL_SECONDS,
)

scheduled_sync_service = ScheduledSyncService(enabled=SCHEDULED_SYNC_ENABLED)
