from __future__ import annotations

from datetime import datetime, timezone
import re
from typing import Any

from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.services.runtime_user import require_explicit_user_id_in_cloud


DOMAIN_RE = re.compile(r"^[a-z0-9][a-z0-9.-]*\.[a-z]{2,}$")
MAX_DOMAIN_LENGTH = 200
MAX_LABEL_LENGTH = 120
MAX_NOTE_LENGTH = 800

DEFAULT_DOMAIN_ATTENTION_NOTES = [
    {
        "domain": "example.net",
        "label": "Example Security",
        "note": (
            "Highlight only alarm/security conditions more severe than routine "
            "End-of-Bypass, Low Battery, status, or informational messages."
        ),
    },
    {
        "domain": "truecoach.co",
        "label": "TrueCoach",
        "note": (
            "Highlight likely personal coach/client communication. Treat routine "
            "workout assignment, missed-workout, and schedule reminder messages as routine."
        ),
    },
]


class AIDigestAttentionNoteValidationError(ValueError):
    pass


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalize_domain(value: object) -> str:
    domain = str(value or "").strip().lower()
    if domain.startswith("@"):
        domain = domain[1:]
    if not domain:
        raise AIDigestAttentionNoteValidationError("domain is required")
    if len(domain) > MAX_DOMAIN_LENGTH:
        raise AIDigestAttentionNoteValidationError(
            f"domain must be {MAX_DOMAIN_LENGTH} characters or fewer"
        )
    if "/" in domain or ":" in domain or not DOMAIN_RE.match(domain):
        raise AIDigestAttentionNoteValidationError(
            "domain must be a bare sender domain such as example.net"
        )
    return domain


def _clean_label(value: object, *, domain: str) -> str:
    label = str(value or "").strip()
    if not label:
        label = domain
    if len(label) > MAX_LABEL_LENGTH:
        raise AIDigestAttentionNoteValidationError(
            f"label must be {MAX_LABEL_LENGTH} characters or fewer"
        )
    return label


def _clean_note(value: object) -> str:
    note = str(value or "").strip()
    if not note:
        raise AIDigestAttentionNoteValidationError("note is required")
    if len(note) > MAX_NOTE_LENGTH:
        raise AIDigestAttentionNoteValidationError(
            f"note must be {MAX_NOTE_LENGTH} characters or fewer"
        )
    return note


def _serialize_row(row) -> dict[str, Any]:
    return {
        "id": int(row["id"]),
        "user_id": int(row["user_id"]),
        "domain": row["domain"],
        "label": row["label"],
        "note": row["note"],
        "enabled": bool(row["enabled"]),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def _insert_note(
    conn,
    *,
    user_id: int,
    domain: str,
    label: str,
    note: str,
    enabled: bool,
    now: str,
) -> int:
    return insert_and_return_id(
        conn,
        """
        INSERT INTO ai_digest_domain_attention_notes (
            user_id, domain, label, note, enabled, created_at, updated_at
        ) VALUES (
            :user_id, :domain, :label, :note, :enabled, :created_at, :updated_at
        )
        """,
        {
            "user_id": user_id,
            "domain": domain,
            "label": label,
            "note": note,
            "enabled": enabled,
            "created_at": now,
            "updated_at": now,
        },
    )


def _seed_defaults_if_empty(conn, *, user_id: int) -> None:
    existing = fetch_one(
        conn,
        "SELECT id FROM ai_digest_domain_attention_notes WHERE user_id = :user_id LIMIT 1",
        {"user_id": user_id},
    )
    if existing is not None:
        return

    now = _now_iso()
    for item in DEFAULT_DOMAIN_ATTENTION_NOTES:
        _insert_note(
            conn,
            user_id=user_id,
            domain=item["domain"],
            label=item["label"],
            note=item["note"],
            enabled=True,
            now=now,
        )


def list_ai_digest_attention_notes(user_id: int | None = None) -> list[dict[str, Any]]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="list_ai_digest_attention_notes",
    )
    with get_connection() as conn:
        _seed_defaults_if_empty(conn, user_id=int(user_id))
        rows = fetch_all(
            conn,
            """
            SELECT * FROM ai_digest_domain_attention_notes
            WHERE user_id = :user_id
            ORDER BY lower(domain)
            """,
            {"user_id": user_id},
        )
    return [_serialize_row(row) for row in rows]


