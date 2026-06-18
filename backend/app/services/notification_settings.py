from __future__ import annotations

from datetime import datetime, timezone
import re
from zoneinfo import ZoneInfo

from app.db.runtime import execute_sql, fetch_one, get_connection, insert_and_return_id
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.services.runtime_user import require_explicit_user_id_in_cloud


DEFAULT_NOTIFICATION_SETTINGS = {
    "enabled": False,
    "recipient_email": None,
    "timezone": "America/Los_Angeles",
    "morning_enabled": True,
    "morning_time": "08:00",
    "evening_enabled": True,
    "evening_time": "16:00",
    "send_only_if_queue_nonempty": True,
    "digest_enabled": False,
    "digest_time": "17:00",
    "ai_digest_summary_enabled": False,
}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class NotificationSettingsValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _serialize_row(row) -> dict:
    return {
        "enabled": bool(row["enabled"]),
        "recipient_email": row["recipient_email"],
        "timezone": row["timezone"],
        "morning_enabled": bool(row["morning_enabled"]),
        "morning_time": row["morning_time"],
        "evening_enabled": bool(row["evening_enabled"]),
        "evening_time": row["evening_time"],
        "send_only_if_queue_nonempty": bool(row["send_only_if_queue_nonempty"]),
        "digest_enabled": bool(row["digest_enabled"]),
        "digest_time": row["digest_time"],
        "ai_digest_summary_enabled": bool(row["ai_digest_summary_enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _validate_time(value: str, field_name: str) -> str:
    parts = value.split(":")
    if len(parts) != 2:
        raise NotificationSettingsValidationError(f"{field_name} must use HH:MM format")

    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise NotificationSettingsValidationError(f"{field_name} must use HH:MM format") from exc

    if hour < 0 or hour > 23 or minute < 0 or minute > 59:
        raise NotificationSettingsValidationError(
            f"{field_name} must use a valid 24-hour time"
        )

    return f"{hour:02d}:{minute:02d}"


def _validate_timezone(value: str) -> str:
    try:
        ZoneInfo(value)
    except Exception as exc:  # pragma: no cover - ZoneInfo raises varying error types by platform
        raise NotificationSettingsValidationError(
            "timezone must be a valid IANA timezone"
        ) from exc
    return value


def _validate_recipient_email(value: str) -> str:
    normalized = value.strip().lower()
    if not EMAIL_RE.match(normalized):
        raise NotificationSettingsValidationError(
            "recipient_email must be a valid email address"
        )
    return normalized


def _ensure_default_user(conn, now: str) -> int:
    row = fetch_one(
        conn,
        "SELECT id FROM users WHERE email = :email",
        {"email": DEFAULT_LOCAL_OWNER_EMAIL},
    )
    if row is not None:
        return int(row["id"])
    return insert_and_return_id(
        conn,
        """
        INSERT INTO users (email, display_name, status, created_at, updated_at)
        VALUES (:email, :display_name, 'active', :created_at, :updated_at)
        """,
        {
            "email": DEFAULT_LOCAL_OWNER_EMAIL,
            "display_name": DEFAULT_LOCAL_OWNER_NAME,
            "created_at": now,
            "updated_at": now,
        },
    )


def _load_legacy_seed_row(conn):
    return fetch_one(conn, "SELECT * FROM notification_settings WHERE id = 1")


def _ensure_notification_settings_for_user(conn, user_id: int, now: str):
    row = fetch_one(
        conn,
        "SELECT * FROM notification_settings_by_user WHERE user_id = :user_id",
        {"user_id": user_id},
    )
    if row is not None:
        return row

    legacy_row = _load_legacy_seed_row(conn)
    if legacy_row is None:
        source = {
            "enabled": int(DEFAULT_NOTIFICATION_SETTINGS["enabled"]),
            "recipient_email": DEFAULT_NOTIFICATION_SETTINGS["recipient_email"],
            "timezone": DEFAULT_NOTIFICATION_SETTINGS["timezone"],
            "morning_enabled": int(DEFAULT_NOTIFICATION_SETTINGS["morning_enabled"]),
            "morning_time": DEFAULT_NOTIFICATION_SETTINGS["morning_time"],
            "evening_enabled": int(DEFAULT_NOTIFICATION_SETTINGS["evening_enabled"]),
            "evening_time": DEFAULT_NOTIFICATION_SETTINGS["evening_time"],
            "send_only_if_queue_nonempty": int(
                DEFAULT_NOTIFICATION_SETTINGS["send_only_if_queue_nonempty"]
            ),
            "digest_enabled": int(DEFAULT_NOTIFICATION_SETTINGS["digest_enabled"]),
            "digest_time": DEFAULT_NOTIFICATION_SETTINGS["digest_time"],
            "ai_digest_summary_enabled": int(
                DEFAULT_NOTIFICATION_SETTINGS["ai_digest_summary_enabled"]
            ),
            "created_at": now,
            "updated_at": now,
        }
    else:
        source = dict(legacy_row)

    execute_sql(
        conn,
        """
        INSERT INTO notification_settings_by_user (
            user_id,
            enabled,
            recipient_email,
            timezone,
            morning_enabled,
            morning_time,
            evening_enabled,
            evening_time,
            send_only_if_queue_nonempty,
            digest_enabled,
            digest_time,
            ai_digest_summary_enabled,
            created_at,
            updated_at
        ) VALUES (
            :user_id,
            :enabled,
            :recipient_email,
            :timezone,
            :morning_enabled,
            :morning_time,
            :evening_enabled,
            :evening_time,
            :send_only_if_queue_nonempty,
            :digest_enabled,
            :digest_time,
            :ai_digest_summary_enabled,
            :created_at,
            :updated_at
        )
        """,
        {
            "user_id": user_id,
            "enabled": source["enabled"],
            "recipient_email": source["recipient_email"],
            "timezone": source["timezone"],
            "morning_enabled": source["morning_enabled"],
            "morning_time": source["morning_time"],
            "evening_enabled": source["evening_enabled"],
            "evening_time": source["evening_time"],
            "send_only_if_queue_nonempty": source["send_only_if_queue_nonempty"],
            "digest_enabled": source.get(
                "digest_enabled", int(DEFAULT_NOTIFICATION_SETTINGS["digest_enabled"])
            ),
            "digest_time": source.get(
                "digest_time", DEFAULT_NOTIFICATION_SETTINGS["digest_time"]
            ),
            "ai_digest_summary_enabled": source.get(
                "ai_digest_summary_enabled",
                int(DEFAULT_NOTIFICATION_SETTINGS["ai_digest_summary_enabled"]),
            ),
            "created_at": source["created_at"],
            "updated_at": source["updated_at"],
        },
    )
    return fetch_one(
        conn,
        "SELECT * FROM notification_settings_by_user WHERE user_id = :user_id",
        {"user_id": user_id},
    )


def ensure_notification_settings(user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="ensure_notification_settings",
    )
    now = _now_iso()
    with get_connection() as conn:
        effective_user_id = user_id if user_id is not None else _ensure_default_user(conn, now)
        row = _ensure_notification_settings_for_user(conn, effective_user_id, now)
    return _serialize_row(row)


def get_notification_settings(user_id: int | None = None) -> dict:
    return ensure_notification_settings(user_id=user_id)


def update_notification_settings(changes: dict, user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="update_notification_settings",
    )
    updates: dict[str, object] = {}

    if "enabled" in changes:
        updates["enabled"] = int(bool(changes["enabled"]))

    if "recipient_email" in changes:
        recipient_email = changes["recipient_email"]
        updates["recipient_email"] = (
            _validate_recipient_email(recipient_email)
            if isinstance(recipient_email, str) and recipient_email.strip()
            else None
        )

    if "timezone" in changes:
        updates["timezone"] = _validate_timezone(str(changes["timezone"]).strip())

    if "morning_enabled" in changes:
        updates["morning_enabled"] = int(bool(changes["morning_enabled"]))

    if "morning_time" in changes:
        updates["morning_time"] = _validate_time(
            str(changes["morning_time"]).strip(),
            "morning_time",
        )

    if "evening_enabled" in changes:
        updates["evening_enabled"] = int(bool(changes["evening_enabled"]))

    if "evening_time" in changes:
        updates["evening_time"] = _validate_time(
            str(changes["evening_time"]).strip(),
            "evening_time",
        )

    if "send_only_if_queue_nonempty" in changes:
        updates["send_only_if_queue_nonempty"] = int(
            bool(changes["send_only_if_queue_nonempty"])
        )

    if "digest_enabled" in changes:
        updates["digest_enabled"] = int(bool(changes["digest_enabled"]))

    if "digest_time" in changes:
        updates["digest_time"] = _validate_time(
            str(changes["digest_time"]).strip(),
            "digest_time",
        )

    if "ai_digest_summary_enabled" in changes:
        updates["ai_digest_summary_enabled"] = int(
            bool(changes["ai_digest_summary_enabled"])
        )

    now = _now_iso()
    with get_connection() as conn:
        effective_user_id = user_id if user_id is not None else _ensure_default_user(conn, now)
        _ensure_notification_settings_for_user(conn, effective_user_id, now)

        if not updates:
            row = fetch_one(
                conn,
                "SELECT * FROM notification_settings_by_user WHERE user_id = :user_id",
                {"user_id": effective_user_id},
            )
            return _serialize_row(row)

        updates["updated_at"] = now
        assignments = ", ".join(f"{field} = :{field}" for field in updates)
        execute_sql(
            conn,
            f"UPDATE notification_settings_by_user SET {assignments} WHERE user_id = :user_id",
            {**updates, "user_id": effective_user_id},
        )
        row = fetch_one(
            conn,
            "SELECT * FROM notification_settings_by_user WHERE user_id = :user_id",
            {"user_id": effective_user_id},
        )
    return _serialize_row(row)
