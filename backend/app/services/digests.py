from __future__ import annotations

from collections import Counter
from collections import defaultdict
from datetime import datetime, timezone
from html import escape
import logging
import re
import threading
from zoneinfo import ZoneInfo

from app.core.config import FRONTEND_URL, SCHEDULED_DIGESTS_ENABLED
from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.services.ai_digest_summary import build_ai_digest_summary
from app.services.digest_sender import validate_gmail_digest_sender
from app.services.mailer import MailDeliveryError, MailerNotConfiguredError, send_email
from app.services.notification_settings import get_notification_settings
from app.services.runtime_user import require_explicit_user_id_in_cloud

logger = logging.getLogger(__name__)

DIGEST_ACTION_ORDER = [
    "keep",
    "bulk_mail",
    "junk_review",
    "trash",
    "needs_review",
]

DIGEST_ACTION_LABELS = {
    "keep": "Keep",
    "bulk_mail": "Bulk",
    "junk_review": "Junk",
    "trash": "Trash",
    "needs_review": "Review",
}
DIGEST_ACTION_COLORS = {
    "keep": ("#e8f5ee", "#136c43"),
    "bulk_mail": ("#eef2ff", "#3844a3"),
    "junk_review": ("#fff4e5", "#9a4d00"),
    "trash": ("#fdecec", "#a82020"),
    "needs_review": ("#f3f4f6", "#4b5563"),
}
DIGEST_ACTION_SOURCE_LABELS = {
    "manual": "Manual",
    "rule_auto_apply": "Rule auto",
    "high_confidence_auto_clean": "Auto-clean",
    "recovery": "Recovery",
    "legacy_unknown": "Legacy",
}
DIGEST_ACTION_SOURCE_COLORS = {
    "manual": ("#f3f4f6", "#374151"),
    "rule_auto_apply": ("#e0f2fe", "#075985"),
    "high_confidence_auto_clean": ("#fef3c7", "#92400e"),
    "recovery": ("#ecfdf5", "#047857"),
    "legacy_unknown": ("#f3f4f6", "#6b7280"),
}

PROCESSED_DIGEST_LIMIT = 50
DIGEST_DOMAIN_SUMMARY_LIMIT = 10
DIGEST_DOMAIN_SAMPLE_LIMIT = 3
DIGEST_PREVIEW_LIMIT = 500
WHITESPACE_RE = re.compile(r"\s+")


class DigestUserNotFoundError(ValueError):
    pass


