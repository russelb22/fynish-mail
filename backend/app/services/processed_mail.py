from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta
from html import unescape

from app.db.runtime import fetch_all, get_connection
from app.services.classifier import extract_email
from app.services.provider_models import ProviderMessageRecord


INLINE_WHITESPACE_RE = re.compile(r"[ \t\f\v]+")
EXCESS_BLANK_LINES_RE = re.compile(r"\n{3,}")
ANGLE_WRAPPED_URL_RE = re.compile(r"<https?://[^>\s]+>", re.IGNORECASE)
URL_ONLY_LINE_RE = re.compile(r"^\s*(?:https?://|www\.)\S+\s*$", re.IGNORECASE)
PROCESSED_PREVIEW_LIMIT = 4000
AUTO_CLEAN_PRIORITY_WINDOW = timedelta(days=2)


def _normalize_preview(
    snippet: str | None,
    body_preview: str | None,
    limit: int = PROCESSED_PREVIEW_LIMIT,
) -> str:
    def normalize_text(value: str | None) -> str:
        text = unescape(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
        text = ANGLE_WRAPPED_URL_RE.sub("", text)
        lines = []
        for line in text.splitlines():
            normalized_line = INLINE_WHITESPACE_RE.sub(" ", line).strip()
            if URL_ONLY_LINE_RE.match(normalized_line):
                continue
            lines.append(normalized_line)
        text = "\n".join(lines)
        return EXCESS_BLANK_LINES_RE.sub("\n\n", text).strip()

    snippet_text = normalize_text(snippet)
    body_text = normalize_text(body_preview)

    if snippet_text and body_text and snippet_text not in body_text:
        preview = f"{snippet_text}\n\n{body_text}".strip()
    else:
        preview = body_text or snippet_text

    if not preview:
        return ""
    if len(preview) <= limit:
        return preview
    return preview[: limit - 1].rstrip() + "…"


def list_processed_messages(limit: int = 200, user_id: int | None = None) -> list[dict]:
    bounded_limit = max(1, min(limit, 500))
    auto_clean_priority_start = (
        datetime.now(UTC) - AUTO_CLEAN_PRIORITY_WINDOW
    ).isoformat()
    with get_connection() as conn:
        params: dict[str, object] = {
            "auto_clean_priority_start": auto_clean_priority_start,
            "limit": bounded_limit,
        }
        ownership_filter = ""
        if user_id is not None:
            ownership_filter = "AND owned_ma.user_id = :user_id"
            params["user_id"] = user_id
        rows = fetch_all(
            conn,
            f"""
            SELECT
                l.id,
                COALESCE(m.id, l.message_id) AS message_id,
                l.created_at AS processed_at,
                l.account_email,
                l.selected_action,
                l.recommended_action,
                l.user_overrode,
                l.action_source,
                l.created_rule_id,
                COALESCE(owned_ma.provider, a.provider, 'unknown') AS provider,
                m.mail_account_id,
                m.provider_message_id,
                m.provider_thread_id,
                m.provider_labels_json,
                m.sender,
                m.sender_domain,
                m.subject,
                m.snippet,
                m.body_preview,
                m.received_at
            FROM actions_log l
            LEFT JOIN messages m
              ON l.message_id = m.id
              OR (
                    l.message_id IS NULL
                AND l.gmail_message_id = m.gmail_message_id
                AND l.account_email = m.account_email
              )
            LEFT JOIN mail_accounts owned_ma
              ON owned_ma.id = m.mail_account_id
            LEFT JOIN accounts a
              ON a.email_address = l.account_email
             AND (owned_ma.id IS NULL OR a.provider = owned_ma.provider)
            WHERE l.selected_action != 'recover'
              {ownership_filter}
            ORDER BY
                CASE
                    WHEN COALESCE(l.action_source, 'manual') = 'high_confidence_auto_clean'
                     AND l.created_at >= :auto_clean_priority_start
                    THEN 0
                    ELSE 1
                END,
                l.created_at DESC,
                l.id DESC
            LIMIT :limit
            """,
            params,
        )

    payload = []
    for row in rows:
        message = ProviderMessageRecord.from_row(row)
        sender = message.sender or "Unknown sender"
        sender_email = extract_email(sender) if message.sender else ""
        subject = message.subject or "Unknown subject"
        payload.append(
            {
                "id": int(row["id"]),
                "message_id": int(row["message_id"]) if row["message_id"] is not None else None,
                "processed_at": row["processed_at"],
                "account_email": message.account_email,
                "sender": sender,
                "sender_email": sender_email,
                "sender_domain": message.sender_domain or "",
                "subject": subject,
                "preview": _normalize_preview(message.snippet, message.body_preview),
                "selected_action": row["selected_action"],
                "recommended_action": row["recommended_action"],
                "user_overrode": bool(row["user_overrode"]),
                "action_source": row["action_source"] or "manual",
                "created_rule_id": row["created_rule_id"],
                "received_at": message.received_at,
            }
        )
    return payload
