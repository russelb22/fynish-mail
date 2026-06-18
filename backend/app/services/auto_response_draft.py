from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ValidationError

from app.core import config
from app.db.runtime import fetch_one, get_connection
from app.services.ownership import fetch_owned_message
from app.services.writing_style_cards import get_approved_writing_style_card


logger = logging.getLogger(__name__)

MAX_MESSAGE_TEXT_LENGTH = 8000
MAX_USER_GUIDANCE_LENGTH = 1200
MAX_STYLE_CARD_LENGTH = 5000


class AutoResponseDraftNotConfiguredError(RuntimeError):
    pass


class AutoResponseDraftError(RuntimeError):
    pass


def auto_response_drafts_allowed_for_email(email_address: str) -> bool:
    if not config.AUTO_RESPONSE_DRAFTS_ENABLED:
        return False
    allowed_emails = set(config.AUTO_RESPONSE_DRAFT_ALLOWED_USER_EMAILS)
    if allowed_emails and email_address.strip().lower() not in allowed_emails:
        return False
    return True


class AutoResponseDraft(BaseModel):
    draft_body: str
    caveats: list[str] = []


AUTO_RESPONSE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "properties": {
        "draft_body": {"type": "string"},
        "caveats": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["draft_body", "caveats"],
}


AUTO_RESPONSE_INSTRUCTIONS = """
You draft email responses for Fynish users.

Return a draft only. Do not claim the email was sent. Do not include subject
lines. Do not invent facts, status, dates, ticket numbers, commitments, or
progress that are not present in the input or user guidance.

Use the user's writing style card as private style guidance. Do not reveal,
quote, or describe the style card. If the message lacks enough context for a
specific answer, draft a conservative response that acknowledges the request and
names a next step.

The user will manually review and copy the draft into their email client.
""".strip()