def get_enabled_ai_digest_attention_notes(
    user_id: int | None = None,
) -> list[dict[str, Any]]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="get_enabled_ai_digest_attention_notes",
    )
    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT * FROM ai_digest_domain_attention_notes
            WHERE user_id = :user_id
            ORDER BY lower(domain)
            """,
            {"user_id": user_id},
        )
    if not rows:
        return [
            {"id": None, "user_id": user_id, "enabled": True, **item}
            for item in DEFAULT_DOMAIN_ATTENTION_NOTES
        ]
    return [_serialize_row(row) for row in rows if bool(row["enabled"])]


def create_ai_digest_attention_note(
    changes: dict[str, Any],
    *,
    user_id: int | None = None,
) -> dict[str, Any]:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="create_ai_digest_attention_note",
    )
    domain = normalize_domain(changes.get("domain"))
    label = _clean_label(changes.get("label"), domain=domain)
    note = _clean_note(changes.get("note"))
    enabled = bool(changes.get("enabled", True))
    now = _now_iso()

    with get_connection() as conn:
        existing = fetch_one(
            conn,
            """
            SELECT id FROM ai_digest_domain_attention_notes
            WHERE user_id = :user_id AND lower(domain) = :domain
            """,
            {"user_id": user_id, "domain": domain},
        )
        if existing is not None:
            raise AIDigestAttentionNoteValidationError(
                "attention note already exists for this domain"
            )
        note_id = _insert_note(
            conn,
            user_id=int(user_id),
            domain=domain,
            label=label,
            note=note,
            enabled=enabled,
            now=now,
        )
        row = fetch_one(
            conn,
            "SELECT * FROM ai_digest_domain_attention_notes WHERE id = :id AND user_id = :user_id",
            {"id": note_id, "user_id": user_id},
        )
    return _serialize_row(row)


def update_ai_digest_attention_note(
    note_id: int,
    changes: dict[str, Any],
    *,
    user_id: int | None = None,
) -> dict[str, Any] | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="update_ai_digest_attention_note",
    )
    updates: dict[str, Any] = {}

    if "domain" in changes:
        domain = normalize_domain(changes.get("domain"))
        updates["domain"] = domain
    if "label" in changes:
        updates["label"] = _clean_label(changes.get("label"), domain="domain")
    if "note" in changes:
        updates["note"] = _clean_note(changes.get("note"))
    if "enabled" in changes:
        updates["enabled"] = bool(changes["enabled"])

    with get_connection() as conn:
        current = fetch_one(
            conn,
            "SELECT * FROM ai_digest_domain_attention_notes WHERE id = :id AND user_id = :user_id",
            {"id": note_id, "user_id": user_id},
        )
        if current is None:
            return None

        if "label" in changes:
            updates["label"] = _clean_label(
                changes.get("label"),
                domain=str(updates.get("domain") or current["domain"]),
            )

        if "domain" in updates:
            duplicate = fetch_one(
                conn,
                """
                SELECT id FROM ai_digest_domain_attention_notes
                WHERE user_id = :user_id AND lower(domain) = :domain AND id != :id
                """,
                {"user_id": user_id, "domain": updates["domain"], "id": note_id},
            )
            if duplicate is not None:
                raise AIDigestAttentionNoteValidationError(
                    "attention note already exists for this domain"
                )

        if updates:
            updates["updated_at"] = _now_iso()
            assignments = ", ".join(f"{field} = :{field}" for field in updates)
            execute_sql(
                conn,
                f"""
                UPDATE ai_digest_domain_attention_notes
                SET {assignments}
                WHERE id = :id AND user_id = :user_id
                """,
                {**updates, "id": note_id, "user_id": user_id},
            )

        row = fetch_one(
            conn,
            "SELECT * FROM ai_digest_domain_attention_notes WHERE id = :id AND user_id = :user_id",
            {"id": note_id, "user_id": user_id},
        )
    return _serialize_row(row)


def delete_ai_digest_attention_note(
    note_id: int,
    *,
    user_id: int | None = None,
) -> bool:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="delete_ai_digest_attention_note",
    )
    with get_connection() as conn:
        existing = fetch_one(
            conn,
            "SELECT id FROM ai_digest_domain_attention_notes WHERE id = :id AND user_id = :user_id",
            {"id": note_id, "user_id": user_id},
        )
        if existing is None:
            return False
        execute_sql(
            conn,
            "DELETE FROM ai_digest_domain_attention_notes WHERE id = :id AND user_id = :user_id",
            {"id": note_id, "user_id": user_id},
        )
    return True
