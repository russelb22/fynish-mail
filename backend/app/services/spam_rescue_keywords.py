from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.services.classifier import DEFAULT_PROTECTED_KEYWORDS
from app.services.runtime_user import require_explicit_user_id_in_cloud


KEYWORD_RE = re.compile(r"^[a-z0-9][a-z0-9 &/.'-]*[a-z0-9]$")
MAX_KEYWORD_LENGTH = 80


class SpamRescueKeywordValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_keyword(value: object) -> str:
    keyword = " ".join(str(value or "").strip().lower().split())
    if not keyword:
        raise SpamRescueKeywordValidationError("keyword is required")
    if len(keyword) > MAX_KEYWORD_LENGTH:
        raise SpamRescueKeywordValidationError(
            f"keyword must be {MAX_KEYWORD_LENGTH} characters or fewer"
        )
    if not KEYWORD_RE.match(keyword):
        raise SpamRescueKeywordValidationError(
            "keyword may contain letters, numbers, spaces, &, /, apostrophes, periods, and hyphens"
        )
    return keyword


def _serialize_row(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "keyword": row["keyword"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _insert_keyword(
    conn,
    *,
    user_id: int,
    keyword: str,
    enabled: bool,
    now: str,
) -> int:
    return insert_and_return_id(
        conn,
        """
        INSERT INTO spam_rescue_protected_keywords (
            user_id, keyword, enabled, created_at, updated_at
        ) VALUES (
            :user_id, :keyword, :enabled, :created_at, :updated_at
        )
        """,
        {
            "user_id": user_id,
            "keyword": keyword,
            "enabled": enabled,
            "created_at": now,
            "updated_at": now,
        },
    )


def _seed_defaults_if_empty(conn, *, user_id: int) -> None:
    existing = fetch_one(
        conn,
        "SELECT id FROM spam_rescue_protected_keywords WHERE user_id = :user_id LIMIT 1",
        {"user_id": user_id},
    )
    if existing is not None:
        return

    now = _now_iso()
    for keyword in sorted(DEFAULT_PROTECTED_KEYWORDS):
        _insert_keyword(
            conn,
            user_id=user_id,
            keyword=keyword,
            enabled=True,
            now=now,
        )


def list_spam_rescue_protected_keywords(user_id: int | None = None) -> list[dict[str, Any]]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="list_spam_rescue_protected_keywords",
    )
    with get_connection() as conn:
        if user_id is not None:
            _seed_defaults_if_empty(conn, user_id=int(user_id))
            rows = fetch_all(
                conn,
                """
                SELECT * FROM spam_rescue_protected_keywords
                WHERE user_id = :user_id
                ORDER BY lower(keyword)
                """,
                {"user_id": user_id},
            )
        else:
            rows = fetch_all(
                conn,
                """
                SELECT * FROM spam_rescue_protected_keywords
                ORDER BY lower(keyword)
                """,
            )
    if user_id is None and not rows:
        now = _now_iso()
        return [
            {
                "id": index + 1,
                "user_id": 0,
                "keyword": keyword,
                "enabled": True,
                "created_at": now,
                "updated_at": now,
            }
            for index, keyword in enumerate(sorted(DEFAULT_PROTECTED_KEYWORDS))
        ]
    return [_serialize_row(row) for row in rows]


def get_enabled_spam_rescue_protected_keywords(user_id: int | None = None) -> set[str]:
    rows = list_spam_rescue_protected_keywords(user_id=user_id)
    return {row["keyword"] for row in rows if row["enabled"]}


def create_spam_rescue_protected_keyword(
    changes: dict[str, Any],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="create_spam_rescue_protected_keyword",
    )
    if user_id is None:
        raise SpamRescueKeywordValidationError("user is required")
    keyword = normalize_keyword(changes.get("keyword"))
    enabled = bool(changes.get("enabled", True))
    now = _now_iso()

    with get_connection() as conn:
        _seed_defaults_if_empty(conn, user_id=int(user_id))
        existing = fetch_one(
            conn,
            """
            SELECT id FROM spam_rescue_protected_keywords
            WHERE user_id = :user_id AND lower(keyword) = :keyword
            """,
            {"user_id": user_id, "keyword": keyword},
        )
        if existing is not None:
            raise SpamRescueKeywordValidationError("protected keyword already exists")
        keyword_id = _insert_keyword(
            conn,
            user_id=int(user_id),
            keyword=keyword,
            enabled=enabled,
            now=now,
        )
        row = fetch_one(
            conn,
            "SELECT * FROM spam_rescue_protected_keywords WHERE id = :id AND user_id = :user_id",
            {"id": keyword_id, "user_id": user_id},
        )
    return _serialize_row(row)


def update_spam_rescue_protected_keyword(
    keyword_id: int,
    changes: dict[str, Any],
    *,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="update_spam_rescue_protected_keyword",
    )
    updates: dict[str, Any] = {}
    if "keyword" in changes:
        updates["keyword"] = normalize_keyword(changes.get("keyword"))
    if "enabled" in changes:
        updates["enabled"] = bool(changes["enabled"])

    with get_connection() as conn:
        current = fetch_one(
            conn,
            "SELECT * FROM spam_rescue_protected_keywords WHERE id = :id AND user_id = :user_id",
            {"id": keyword_id, "user_id": user_id},
        )
        if current is None:
            return None

        if "keyword" in updates:
            duplicate = fetch_one(
                conn,
                """
                SELECT id FROM spam_rescue_protected_keywords
                WHERE user_id = :user_id AND lower(keyword) = :keyword AND id != :id
                """,
                {"user_id": user_id, "keyword": updates["keyword"], "id": keyword_id},
            )
            if duplicate is not None:
                raise SpamRescueKeywordValidationError("protected keyword already exists")

        if updates:
            updates["updated_at"] = _now_iso()
            assignments = ", ".join(f"{field} = :{field}" for field in updates)
            execute_sql(
                conn,
                f"""
                UPDATE spam_rescue_protected_keywords
                SET {assignments}
                WHERE id = :id AND user_id = :user_id
                """,
                {**updates, "id": keyword_id, "user_id": user_id},
            )

        row = fetch_one(
            conn,
            "SELECT * FROM spam_rescue_protected_keywords WHERE id = :id AND user_id = :user_id",
            {"id": keyword_id, "user_id": user_id},
        )
    return _serialize_row(row)


def delete_spam_rescue_protected_keyword(
    keyword_id: int,
    *,
    user_id: int | None = None,
) -> bool:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="delete_spam_rescue_protected_keyword",
    )
    with get_connection() as conn:
        existing = fetch_one(
            conn,
            "SELECT id FROM spam_rescue_protected_keywords WHERE id = :id AND user_id = :user_id",
            {"id": keyword_id, "user_id": user_id},
        )
        if existing is None:
            return False
        execute_sql(
            conn,
            "DELETE FROM spam_rescue_protected_keywords WHERE id = :id AND user_id = :user_id",
            {"id": keyword_id, "user_id": user_id},
        )
    return True
