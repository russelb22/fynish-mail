from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.db.database import get_connection
from app.services.gmail_readonly import (
    build_service_from_token_path,
    fetch_message,
    list_unread_inbox_message_ids,
    transform_gmail_message,
)
from app.services.style_draft_sandbox import load_style_profile
from app.services.writing_sample_export import sample_word_count


BULK_MARKERS = (
    "unsubscribe",
    "newsletter",
    "digest",
    "promotion",
    "discount",
    "limited time",
    "register now",
    "click here",
    "ticker symbol",
    "urgent video",
    "wealth",
    "pre-ipo",
    "ipo",
    "millionaire",
    "stock market",
    "largest ipo",
    "track.",
    "premiumretiring",
)
NO_REPLY_MARKERS = (
    "no-reply",
    "noreply",
    "donotreply",
    "do-not-reply",
    "notifications@",
)
REPLY_INTENT_MARKERS = (
    "please reply",
    "let me know",
    "can you",
    "could you",
    "would you",
    "please review",
    "any questions",
    "confirm",
    "schedule",
    "reschedule",
    "?",
)


@dataclass(frozen=True)
class ReplyCandidate:
    message_id: int
    account_email: str
    sender: str
    sender_domain: str
    subject: str
    received_at: str
    body_preview: str
    current_category: str
    score: int
    reasons: list[str]


def _row_value(row: Any, key: str, default: str = "") -> str:
    value = row[key] if row[key] is not None else default
    return str(value)


def score_reply_candidate(row: Any) -> ReplyCandidate | None:
    sender = _row_value(row, "sender")
    sender_domain = _row_value(row, "sender_domain")
    subject = _row_value(row, "subject")
    body = _row_value(row, "body_preview")
    category = _row_value(row, "current_category")
    labels_raw = _row_value(row, "gmail_labels_json", "[]")
    combined = f"{sender}\n{sender_domain}\n{subject}\n{body}".lower()
    word_count = sample_word_count(body)
    has_reply_intent = any(marker in combined for marker in REPLY_INTENT_MARKERS)

    if word_count < 12:
        return None
    if word_count < 20 and not has_reply_intent:
        return None
    if any(marker in combined for marker in NO_REPLY_MARKERS):
        return None
    if category in {"bulk_mail", "junk_review", "trash"}:
        return None
    if any(marker in combined for marker in BULK_MARKERS):
        return None
    if combined.count("http://") + combined.count("https://") >= 3:
        return None

    score = 0
    reasons: list[str] = []

    if category == "keep":
        score += 20
        reasons.append("kept_by_fynish")
    if "?" in body or "?" in subject:
        score += 25
        reasons.append("contains_question")
    if has_reply_intent:
        score += 30
        reasons.append("reply_intent_marker")
    if 20 <= word_count <= 180:
        score += 20
        reasons.append("useful_body_length")
    elif has_reply_intent:
        score += 10
        reasons.append("short_but_reply_intent")
    if "UNREAD" in labels_raw:
        score += 10
        reasons.append("unread")

    return ReplyCandidate(
        message_id=int(row["id"]),
        account_email=_row_value(row, "account_email"),
        sender=sender,
        sender_domain=sender_domain,
        subject=subject,
        received_at=_row_value(row, "received_at"),
        body_preview=body,
        current_category=category,
        score=score,
        reasons=reasons,
    )


def fetch_reply_candidates(
    *,
    message_account: str | None = None,
    limit: int = 5,
) -> list[ReplyCandidate]:
    params: dict[str, Any] = {}
    where = ["COALESCE(body_preview, '') != ''", "reviewed = 0"]
    if message_account:
        where.append("account_email = :message_account")
        params["message_account"] = message_account

    sql = f"""
        SELECT id, account_email, sender, sender_domain, subject, received_at,
               body_preview, current_category, gmail_labels_json
        FROM messages
        WHERE {' AND '.join(where)}
        ORDER BY received_at DESC, id DESC
        LIMIT 100
    """

    candidates: list[ReplyCandidate] = []
    with get_connection() as conn:
        rows = conn.execute(sql, params).fetchall()
    for row in rows:
        candidate = score_reply_candidate(row)
        if candidate is not None:
            candidates.append(candidate)

    candidates.sort(key=lambda item: (item.score, item.received_at), reverse=True)
    return candidates[:limit]


