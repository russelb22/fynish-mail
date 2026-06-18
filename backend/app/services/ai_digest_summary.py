from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core import config
from app.services.ai_digest_attention_notes import (
    DEFAULT_DOMAIN_ATTENTION_NOTES,
    get_enabled_ai_digest_attention_notes,
)

logger = logging.getLogger(__name__)

WHITESPACE_RE = re.compile(r"\s+")

MAX_SENDER_LENGTH = 200
MAX_SUBJECT_LENGTH = 240
MAX_SNIPPET_LENGTH = 500
MAX_TOP_DOMAINS = 10
MAX_SAMPLE_SUBJECTS = 3
MAX_DOMAIN_ATTENTION_NOTES = 10
MAX_ATTENTION_NOTE_LENGTH = 800


class SummaryNotableItem(BaseModel):
    subject: str = ""
    reason: str = ""


class SummaryNoiseSource(BaseModel):
    sender_domain: str = ""
    summary: str = ""


class SummaryAutoCleanReview(BaseModel):
    count: int = Field(ge=0)
    summary: str = ""
    notable_items: list[SummaryNotableItem] = Field(default_factory=list)


class AIDigestSummary(BaseModel):
    headline: str = ""
    summary: str = ""
    key_takeaways: list[str] = Field(default_factory=list)
    auto_clean_review: SummaryAutoCleanReview
    notable_kept_messages: list[SummaryNotableItem] = Field(default_factory=list)
    top_noise_sources: list[SummaryNoiseSource] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)


AI_DIGEST_SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "headline": {"type": "string"},
        "summary": {"type": "string"},
        "key_takeaways": {"type": "array", "items": {"type": "string"}},
        "auto_clean_review": {
            "type": "object",
            "additionalProperties": False,
            "properties": {
                "count": {"type": "integer"},
                "summary": {"type": "string"},
                "notable_items": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "subject": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": ["subject", "reason"],
                    },
                },
            },
            "required": ["count", "summary", "notable_items"],
        },
        "notable_kept_messages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "subject": {"type": "string"},
                    "reason": {"type": "string"},
                },
                "required": ["subject", "reason"],
            },
        },
        "top_noise_sources": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "properties": {
                    "sender_domain": {"type": "string"},
                    "summary": {"type": "string"},
                },
                "required": ["sender_domain", "summary"],
            },
        },
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "headline",
        "summary",
        "key_takeaways",
        "auto_clean_review",
        "notable_kept_messages",
        "top_noise_sources",
        "caveats",
    ],
}


AI_DIGEST_INSTRUCTIONS = """
You summarize a Fynish daily processed-mail digest.

Use only the structured input. Do not infer facts beyond sender, domain, subject,
snippet, selected action, action source, digest counts, and domain attention
notes. Keep the tone calm, brief, factual, and non-alarmist.

Call out auto-cleaned messages separately. Do not state that a message is
definitely safe or correctly handled. Use careful language such as "appears",
"looks like", and "based on sender, subject, and snippet".

Do not recommend creating or changing rules. Do not include raw email addresses
unless needed for clarity. Return only the requested structured output.

If domain_attention_notes are provided, apply them when deciding what deserves
attention. These notes are user preferences for digest interpretation only. Do
not claim that Fynish changed any rule, classifier, or Gmail behavior because of
them.

For domains with attention notes:
- highlight messages only when the note says they appear attention-worthy
- treat note-described routine messages as routine
- if evidence is ambiguous, mention uncertainty or omit the item from highlights
- do not invent severity, sender intent, or message content beyond provided fields
""".strip()