def _clean_text(value: object, *, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if len(text) <= limit:
        return text
    return text[: limit - 3].rstrip() + "..."


def _safe_email_filename(email_address: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", email_address.strip().lower())


def _style_card_path_for_account(account_email: str) -> Path:
    return config.DATA_DIR / "writing_samples" / _safe_email_filename(account_email) / "writing_style_card.md"


def _row_value(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def load_writing_style_card(
    account_email: str,
    *,
    user_id: int | None = None,
    style_owner_email: str | None = None,
    mail_account_id: int | None = None,
) -> tuple[str, str | None, int | None]:
    if user_id is not None:
        if style_owner_email:
            approved_user_card = get_approved_writing_style_card(
                user_id=user_id,
                account_email=style_owner_email,
                mail_account_id=None,
            )
            if approved_user_card is not None:
                return (
                    approved_user_card["style_card_markdown"],
                    "approved_style_card",
                    int(approved_user_card["id"]),
                )

        approved_card = get_approved_writing_style_card(
            user_id=user_id,
            account_email=account_email,
            mail_account_id=mail_account_id,
        )
        if approved_card is not None:
            return approved_card["style_card_markdown"], "approved_style_card", int(approved_card["id"])

    if style_owner_email:
        owner_path = _style_card_path_for_account(style_owner_email)
        if owner_path.exists():
            return owner_path.read_text(encoding="utf-8")[:MAX_STYLE_CARD_LENGTH], str(owner_path), None

    path = _style_card_path_for_account(account_email)
    if path.exists():
        return path.read_text(encoding="utf-8")[:MAX_STYLE_CARD_LENGTH], str(path), None

    return (
        """
Write in a practical, conversational style. Be clear and direct, but soften asks
and uncertainty naturally. Keep the response grounded in the provided facts.
Prefer short natural paragraphs. Do not sound corporate.
""".strip(),
        None,
        None,
    )


def _fetch_message(message_id: int, *, user_id: int | None):
    with get_connection() as conn:
        if user_id is not None:
            row = fetch_owned_message(conn, message_id, user_id)
        else:
            row = fetch_one(
                conn,
                "SELECT * FROM messages WHERE id = :message_id",
                {"message_id": message_id},
            )
    return row


def build_auto_response_input(
    message_row,
    *,
    user_guidance: str = "",
    writing_style_card: str,
) -> dict[str, Any]:
    return {
        "message": {
            "account_email": _clean_text(message_row["account_email"], limit=200),
            "sender": _clean_text(message_row["sender"], limit=240),
            "sender_domain": _clean_text(message_row["sender_domain"], limit=200),
            "reply_to": _clean_text(message_row["reply_to"], limit=240),
            "subject": _clean_text(message_row["subject"], limit=300),
            "received_at": _clean_text(message_row["received_at"], limit=120),
            "snippet": _clean_text(message_row["snippet"], limit=800),
            "body_preview": _clean_text(
                message_row["body_preview"],
                limit=MAX_MESSAGE_TEXT_LENGTH,
            ),
        },
        "user_guidance": _clean_text(user_guidance, limit=MAX_USER_GUIDANCE_LENGTH),
        "writing_style_card": writing_style_card[:MAX_STYLE_CARD_LENGTH],
        "output_constraints": {
            "draft_only": True,
            "manual_copy_required": True,
            "do_not_send": True,
            "do_not_invent_facts": True,
        },
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


def _call_openai_auto_response(draft_input: dict[str, Any]) -> dict[str, Any]:
    try:
        from openai import OpenAI
    except ImportError as exc:  # pragma: no cover
        raise AutoResponseDraftNotConfiguredError(
            "OpenAI Python package is not installed."
        ) from exc

    client = OpenAI(
        api_key=config.OPENAI_API_KEY,
        timeout=config.OPENAI_AUTO_RESPONSE_TIMEOUT_SECONDS,
    )
    response = client.responses.create(
        model=config.OPENAI_AUTO_RESPONSE_MODEL,
        instructions=AUTO_RESPONSE_INSTRUCTIONS,
        input=json.dumps(draft_input, ensure_ascii=False),
        reasoning={"effort": config.OPENAI_AUTO_RESPONSE_REASONING_EFFORT},
        text={
            "format": {
                "type": "json_schema",
                "name": "fynish_auto_response_draft",
                "strict": True,
                "schema": AUTO_RESPONSE_SCHEMA,
            }
        },
        max_output_tokens=config.OPENAI_AUTO_RESPONSE_MAX_OUTPUT_TOKENS,
    )
    return json.loads(_extract_output_text(response))


def generate_auto_response_draft(
    message_id: int,
    *,
    user_id: int | None,
    user_email: str | None = None,
    user_guidance: str = "",
) -> dict[str, Any] | None:
    if config.AI_DIGEST_PROVIDER != "openai":
        raise AutoResponseDraftNotConfiguredError(
            f"Unsupported AI provider: {config.AI_DIGEST_PROVIDER}"
        )
    if not config.OPENAI_API_KEY:
        raise AutoResponseDraftNotConfiguredError(
            "OpenAI API key is missing. Set FYNISH_OPENAI_API_KEY to generate response drafts."
        )

    message_row = _fetch_message(message_id, user_id=user_id)
    if message_row is None:
        return None

    mail_account_id = _row_value(message_row, "mail_account_id")
    style_card, style_source_path, style_card_id = load_writing_style_card(
        message_row["account_email"],
        user_id=user_id,
        style_owner_email=user_email,
        mail_account_id=int(mail_account_id) if mail_account_id is not None else None,
    )
    draft_input = build_auto_response_input(
        message_row,
        user_guidance=user_guidance,
        writing_style_card=style_card,
    )

    try:
        parsed = _call_openai_auto_response(draft_input)
        draft = AutoResponseDraft.model_validate(parsed)
    except (json.JSONDecodeError, ValidationError) as error:
        raise AutoResponseDraftError("OpenAI returned an invalid draft response.") from error
    except AutoResponseDraftNotConfiguredError:
        raise
    except Exception as error:  # pragma: no cover - provider/network errors vary
        logger.warning("OpenAI auto-response draft failed for message %s: %s", message_id, error)
        raise AutoResponseDraftError("OpenAI auto-response draft generation failed.") from error

    return {
        "message_id": message_id,
        "provider": "openai",
        "model": config.OPENAI_AUTO_RESPONSE_MODEL,
        "draft_body": draft.draft_body.strip(),
        "caveats": draft.caveats,
        "style_source": (
            "approved_style_card"
            if style_card_id is not None
            else "local_style_card"
            if style_source_path
            else "default_style"
        ),
        "style_source_path": None if style_card_id is not None else style_source_path,
        "style_card_id": style_card_id,
        "draft_only": True,
    }