def candidate_from_gmail_message(
    *,
    account_email: str,
    message: dict[str, Any],
) -> ReplyCandidate | None:
    row = {
        "id": int(str(message.get("gmail_message_id", "0")).encode("utf-8").hex()[:12], 16),
        "account_email": account_email,
        "sender": message.get("sender", ""),
        "sender_domain": "",
        "subject": message.get("subject", ""),
        "received_at": message.get("received_at", ""),
        "body_preview": message.get("body_preview") or message.get("snippet") or "",
        "current_category": "keep",
        "gmail_labels_json": json.dumps(message.get("gmail_labels", [])),
    }
    sender = str(row["sender"]).lower()
    if "@" in sender:
        row["sender_domain"] = sender.rsplit("@", 1)[1].split(">")[0].strip()
    return score_reply_candidate(row)


def fetch_live_gmail_reply_candidates(
    *,
    account_email: str,
    token_path: Path,
    limit: int = 3,
    inspect_limit: int = 20,
) -> list[ReplyCandidate]:
    service = build_service_from_token_path(str(token_path))
    refs = list_unread_inbox_message_ids(service, max_results=inspect_limit)
    candidates: list[ReplyCandidate] = []
    for ref in refs:
        raw = fetch_message(service, ref["id"])
        transformed = transform_gmail_message(raw)
        candidate = candidate_from_gmail_message(
            account_email=account_email,
            message=transformed,
        )
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item.score, item.received_at), reverse=True)
    return candidates[:limit]


def search_live_gmail_reply_candidates(
    *,
    account_email: str,
    token_path: Path,
    query: str,
    limit: int = 3,
    include_low_score: bool = False,
) -> list[ReplyCandidate]:
    service = build_service_from_token_path(str(token_path))
    response = (
        service.users()
        .messages()
        .list(userId="me", q=query, maxResults=limit)
        .execute()
    )
    candidates: list[ReplyCandidate] = []
    for ref in response.get("messages", []) or []:
        raw = fetch_message(service, ref["id"])
        transformed = transform_gmail_message(raw)
        candidate = candidate_from_gmail_message(
            account_email=account_email,
            message=transformed,
        )
        if candidate is None and include_low_score:
            candidate = _fallback_candidate_from_gmail_message(
                account_email=account_email,
                message=transformed,
            )
        if candidate is not None:
            candidates.append(candidate)
    candidates.sort(key=lambda item: (item.score, item.received_at), reverse=True)
    return candidates[:limit]


def _fallback_candidate_from_gmail_message(
    *,
    account_email: str,
    message: dict[str, Any],
) -> ReplyCandidate:
    sender = str(message.get("sender", ""))
    sender_domain = ""
    if "@" in sender:
        sender_domain = sender.lower().rsplit("@", 1)[1].split(">")[0].strip()
    return ReplyCandidate(
        message_id=int(str(message.get("gmail_message_id", "0")).encode("utf-8").hex()[:12], 16),
        account_email=account_email,
        sender=sender,
        sender_domain=sender_domain,
        subject=str(message.get("subject", "")),
        received_at=str(message.get("received_at", "")),
        body_preview=str(message.get("body_preview") or message.get("snippet") or ""),
        current_category="explicit_query_match",
        score=0,
        reasons=["matched_explicit_query"],
    )


def _safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^a-zA-Z0-9._-]+", "-", value.strip().lower()).strip("-")
    return cleaned or "message"


def render_real_reply_packet(
    *,
    style_account: str,
    style_profile: str,
    candidate: ReplyCandidate,
) -> str:
    return f"""# Real Reply Sandbox Packet: message-{candidate.message_id}

## Safety

This is a local draft prompt for review only. Do not send anything. Do not modify Gmail. Do not invent facts. Draft only from the inbound message and the private style profile.

## Task

Draft a possible reply as Russel from {style_account}. Use the writing style profile below as private context. Do not quote or reveal the profile.

## Writing Style Profile

{style_profile}

## Inbound Email Candidate

Account: {candidate.account_email}
From: {candidate.sender}
Subject: {candidate.subject}
Received: {candidate.received_at}
Fynish category: {candidate.current_category}
Candidate score: {candidate.score}
Candidate reasons: {', '.join(candidate.reasons) or '(none)'}

```text
{candidate.body_preview}
```

## Output

Return only a draft email body. Keep it local. Do not send.
"""