def _clean_text(value: object, *, limit: int) -> str:
    text = WHITESPACE_RE.sub(" ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _configured_attention_notes(user_id: int | None) -> list[dict[str, Any]]:
    if user_id is None:
        return [
            {"id": None, "user_id": None, "enabled": True, **item}
            for item in DEFAULT_DOMAIN_ATTENTION_NOTES
        ]
    return get_enabled_ai_digest_attention_notes(user_id=user_id)


def _build_domain_attention_notes(
    processed_messages: list[dict[str, Any]],
    *,
    user_id: int | None,
) -> list[dict[str, Any]]:
    messages_by_domain: dict[str, list[dict[str, Any]]] = {}
    for message in processed_messages:
        domain = str(message.get("sender_domain") or "").strip().lower()
        if not domain:
            continue
        messages_by_domain.setdefault(domain, []).append(message)

    attention_notes = []
    for note in _configured_attention_notes(user_id)[:MAX_DOMAIN_ATTENTION_NOTES]:
        domain = str(note.get("domain") or "").strip().lower()
        matches = messages_by_domain.get(domain, [])
        if not matches:
            continue
        attention_notes.append(
            {
                "domain": _clean_text(domain, limit=200),
                "label": _clean_text(note.get("label"), limit=120),
                "note": _clean_text(note.get("note"), limit=MAX_ATTENTION_NOTE_LENGTH),
                "matched_message_count": len(matches),
                "sample_subjects": [
                    _clean_text(message.get("subject"), limit=MAX_SUBJECT_LENGTH)
                    for message in matches[:MAX_SAMPLE_SUBJECTS]
                ],
            }
        )
    return attention_notes


def build_digest_summary_input(
    payload: dict,
    *,
    include_snippets: bool,
    max_messages: int | None = None,
    user_id: int | None = None,
) -> dict:
    message_limit = max_messages or config.OPENAI_DIGEST_MAX_INPUT_MESSAGES
    processed_messages = []
    for message in payload.get("processed_messages", [])[:message_limit]:
        processed_message = {
            "account_email": _clean_text(message.get("account_email"), limit=200),
            "sender": _clean_text(message.get("sender"), limit=MAX_SENDER_LENGTH),
            "sender_domain": _clean_text(message.get("sender_domain"), limit=200),
            "subject": _clean_text(message.get("subject"), limit=MAX_SUBJECT_LENGTH),
            "selected_action": _clean_text(message.get("selected_action"), limit=40),
            "selected_action_label": _clean_text(
                message.get("selected_action_label"),
                limit=80,
            ),
            "action_source": _clean_text(message.get("action_source"), limit=80),
            "action_source_label": _clean_text(
                message.get("action_source_label"),
                limit=80,
            ),
            "processed_at": _clean_text(message.get("processed_at"), limit=80),
        }
        if include_snippets:
            processed_message["preview"] = _clean_text(
                message.get("preview"),
                limit=MAX_SNIPPET_LENGTH,
            )
        processed_messages.append(processed_message)

    top_sender_domains = []
    for domain in payload.get("top_sender_domains", [])[:MAX_TOP_DOMAINS]:
        top_sender_domains.append(
            {
                "sender_domain": _clean_text(domain.get("sender_domain"), limit=200),
                "message_count": int(domain.get("message_count") or 0),
                "counts_by_action": dict(domain.get("counts_by_action") or {}),
                "counts_by_source": dict(domain.get("counts_by_source") or {}),
                "sample_subjects": [
                    _clean_text(subject, limit=MAX_SUBJECT_LENGTH)
                    for subject in (domain.get("sample_subjects") or [])[
                        :MAX_SAMPLE_SUBJECTS
                    ]
                ],
            }
        )

    return {
        "digest_window": payload.get("window_display"),
        "processed_count": int(payload.get("processed_count") or 0),
        "counts_by_action": dict(payload.get("counts_by_action") or {}),
        "counts_by_source": dict(payload.get("counts_by_source") or {}),
        "new_rules_count": int(payload.get("new_rules_count") or 0),
        "queue_count": int(payload.get("queue_count") or 0),
        "top_sender_domains": top_sender_domains,
        "domain_attention_notes": _build_domain_attention_notes(
            processed_messages,
            user_id=user_id,
        ),
        "processed_messages": processed_messages,
        "input_scope": (
            "sender, domain, subject, action, source, processed time, and preview"
            if include_snippets
            else "sender, domain, subject, action, source, and processed time"
        ),
    }


def _extract_output_text(response: object) -> str:
    output_text = getattr(response, "output_text", None)
    if output_text:
        return str(output_text)

    chunks: list[str] = []
    for item in getattr(response, "output", []) or []:
        for content in getattr(item, "content", []) or []:
            text = getattr(content, "text", None)
            if text:
                chunks.append(str(text))
    return "".join(chunks)


def _call_openai_digest_summary(summary_input: dict) -> dict:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover - exercised only without dependency
        raise RuntimeError("OpenAI Python package is not installed.") from exc

    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        timeout=config.OPENAI_DIGEST_TIMEOUT_SECONDS,
    )
    response = client.responses.create(
        model=config.OPENAI_DIGEST_MODEL,
        instructions=AI_DIGEST_INSTRUCTIONS,
        input=json.dumps(summary_input, ensure_ascii=False),
        reasoning={"effort": config.OPENAI_DIGEST_REASONING_EFFORT},
        text={
            "format": {
                "type": "json_schema",
                "name": "fynish_ai_digest_summary",
                "strict": True,
                "schema": AI_DIGEST_SUMMARY_SCHEMA,
            }
        },
        max_output_tokens=config.OPENAI_DIGEST_MAX_OUTPUT_TOKENS,
    )
    raw_text = _extract_output_text(response)
    parsed = json.loads(raw_text)
    return AIDigestSummary.model_validate(parsed).model_dump()


def build_ai_digest_summary(
    payload: dict,
    *,
    user_id: int,
    enabled_for_user: bool,
) -> dict | None:
    if not config.AI_DIGEST_SUMMARIES_ENABLED:
        return None
    if not enabled_for_user:
        return None
    if config.AI_DIGEST_PROVIDER != "openai":
        logger.warning("Unsupported AI digest provider: %s", config.AI_DIGEST_PROVIDER)
        return None
    if not config.OPENAI_API_KEY:
        logger.warning("AI digest summary skipped because OpenAI API key is missing.")
        return None
    if int(payload.get("processed_count") or 0) <= 0:
        return None

    summary_input = build_digest_summary_input(
        payload,
        include_snippets=config.OPENAI_DIGEST_INCLUDE_SNIPPETS,
        user_id=user_id,
    )
    try:
        summary = _call_openai_digest_summary(summary_input)
    except (json.JSONDecodeError, ValidationError, RuntimeError) as error:
        logger.warning(
            "AI digest summary generation failed for user %s: %s",
            user_id,
            error,
        )
        return None
    except Exception as error:  # pragma: no cover - provider/network errors vary
        logger.warning(
            "AI digest summary provider call failed for user %s: %s",
            user_id,
            error,
        )
        return None

    return {
        "generated": True,
        "provider": config.AI_DIGEST_PROVIDER,
        "model": config.OPENAI_DIGEST_MODEL,
        **summary,
    }