def _ensure_utc(value: datetime | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _format_digest_timestamp(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat()


def _format_display_window(
    start_utc: datetime,
    end_utc: datetime,
    timezone_name: str,
) -> str:
    zone = ZoneInfo(timezone_name)
    start_local = start_utc.astimezone(zone)
    end_local = end_utc.astimezone(zone)
    return (
        f"{start_local.strftime('%b %d, %Y %I:%M %p %Z')} to "
        f"{end_local.strftime('%b %d, %Y %I:%M %p %Z')}"
    )


def _format_message_time(value: str | None, timezone_name: str) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return str(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    zone = ZoneInfo(timezone_name)
    return parsed.astimezone(zone).strftime("%b %-d, %-I:%M %p")


def _source_label(source: str | None) -> str:
    source_key = source or "legacy_unknown"
    return DIGEST_ACTION_SOURCE_LABELS.get(
        source_key,
        source_key.replace("_", " ").title(),
    )


def _normalize_preview(
    snippet: str | None,
    body_preview: str | None,
    limit: int = DIGEST_PREVIEW_LIMIT,
) -> str:
    snippet_text = (snippet or "").strip()
    body_text = (body_preview or "").strip()
    if snippet_text and body_text and body_text != snippet_text:
        preview = f"{snippet_text} {body_text}".strip()
    else:
        preview = snippet_text or body_text
    preview = WHITESPACE_RE.sub(" ", preview)
    if len(preview) <= limit:
        return preview
    return preview[: limit - 1].rstrip() + "…"


def _get_user_email(conn, user_id: int) -> str:
    row = fetch_one(
        conn,
        "SELECT email FROM users WHERE id = :user_id",
        {"user_id": user_id},
    )
    if row is None:
        raise DigestUserNotFoundError("User not found.")
    return str(row["email"])


def get_digest_window(
    user_id: int,
    as_of: datetime | None = None,
) -> tuple[datetime, datetime, str]:
    effective_user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="get_digest_window",
    )
    as_of_utc = _ensure_utc(as_of)
    settings = get_notification_settings(user_id=effective_user_id)
    timezone_name = str(settings["timezone"] or "America/Los_Angeles")
    zone = ZoneInfo(timezone_name)
    as_of_local = as_of_utc.astimezone(zone)
    start_local = datetime(
        year=as_of_local.year,
        month=as_of_local.month,
        day=as_of_local.day,
        tzinfo=zone,
    )
    return start_local.astimezone(timezone.utc), as_of_utc, timezone_name


def _fetch_processed_digest_rows(
    conn,
    *,
    user_id: int,
    window_start: str,
    window_end: str,
    limit: int = PROCESSED_DIGEST_LIMIT,
) -> list[dict]:
    rows = fetch_all(
        conn,
        """
        SELECT
            l.id,
            l.created_at AS processed_at,
            l.account_email,
            l.selected_action,
            COALESCE(l.action_source, 'legacy_unknown') AS action_source,
            l.user_overrode,
            l.created_rule_id,
            COALESCE(m.sender_domain, 'unknown') AS sender_domain,
            COALESCE(m.sender, 'Unknown sender') AS sender,
            COALESCE(m.subject, 'Unknown subject') AS subject,
            m.snippet,
            m.body_preview
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
        LEFT JOIN mail_accounts account_ma
          ON account_ma.external_account_email = l.account_email
         AND account_ma.user_id = :user_id
        WHERE l.selected_action != 'recover'
          AND l.created_at >= :window_start
          AND l.created_at < :window_end
          AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
        ORDER BY
            CASE
                WHEN COALESCE(l.action_source, 'legacy_unknown') = 'high_confidence_auto_clean'
                THEN 0
                ELSE 1
            END,
            l.created_at DESC,
            l.id DESC
        LIMIT :limit
        """,
        {
            "user_id": user_id,
            "window_start": window_start,
            "window_end": window_end,
            "limit": limit,
        },
    )

    return [
        {
            "id": int(row["id"]),
            "processed_at": row["processed_at"],
            "account_email": row["account_email"],
            "selected_action": row["selected_action"],
            "selected_action_label": DIGEST_ACTION_LABELS.get(
                row["selected_action"], row["selected_action"]
            ),
            "action_source": row["action_source"],
            "action_source_label": _source_label(row["action_source"]),
            "sender_domain": row["sender_domain"],
            "sender": row["sender"],
            "subject": row["subject"],
            "preview": _normalize_preview(row["snippet"], row["body_preview"]),
            "user_overrode": bool(row["user_overrode"]),
            "created_rule_id": row["created_rule_id"],
        }
        for row in rows
    ]


def _fetch_top_sender_domains(
    conn,
    *,
    user_id: int,
    window_start: str,
    window_end: str,
) -> list[dict]:
    rows = fetch_all(
        conn,
        """
        SELECT
            COALESCE(NULLIF(m.sender_domain, ''), 'unknown') AS sender_domain,
            l.selected_action,
            COALESCE(l.action_source, 'legacy_unknown') AS action_source,
            COALESCE(m.subject, 'Unknown subject') AS subject,
            l.created_at AS processed_at
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
        LEFT JOIN mail_accounts account_ma
          ON account_ma.external_account_email = l.account_email
         AND account_ma.user_id = :user_id
        WHERE l.selected_action != 'recover'
          AND l.created_at >= :window_start
          AND l.created_at < :window_end
          AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
        ORDER BY l.created_at DESC, l.id DESC
        """,
        {
            "user_id": user_id,
            "window_start": window_start,
            "window_end": window_end,
        },
    )

    domains: dict[str, dict] = {}
    action_counts: defaultdict[str, Counter] = defaultdict(Counter)
    source_counts: defaultdict[str, Counter] = defaultdict(Counter)
    samples: defaultdict[str, list[str]] = defaultdict(list)

    for row in rows:
        domain = str(row["sender_domain"] or "unknown").lower()
        if domain not in domains:
            domains[domain] = {
                "sender_domain": domain,
                "message_count": 0,
                "latest_processed_at": row["processed_at"],
            }
        domains[domain]["message_count"] += 1
        action_counts[domain][str(row["selected_action"])] += 1
        source_counts[domain][str(row["action_source"])] += 1
        if len(samples[domain]) < DIGEST_DOMAIN_SAMPLE_LIMIT:
            samples[domain].append(str(row["subject"] or "Unknown subject"))

    sorted_domains = sorted(
        domains.values(),
        key=lambda item: (-int(item["message_count"]), str(item["sender_domain"])),
    )
    top_domains = sorted_domains[:DIGEST_DOMAIN_SUMMARY_LIMIT]
    return [
        item
        | {
            "counts_by_action": dict(action_counts[item["sender_domain"]]),
            "counts_by_source": dict(source_counts[item["sender_domain"]]),
            "sample_subjects": samples[item["sender_domain"]],
        }
        for item in top_domains
    ]


def build_processed_digest_payload(
    user_id: int,
    as_of: datetime | None = None,
) -> dict:
    effective_user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="build_processed_digest_payload",
    )
    window_start_dt, window_end_dt, timezone_name = get_digest_window(
        effective_user_id,
        as_of=as_of,
    )
    generated_at = _ensure_utc(as_of)
    window_start = _format_digest_timestamp(window_start_dt)
    window_end = _format_digest_timestamp(window_end_dt)

    settings = get_notification_settings(user_id=effective_user_id)

    with get_connection() as conn:
        user_email = _get_user_email(conn, effective_user_id)

        processed_count_row = fetch_one(
            conn,
            """
            SELECT COUNT(*) AS count
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
            LEFT JOIN mail_accounts account_ma
              ON account_ma.external_account_email = l.account_email
             AND account_ma.user_id = :user_id
            WHERE l.selected_action != 'recover'
              AND l.created_at >= :window_start
              AND l.created_at < :window_end
              AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
            """,
            {
                "user_id": effective_user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )

        action_rows = fetch_all(
            conn,
            """
            SELECT l.selected_action, COUNT(*) AS count
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
            LEFT JOIN mail_accounts account_ma
              ON account_ma.external_account_email = l.account_email
             AND account_ma.user_id = :user_id
            WHERE l.selected_action != 'recover'
              AND l.created_at >= :window_start
              AND l.created_at < :window_end
              AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
            GROUP BY l.selected_action
            """,
            {
                "user_id": effective_user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )

        source_rows = fetch_all(
            conn,
            """
            SELECT COALESCE(l.action_source, 'legacy_unknown') AS action_source, COUNT(*) AS count
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
            LEFT JOIN mail_accounts account_ma
              ON account_ma.external_account_email = l.account_email
             AND account_ma.user_id = :user_id
            WHERE l.selected_action != 'recover'
              AND l.created_at >= :window_start
              AND l.created_at < :window_end
              AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
            GROUP BY COALESCE(l.action_source, 'legacy_unknown')
            """,
            {
                "user_id": effective_user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )

        new_rules_row = fetch_one(
            conn,
            """
            SELECT COUNT(*) AS count
            FROM rules
            WHERE user_id = :user_id
              AND created_at >= :window_start
              AND created_at < :window_end
            """,
            {
                "user_id": effective_user_id,
                "window_start": window_start,
                "window_end": window_end,
            },
        )

        queue_count_row = fetch_one(
            conn,
            """
            SELECT COUNT(*) AS count
            FROM messages m
            LEFT JOIN mail_accounts owned_ma
              ON owned_ma.id = m.mail_account_id
            LEFT JOIN mail_accounts account_ma
              ON account_ma.external_account_email = m.account_email
             AND account_ma.user_id = :user_id
            WHERE m.reviewed = 0
              AND COALESCE(owned_ma.user_id, account_ma.user_id) = :user_id
            """,
            {"user_id": effective_user_id},
        )

        processed_messages = _fetch_processed_digest_rows(
            conn,
            user_id=effective_user_id,
            window_start=window_start,
            window_end=window_end,
            limit=PROCESSED_DIGEST_LIMIT,
        )
        top_sender_domains = _fetch_top_sender_domains(
            conn,
            user_id=effective_user_id,
            window_start=window_start,
            window_end=window_end,
        )

    action_counter = Counter(
        {
            str(row["selected_action"]): int(row["count"])
            for row in action_rows
        }
    )
    counts_by_action = {
        action: int(action_counter.get(action, 0))
        for action in DIGEST_ACTION_ORDER
    }
    counts_by_source = {
        str(row["action_source"]): int(row["count"])
        for row in source_rows
    }
    processed_count = int(processed_count_row["count"]) if processed_count_row else 0
    new_rules_count = int(new_rules_row["count"]) if new_rules_row else 0
    queue_count = int(queue_count_row["count"]) if queue_count_row else 0
    recipient_email = (
        (settings.get("recipient_email") or "").strip().lower() or user_email
    )
    processed_overflow_count = max(0, processed_count - len(processed_messages))

    payload = {
        "generated_at": _format_digest_timestamp(generated_at),
        "digest_type": "daily_processed",
        "timezone": timezone_name,
        "window_start": window_start,
        "window_end": window_end,
        "window_display": _format_display_window(
            window_start_dt,
            window_end_dt,
            timezone_name,
        ),
        "recipient_email": recipient_email,
        "processed_count": processed_count,
        "counts_by_action": counts_by_action,
        "counts_by_source": counts_by_source,
        "new_rules_count": new_rules_count,
        "queue_count": queue_count,
        "processed_messages": processed_messages,
        "top_sender_domains": top_sender_domains,
        "processed_overflow_count": processed_overflow_count,
        "frontend_url": FRONTEND_URL,
        "digest_enabled": bool(settings.get("digest_enabled")),
        "digest_time": settings.get("digest_time") or "17:00",
        "ai_summary_enabled": bool(settings.get("ai_digest_summary_enabled")),
        "ai_summary": None,
        "ai_summary_error": None,
    }
    ai_summary_expected = (
        bool(settings.get("ai_digest_summary_enabled"))
        and processed_count > 0
    )
    try:
        payload["ai_summary"] = build_ai_digest_summary(
            payload,
            user_id=effective_user_id,
            enabled_for_user=bool(settings.get("ai_digest_summary_enabled")),
        )
    except Exception as error:
        logger.warning(
            "AI digest summary failed before rendering digest for user %s: %s",
            effective_user_id,
            error,
        )
        payload["ai_summary"] = None
    if ai_summary_expected and payload["ai_summary"] is None:
        payload["ai_summary_error"] = (
            "AI summary was unavailable, so this digest was sent with the standard summary only."
        )
    payload["plain_text_preview"] = render_processed_digest_text(payload)
    payload["html_preview"] = render_processed_digest_html(payload)
    return payload


def render_processed_digest_text(payload: dict) -> str:
    lines = [
        "Fynish daily digest",
        "",
        f"Digest window: {payload['window_display']}",
        f"Recipient: {payload['recipient_email']}",
        "",
        f"Processed messages: {payload['processed_count']}",
        f"Auto-cleaned messages: {payload.get('counts_by_source', {}).get('high_confidence_auto_clean', 0)}",
        f"New rules created: {payload['new_rules_count']}",
        f"Current queue count: {payload['queue_count']}",
        "",
        "Processed by action:",
    ]

    for action in DIGEST_ACTION_ORDER:
        lines.append(
            f"- {DIGEST_ACTION_LABELS[action]}: {payload['counts_by_action'].get(action, 0)}"
        )

    ai_summary = payload.get("ai_summary")
    if ai_summary:
        lines.extend(["", "Today's inbox briefing:"])
        if ai_summary.get("headline"):
            lines.append(str(ai_summary["headline"]))
        if ai_summary.get("summary"):
            lines.extend(["", str(ai_summary["summary"])])
        if ai_summary.get("key_takeaways"):
            lines.extend(["", "Worth noticing:"])
            for takeaway in ai_summary["key_takeaways"]:
                lines.append(f"- {takeaway}")
        auto_clean_review = ai_summary.get("auto_clean_review") or {}
        if auto_clean_review.get("summary"):
            lines.extend(["", f"Auto-clean review: {auto_clean_review['summary']}"])
    elif payload.get("ai_summary_error"):
        lines.extend(["", str(payload["ai_summary_error"])])

    lines.extend(["", "Processed Mail:"])

    if not payload["processed_messages"]:
        lines.append("No processed messages during this digest window.")
    else:
        for message in payload["processed_messages"]:
            processed_at = message["processed_at"]
            lines.append(
                f"- [{message.get('action_source_label') or _source_label(message.get('action_source'))} | "
                f"{message['selected_action_label']}] {message['sender']} | "
                f"{message['subject']} | {processed_at} | {message['account_email']}"
            )
        if payload["processed_overflow_count"] > 0:
            lines.append(
                f"+ {payload['processed_overflow_count']} more processed messages not shown"
            )

    lines.extend(["", "Top sender domains:"])
    if not payload["top_sender_domains"]:
        lines.append("No sender domains during this digest window.")
    else:
        for domain in payload["top_sender_domains"]:
            sample_text = "; ".join(domain["sample_subjects"])
            lines.append(
                f"- {domain['sender_domain']}: {domain['message_count']} messages"
                + (f" | {sample_text}" if sample_text else "")
            )

    lines.extend(
        [
            "",
            f"Open Fynish: {payload['frontend_url']}",
            "You can review or recover processed messages from the Processed Mail screen.",
        ]
    )
    return "\n".join(lines).strip()


def _action_badge_html(action: str, label: str) -> str:
    background, color = DIGEST_ACTION_COLORS.get(action, ("#f3f4f6", "#374151"))
    return (
        f'<span style="display:inline-block; min-width:58px; text-align:center; '
        f'border-radius:999px; padding:4px 9px; background:{background}; color:{color}; '
        f'font-size:12px; font-weight:700;">{escape(label)}</span>'
    )


def _source_badge_html(source: str, label: str) -> str:
    background, color = DIGEST_ACTION_SOURCE_COLORS.get(source, ("#f3f4f6", "#374151"))
    return (
        f'<span style="display:inline-block; min-width:82px; text-align:center; '
        f'border-radius:999px; padding:4px 9px; background:{background}; color:{color}; '
        f'font-size:12px; font-weight:800;">{escape(label)}</span>'
    )


def _render_ai_summary_html(ai_summary: dict | None) -> str:
    if not ai_summary:
        return ""

    headline = escape(str(ai_summary.get("headline") or "Today's inbox briefing"))
    summary = escape(str(ai_summary.get("summary") or ""))
    key_takeaways = ai_summary.get("key_takeaways") or []
    auto_clean_review = ai_summary.get("auto_clean_review") or {}
    notable_kept_messages = ai_summary.get("notable_kept_messages") or []
    top_noise_sources = ai_summary.get("top_noise_sources") or []
    caveats = ai_summary.get("caveats") or []

    takeaway_html = "".join(
        f'<li style="margin:0 0 6px;">{escape(str(item))}</li>'
        for item in key_takeaways[:5]
    )
    notable_html = "".join(
        f"""
        <li style="margin:0 0 6px;">
          <strong>{escape(str(item.get("subject") or "Untitled"))}</strong>
          <span style="color:#6b7280;"> - {escape(str(item.get("reason") or ""))}</span>
        </li>
        """
        for item in notable_kept_messages[:5]
    )
    noise_html = "".join(
        f"""
        <li style="margin:0 0 6px;">
          <strong>{escape(str(item.get("sender_domain") or "unknown"))}</strong>
          <span style="color:#6b7280;"> - {escape(str(item.get("summary") or ""))}</span>
        </li>
        """
        for item in top_noise_sources[:5]
    )
    caveat_text = " ".join(str(caveat) for caveat in caveats[:2])

    return f"""
        <div style="padding:22px 26px; border-bottom:1px solid #e5e7eb; background:#fbfcfd;">
          <h2 style="font-size:18px; margin:0 0 8px; color:#111827;">Today's inbox briefing</h2>
          <div style="font-size:16px; font-weight:800; color:#111827; line-height:1.35;">{headline}</div>
          <p style="font-size:14px; color:#374151; line-height:1.55; margin:8px 0 0;">{summary}</p>
          {f'<h3 style="font-size:13px; margin:16px 0 6px; color:#111827;">Worth noticing</h3><ul style="margin:0; padding-left:18px; font-size:13px; color:#374151; line-height:1.5;">{takeaway_html}</ul>' if takeaway_html else ''}
          {f'<h3 style="font-size:13px; margin:16px 0 6px; color:#111827;">Auto-clean review</h3><p style="font-size:13px; color:#374151; line-height:1.5; margin:0;">{escape(str(auto_clean_review.get("summary") or ""))}</p>' if auto_clean_review.get("summary") else ''}
          {f'<h3 style="font-size:13px; margin:16px 0 6px; color:#111827;">Notable kept messages</h3><ul style="margin:0; padding-left:18px; font-size:13px; color:#374151; line-height:1.5;">{notable_html}</ul>' if notable_html else ''}
          {f'<h3 style="font-size:13px; margin:16px 0 6px; color:#111827;">Top noise sources</h3><ul style="margin:0; padding-left:18px; font-size:13px; color:#374151; line-height:1.5;">{noise_html}</ul>' if noise_html else ''}
          {f'<p style="font-size:12px; color:#6b7280; line-height:1.45; margin:14px 0 0;">{escape(caveat_text)}</p>' if caveat_text else ''}
        </div>
    """


def render_processed_digest_html(payload: dict) -> str:
    frontend_url = str(payload["frontend_url"]).rstrip("/")
    processed_url = f"{frontend_url}/?view=processed"
    queue_url = f"{frontend_url}/?view=queue"
    timezone_name = str(payload["timezone"] or "America/Los_Angeles")
    auto_clean_count = int(
        payload.get("counts_by_source", {}).get("high_confidence_auto_clean", 0)
    )
    ai_summary_html = _render_ai_summary_html(payload.get("ai_summary"))
    ai_summary_error_html = ""
    if payload.get("ai_summary_error"):
        ai_summary_error_html = f"""
        <div style="padding:16px 26px; border-bottom:1px solid #e5e7eb; background:#fff7ed;">
          <div style="font-size:13px; color:#9a3412; line-height:1.5; font-weight:700;">{escape(str(payload["ai_summary_error"]))}</div>
        </div>
        """

    action_cells = []
    for action in DIGEST_ACTION_ORDER:
        label = DIGEST_ACTION_LABELS[action]
        count = payload["counts_by_action"].get(action, 0)
        action_cells.append(
            f"""
            <td style="padding:10px 12px; border:1px solid #e5e7eb; border-radius:8px; background:#ffffff;">
              <div style="font-size:12px; color:#6b7280; margin-bottom:4px;">{escape(label)}</div>
              <div style="font-size:20px; font-weight:800; color:#111827;">{count}</div>
            </td>
            """
        )

    if payload["processed_messages"]:
        processed_rows = []
        for message in payload["processed_messages"]:
            processed_at = _format_message_time(message["processed_at"], timezone_name)
            action = str(message["selected_action"])
            label = str(message["selected_action_label"])
            source = str(message.get("action_source") or "legacy_unknown")
            source_label = str(message.get("action_source_label") or _source_label(source))
            sender = escape(str(message["sender"]))
            subject = escape(str(message["subject"]))
            account = escape(str(message["account_email"]))
            domain = escape(str(message.get("sender_domain") or "unknown"))
            row_background = (
                "background:#fffbeb;"
                if source == "high_confidence_auto_clean"
                else "background:#ffffff;"
            )
            processed_rows.append(
                f"""
                <tr style="{row_background}">
                  <td style="padding:13px 12px; border-bottom:1px solid #e5e7eb; vertical-align:top;">
                    {_source_badge_html(source, source_label)}
                  </td>
                  <td style="padding:13px 12px; border-bottom:1px solid #e5e7eb; vertical-align:top;">
                    {_action_badge_html(action, label)}
                  </td>
                  <td style="padding:13px 12px; border-bottom:1px solid #e5e7eb;">
                    <div style="font-size:14px; font-weight:700; color:#111827; line-height:1.35;">{subject}</div>
                    <div style="font-size:13px; color:#4b5563; line-height:1.45; margin-top:3px;">{sender}</div>
                    <div style="font-size:12px; color:#6b7280; line-height:1.45; margin-top:3px;">{domain}</div>
                  </td>
                  <td style="padding:13px 12px; border-bottom:1px solid #e5e7eb; vertical-align:top; font-size:12px; color:#6b7280; white-space:nowrap;">
                    {escape(processed_at)}
                  </td>
                  <td style="padding:13px 12px; border-bottom:1px solid #e5e7eb; vertical-align:top; font-size:12px; color:#6b7280;">
                    {account}
                  </td>
                </tr>
                """
            )
        processed_html = "\n".join(processed_rows)
    else:
        processed_html = """
        <tr>
          <td colspan="5" style="padding:16px 12px; color:#6b7280;">No processed messages during this digest window.</td>
        </tr>
        """

    overflow_html = ""
    if payload["processed_overflow_count"] > 0:
        overflow_html = (
            f'<p style="margin:12px 0 0; font-size:13px; color:#6b7280;">'
            f'+ {payload["processed_overflow_count"]} more processed messages not shown</p>'
        )

    if payload["top_sender_domains"]:
        domain_items = []
        for domain in payload["top_sender_domains"]:
            samples = "; ".join(str(subject) for subject in domain["sample_subjects"])
            sample_html = (
                f'<div style="font-size:12px; color:#6b7280; line-height:1.45; margin-top:4px;">'
                f'{escape(samples)}</div>'
                if samples
                else ""
            )
            domain_items.append(
                f"""
                <tr>
                  <td style="padding:10px 0; border-bottom:1px solid #edf0f3;">
                    <div style="font-size:14px; font-weight:700; color:#111827;">{escape(str(domain["sender_domain"]))}</div>
                    {sample_html}
                  </td>
                  <td style="padding:10px 0; border-bottom:1px solid #edf0f3; text-align:right; font-size:14px; font-weight:800; color:#111827;">
                    {domain["message_count"]}
                  </td>
                </tr>
                """
            )
        domains_html = "\n".join(domain_items)
    else:
        domains_html = '<tr><td style="padding:12px 0; color:#6b7280;">No sender domains during this digest window.</td><td></td></tr>'

    return f"""<!doctype html>
<html>
  <body style="margin:0; padding:0; background:#f6f7f9; color:#111827; font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Arial,sans-serif;">
    <div style="max-width:920px; margin:0 auto; padding:28px 18px;">
      <div style="background:#ffffff; border:1px solid #e5e7eb; border-radius:12px; overflow:hidden;">
        <div style="padding:24px 26px; border-bottom:1px solid #e5e7eb;">
          <div style="font-size:13px; color:#6b7280; font-weight:700; text-transform:uppercase; letter-spacing:.04em;">Fynish</div>
          <h1 style="font-size:26px; line-height:1.2; margin:6px 0 8px; color:#111827;">Daily digest</h1>
          <div style="font-size:14px; color:#4b5563; line-height:1.5;">{escape(str(payload["window_display"]))}</div>
        </div>

        <div style="padding:20px 26px; border-bottom:1px solid #e5e7eb;">
          <table role="presentation" width="100%" cellspacing="0" cellpadding="0" style="border-collapse:separate; border-spacing:8px;">
            <tr>
              <td style="padding:14px 16px; border-radius:9px; background:#111827; color:#ffffff;">
                <div style="font-size:12px; color:#d1d5db;">Processed</div>
                <div style="font-size:28px; font-weight:800; line-height:1.1;">{payload["processed_count"]}</div>
              </td>
              <td style="padding:14px 16px; border-radius:9px; background:#f3f4f6;">
                <div style="font-size:12px; color:#6b7280;">Auto-cleaned</div>
                <div style="font-size:28px; font-weight:800; line-height:1.1;">{auto_clean_count}</div>
              </td>
              <td style="padding:14px 16px; border-radius:9px; background:#f3f4f6;">
                <div style="font-size:12px; color:#6b7280;">New rules</div>
                <div style="font-size:28px; font-weight:800; line-height:1.1;">{payload["new_rules_count"]}</div>
              </td>
              <td style="padding:14px 16px; border-radius:9px; background:#f3f4f6;">
                <div style="font-size:12px; color:#6b7280;">Queue now</div>
                <div style="font-size:28px; font-weight:800; line-height:1.1;">{payload["queue_count"]}</div>
              </td>
            </tr>
          </table>

          <table role="presentation" width="100%" cellspacing="8" cellpadding="0" style="margin-top:6px;">
            <tr>{''.join(action_cells)}</tr>
          </table>
        </div>

        {ai_summary_html}
        {ai_summary_error_html}

        <div style="padding:22px 26px; border-bottom:1px solid #e5e7eb;">
          <h2 style="font-size:18px; margin:0 0 12px; color:#111827;">Processed Mail</h2>
          <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse; border:1px solid #e5e7eb; border-radius:8px; overflow:hidden;">
            <thead>
              <tr style="background:#f9fafb;">
                <th align="left" style="padding:10px 12px; font-size:12px; color:#6b7280; border-bottom:1px solid #e5e7eb;">Source</th>
                <th align="left" style="padding:10px 12px; font-size:12px; color:#6b7280; border-bottom:1px solid #e5e7eb;">Action</th>
                <th align="left" style="padding:10px 12px; font-size:12px; color:#6b7280; border-bottom:1px solid #e5e7eb;">Message</th>
                <th align="left" style="padding:10px 12px; font-size:12px; color:#6b7280; border-bottom:1px solid #e5e7eb;">Processed</th>
                <th align="left" style="padding:10px 12px; font-size:12px; color:#6b7280; border-bottom:1px solid #e5e7eb;">Inbox</th>
              </tr>
            </thead>
            <tbody>{processed_html}</tbody>
          </table>
          {overflow_html}
        </div>

        <div style="padding:22px 26px;">
          <h2 style="font-size:18px; margin:0 0 8px; color:#111827;">Top sender domains</h2>
          <table width="100%" cellspacing="0" cellpadding="0" style="border-collapse:collapse;">
            <tbody>{domains_html}</tbody>
          </table>
        </div>
      </div>

      <div style="text-align:center; margin-top:18px;">
        <a href="{escape(processed_url)}" style="display:inline-block; padding:11px 16px; border-radius:8px; background:#111827; color:#ffffff; text-decoration:none; font-size:14px; font-weight:700;">Open Processed Mail</a>
        <a href="{escape(queue_url)}" style="display:inline-block; padding:11px 16px; border-radius:8px; color:#111827; text-decoration:none; font-size:14px; font-weight:700;">Open Review Queue</a>
      </div>
    </div>
  </body>
</html>"""


def _subject_for_payload(payload: dict) -> str:
    end_dt = datetime.fromisoformat(payload["window_end"])
    return f"Fynish daily digest for {end_dt.strftime('%B %d, %Y')}"


def _activity_present(payload: dict) -> bool:
    return (
        payload["processed_count"] > 0
        or payload["new_rules_count"] > 0
        or payload["queue_count"] > 0
    )


def _already_sent(conn, *, user_id: int, window_start: str) -> bool:
    row = fetch_one(
        conn,
        """
        SELECT id
        FROM digest_delivery_log
        WHERE user_id = :user_id
          AND digest_type = 'daily_processed'
          AND window_start = :window_start
          AND status = 'sent'
        ORDER BY id DESC
        LIMIT 1
        """,
        {
            "user_id": user_id,
            "window_start": window_start,
        },
    )
    return row is not None


def _record_digest_delivery(
    conn,
    *,
    user_id: int,
    payload: dict,
    status: str,
    sent_at: str | None = None,
    scheduled_for: str | None = None,
    error_message: str | None = None,
) -> int:
    now = _format_digest_timestamp(datetime.now(timezone.utc))
    return insert_and_return_id(
        conn,
        """
        INSERT INTO digest_delivery_log (
            user_id,
            digest_type,
            window_start,
            window_end,
            scheduled_for,
            sent_at,
            status,
            recipient_email,
            processed_count,
            new_rules_count,
            queue_count,
            error_message,
            created_at,
            updated_at
        ) VALUES (
            :user_id,
            'daily_processed',
            :window_start,
            :window_end,
            :scheduled_for,
            :sent_at,
            :status,
            :recipient_email,
            :processed_count,
            :new_rules_count,
            :queue_count,
            :error_message,
            :created_at,
            :updated_at
        )
        """,
        {
            "user_id": user_id,
            "window_start": payload["window_start"],
            "window_end": payload["window_end"],
            "scheduled_for": scheduled_for,
            "sent_at": sent_at,
            "status": status,
            "recipient_email": payload["recipient_email"],
            "processed_count": payload["processed_count"],
            "new_rules_count": payload["new_rules_count"],
            "queue_count": payload["queue_count"],
            "error_message": error_message,
            "created_at": now,
            "updated_at": now,
        },
    )


def send_processed_digest(user_id: int, as_of: datetime | None = None) -> dict:
    effective_user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="send_processed_digest",
    )
    payload = build_processed_digest_payload(effective_user_id, as_of=as_of)

    with get_connection() as conn:
        if _already_sent(
            conn,
            user_id=effective_user_id,
            window_start=payload["window_start"],
        ):
            return {
                "user_id": effective_user_id,
                "status": "skipped",
                "reason": "Digest already sent for this local day",
                "recipient_email": payload["recipient_email"],
                "processed_count": payload["processed_count"],
                "new_rules_count": payload["new_rules_count"],
                "queue_count": payload["queue_count"],
            }

        if not _activity_present(payload):
            _record_digest_delivery(
                conn,
                user_id=effective_user_id,
                payload=payload,
                status="skipped",
                error_message="No processed activity, rules, or queue items for this window",
            )
            return {
                "user_id": effective_user_id,
                "status": "skipped",
                "reason": "No processed activity, rules, or queue items for this window",
                "recipient_email": payload["recipient_email"],
                "processed_count": payload["processed_count"],
                "new_rules_count": payload["new_rules_count"],
                "queue_count": payload["queue_count"],
            }

    try:
        delivery = send_email(
            to_email=payload["recipient_email"],
            subject=_subject_for_payload(payload),
            text_body=payload["plain_text_preview"],
            html_body=payload["html_preview"],
        )
    except (MailerNotConfiguredError, MailDeliveryError) as error:
        with get_connection() as conn:
            _record_digest_delivery(
                conn,
                user_id=effective_user_id,
                payload=payload,
                status="failed",
                error_message=str(error),
            )
        raise

    sent_at = _format_digest_timestamp(datetime.now(timezone.utc))
    with get_connection() as conn:
        _record_digest_delivery(
            conn,
            user_id=effective_user_id,
            payload=payload,
            status="sent",
            sent_at=sent_at,
        )

    return {
        "user_id": effective_user_id,
        "status": "sent",
        "recipient_email": payload["recipient_email"],
        "processed_count": payload["processed_count"],
        "new_rules_count": payload["new_rules_count"],
        "queue_count": payload["queue_count"],
        "provider": delivery.provider,
        "message_id": delivery.message_id,
        "sent_at": sent_at,
    }


def _scheduled_digest_candidates() -> list[dict]:
    with get_connection() as conn:
        rows = fetch_all(
            conn,
            """
            SELECT ns.user_id, ns.timezone, ns.digest_time
            FROM notification_settings_by_user ns
            JOIN users u ON u.id = ns.user_id
            WHERE ns.digest_enabled = 1
              AND u.status = 'active'
            ORDER BY ns.user_id ASC
            """,
        )
    return [dict(row) for row in rows]


def _is_user_due_for_digest(candidate: dict, *, as_of_utc: datetime) -> bool:
    zone = ZoneInfo(candidate["timezone"] or "America/Los_Angeles")
    as_of_local = as_of_utc.astimezone(zone)
    hour, minute = [int(part) for part in str(candidate["digest_time"]).split(":", 1)]
    scheduled_local = datetime(
        as_of_local.year,
        as_of_local.month,
        as_of_local.day,
        hour,
        minute,
        tzinfo=zone,
    )
    if as_of_local < scheduled_local:
        return False

    window_start_dt, _, _ = get_digest_window(
        int(candidate["user_id"]),
        as_of=as_of_utc,
    )
    with get_connection() as conn:
        return not _already_sent(
            conn,
            user_id=int(candidate["user_id"]),
            window_start=_format_digest_timestamp(window_start_dt),
        )


def send_due_processed_digests(as_of: datetime | None = None) -> dict:
    as_of_utc = _ensure_utc(as_of)
    candidates = _scheduled_digest_candidates()

    sender_status = validate_gmail_digest_sender()
    if sender_status is None:
        return {
            "status": "blocked",
            "reason": "Digest sender is not connected.",
            "users_considered": len(candidates),
            "users_due": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "user_summaries": [],
            "ran_at": _format_digest_timestamp(as_of_utc),
        }
    if sender_status.get("auth_status") != "connected":
        return {
            "status": "blocked",
            "reason": sender_status.get("auth_status_reason") or "Digest sender must be reconnected.",
            "users_considered": len(candidates),
            "users_due": 0,
            "sent": 0,
            "skipped": 0,
            "failed": 0,
            "user_summaries": [],
            "ran_at": _format_digest_timestamp(as_of_utc),
        }

    summaries: list[dict] = []
    sent_count = 0
    skipped_count = 0
    failed_count = 0
    users_due = 0

    for candidate in candidates:
        if not _is_user_due_for_digest(candidate, as_of_utc=as_of_utc):
            continue
        users_due += 1
        user_id = int(candidate["user_id"])
        try:
            result = send_processed_digest(user_id, as_of=as_of_utc)
            summaries.append(result)
            if result["status"] == "sent":
                sent_count += 1
            else:
                skipped_count += 1
        except Exception as error:  # pragma: no cover - service wrapper handles log side effects
            failed_count += 1
            summaries.append(
                {
                    "user_id": user_id,
                    "status": "failed",
                    "reason": str(error),
                }
            )
            logger.exception("Processed digest delivery failed for user %s", user_id)

    return {
        "status": "completed",
        "users_considered": len(candidates),
        "users_due": users_due,
        "sent": sent_count,
        "skipped": skipped_count,
        "failed": failed_count,
        "user_summaries": summaries,
        "ran_at": _format_digest_timestamp(as_of_utc),
    }


class ScheduledDigestService:
    def __init__(self, *, enabled: bool) -> None:
        self.enabled = enabled
        self._run_lock = threading.Lock()

    def run_once(self) -> dict:
        ran_at = _format_digest_timestamp(datetime.now(timezone.utc))
        if not self.enabled:
            return {
                "status": "disabled",
                "reason": "Hosted scheduled digests are disabled",
                "users_considered": 0,
                "users_due": 0,
                "sent": 0,
                "skipped": 0,
                "failed": 0,
                "user_summaries": [],
                "ran_at": ran_at,
            }
        if not self._run_lock.acquire(blocking=False):
            return {
                "status": "skipped",
                "reason": "Scheduled digests are already running",
                "users_considered": 0,
                "users_due": 0,
                "sent": 0,
                "skipped": 0,
                "failed": 0,
                "user_summaries": [],
                "ran_at": ran_at,
            }
        try:
            return send_due_processed_digests()
        finally:
            self._run_lock.release()

scheduled_digest_service = ScheduledDigestService(enabled=SCHEDULED_DIGESTS_ENABLED)