def build_real_reply_sandbox(
    *,
    style_account: str,
    style_profile_path: Path,
    message_account: str | None = None,
    limit: int = 5,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    style_profile = load_style_profile(style_profile_path)
    candidates = fetch_reply_candidates(message_account=message_account, limit=limit)
    packets = []
    for candidate in candidates:
        filename = f"message-{candidate.message_id}-{_safe_filename(candidate.subject)[:48]}.md"
        packets.append(
            (
                filename,
                render_real_reply_packet(
                    style_account=style_account,
                    style_profile=style_profile,
                    candidate=candidate,
                ),
            )
        )

    manifest = {
        "style_account": style_account,
        "message_account": message_account,
        "style_profile_path": str(style_profile_path),
        "candidate_count": len(candidates),
        "candidates": [
            {
                "message_id": candidate.message_id,
                "account_email": candidate.account_email,
                "sender_domain": candidate.sender_domain,
                "subject": candidate.subject,
                "received_at": candidate.received_at,
                "score": candidate.score,
                "reasons": candidate.reasons,
                "prompt_packet": filename,
            }
            for candidate, (filename, _content) in zip(candidates, packets)
        ],
    }
    return manifest, packets


def build_live_real_reply_sandbox(
    *,
    style_account: str,
    style_profile_path: Path,
    gmail_account: str,
    token_path: Path,
    limit: int = 3,
    inspect_limit: int = 20,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    style_profile = load_style_profile(style_profile_path)
    candidates = fetch_live_gmail_reply_candidates(
        account_email=gmail_account,
        token_path=token_path,
        limit=limit,
        inspect_limit=inspect_limit,
    )
    packets = []
    for candidate in candidates:
        filename = f"live-message-{candidate.message_id}-{_safe_filename(candidate.subject)[:48]}.md"
        packets.append(
            (
                filename,
                render_real_reply_packet(
                    style_account=style_account,
                    style_profile=style_profile,
                    candidate=candidate,
                ),
            )
        )

    manifest = {
        "style_account": style_account,
        "gmail_account": gmail_account,
        "style_profile_path": str(style_profile_path),
        "token_path": str(token_path),
        "candidate_count": len(candidates),
        "inspect_limit": inspect_limit,
        "candidates": [
            {
                "message_id": candidate.message_id,
                "account_email": candidate.account_email,
                "sender_domain": candidate.sender_domain,
                "subject": candidate.subject,
                "received_at": candidate.received_at,
                "score": candidate.score,
                "reasons": candidate.reasons,
                "prompt_packet": filename,
            }
            for candidate, (filename, _content) in zip(candidates, packets)
        ],
    }
    return manifest, packets


def build_live_gmail_query_reply_sandbox(
    *,
    style_account: str,
    style_profile_path: Path,
    gmail_account: str,
    token_path: Path,
    query: str,
    limit: int = 3,
    include_low_score: bool = True,
) -> tuple[dict[str, Any], list[tuple[str, str]]]:
    style_profile = load_style_profile(style_profile_path)
    candidates = search_live_gmail_reply_candidates(
        account_email=gmail_account,
        token_path=token_path,
        query=query,
        limit=limit,
        include_low_score=include_low_score,
    )
    packets = []
    for candidate in candidates:
        filename = f"query-message-{candidate.message_id}-{_safe_filename(candidate.subject)[:48]}.md"
        packets.append(
            (
                filename,
                render_real_reply_packet(
                    style_account=style_account,
                    style_profile=style_profile,
                    candidate=candidate,
                ),
            )
        )

    manifest = {
        "style_account": style_account,
        "gmail_account": gmail_account,
        "style_profile_path": str(style_profile_path),
        "token_path": str(token_path),
        "query": query,
        "candidate_count": len(candidates),
        "candidates": [
            {
                "message_id": candidate.message_id,
                "account_email": candidate.account_email,
                "sender_domain": candidate.sender_domain,
                "subject": candidate.subject,
                "received_at": candidate.received_at,
                "score": candidate.score,
                "reasons": candidate.reasons,
                "prompt_packet": filename,
            }
            for candidate, (filename, _content) in zip(candidates, packets)
        ],
    }
    return manifest, packets
