from __future__ import annotations

import base64
import json
import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import parseaddr
from typing import Any

from app.core import config
from app.db.runtime import execute_sql, fetch_one, get_connection, insert_and_return_id
from app.services.gmail_readonly import (
    GmailReadonlySyncError,
    build_service_from_token_reference,
    transform_gmail_message,
)
from app.services.gmail_token_store import GmailTokenReference
from app.services.ownership import fetch_owned_message


logger = logging.getLogger(__name__)


class AutoResponseSendNotConfiguredError(RuntimeError):
    pass


class AutoResponseSendValidationError(ValueError):
    pass


class AutoResponseSendError(RuntimeError):
    pass


@dataclass(frozen=True)
class AutoResponseSendResult:
    status: str
    message_id: int
    account_email: str
    to_email: str
    subject: str
    gmail_sent_message_id: str | None
    gmail_thread_id: str | None
    sent_at: str | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AutoResponseSendPreview:
    message_id: int
    account_email: str
    to_email: str
    subject: str
    body_text: str
    gmail_thread_id: str | None
    context_source: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ThreadHistoryMessage:
    gmail_message_id: str
    sender: str
    received_at: str
    body_text: str


def auto_response_send_allowed_for_email(email_address: str) -> bool:
    if not config.AUTO_RESPONSE_SEND_ENABLED:
        return False
    allowed_emails = set(config.AUTO_RESPONSE_SEND_ALLOWED_USER_EMAILS)
    if allowed_emails and email_address.strip().lower() not in allowed_emails:
        return False
    return True


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _row_value(row, key: str, default=None):
    try:
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _parse_headers(headers_json: str | None) -> dict[str, str]:
    if not headers_json:
        return {}
    try:
        parsed = json.loads(headers_json)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _normalize_subject(subject: str | None) -> str:
    clean = " ".join(str(subject or "").split()).strip() or "(No subject)"
    if clean.lower().startswith("re:"):
        return clean
    return f"Re: {clean}"


def _extract_recipient(message_row, override: str | None = None) -> str:
    candidate = override or _row_value(message_row, "reply_to") or _row_value(message_row, "sender")
    _, address = parseaddr(str(candidate or ""))
    address = address.strip().lower()
    if not address or "@" not in address:
        raise AutoResponseSendValidationError("Unable to determine a valid reply recipient for this message.")
    return address


def _clean_original_text(value: object, *, limit: int) -> str:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()
    text = re.sub(r"\n{4,}", "\n\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _build_quoted_original(message_row) -> str:
    limit = max(0, int(config.AUTO_RESPONSE_SEND_QUOTED_ORIGINAL_CHARS))
    if limit <= 0:
        return ""

    original_text = _clean_original_text(
        _row_value(message_row, "body_preview") or _row_value(message_row, "snippet"),
        limit=limit,
    )
    if not original_text:
        return ""

    sender = " ".join(str(_row_value(message_row, "sender") or "the sender").split())
    received_at = " ".join(str(_row_value(message_row, "received_at") or "").split())
    heading = f"On {received_at}, {sender} wrote:" if received_at else f"{sender} wrote:"
    quoted_lines = "\n".join(f"> {line}" if line else ">" for line in original_text.splitlines())
    return f"{heading}\n{quoted_lines}"


def _quote_block(*, sender: str, received_at: str, body_text: str) -> str:
    heading = f"On {received_at}, {sender} wrote:" if received_at else f"{sender} wrote:"
    quoted_lines = "\n".join(f"> {line}" if line else ">" for line in body_text.splitlines())
    return f"{heading}\n{quoted_lines}"


def _build_thread_history_quote(history_messages: list[ThreadHistoryMessage]) -> str:
    limit = max(0, int(config.AUTO_RESPONSE_SEND_THREAD_HISTORY_CHARS))
    if limit <= 0 or not history_messages:
        return ""

    blocks: list[str] = []
    remaining = limit
    for message in history_messages:
        if remaining <= 0:
            break
        body_text = _clean_original_text(message.body_text, limit=remaining)
        if not body_text:
            continue
        block = _quote_block(
            sender=" ".join((message.sender or "the sender").split()),
            received_at=" ".join((message.received_at or "").split()),
            body_text=body_text,
        )
        blocks.append(block)
        remaining -= len(body_text)

    if not blocks:
        return ""
    return "Recent Gmail thread context:\n\n" + "\n\n".join(blocks)


def _build_outbound_body(
    draft_body: str,
    message_row,
    *,
    thread_history: list[ThreadHistoryMessage] | None = None,
) -> str:
    quoted_context = _build_thread_history_quote(thread_history or []) or _build_quoted_original(message_row)
    if not quoted_context:
        return draft_body
    return f"{draft_body.rstrip()}\n\n{quoted_context}"


def _context_source_for_history(history_messages: list[ThreadHistoryMessage]) -> str:
    return "gmail_thread_history" if history_messages else "stored_message_excerpt"


def _scopes_for_send(configured_scopes: list[str]) -> list[str]:
    if config.GMAIL_MODIFY_SCOPE in configured_scopes:
        return [config.GMAIL_MODIFY_SCOPE]
    if config.GMAIL_SEND_SCOPE in configured_scopes:
        return [config.GMAIL_SEND_SCOPE]
    raise AutoResponseSendNotConfiguredError(
        "This Gmail account is not connected with send access. Reconnect Gmail before sending a reply."
    )


def _fetch_gmail_connection_for_mail_account(conn, mail_account_id: int):
    return fetch_one(
        conn,
        """
        SELECT
            ma.provider,
            ma.id AS mail_account_id,
            pc.id AS provider_connection_id,
            pc.token_path,
            COALESCE(pc.scopes_json, '[]') AS scopes_json,
            pc.metadata_json,
            ma.external_account_email AS account_email
        FROM mail_accounts ma
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        WHERE ma.id = :mail_account_id
          AND ma.provider = 'gmail_readonly'
        LIMIT 1
        """,
        {"mail_account_id": mail_account_id},
    )


def _build_reply_message(
    *,
    account_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    headers: dict[str, str],
) -> EmailMessage:
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = account_email
    message["Subject"] = subject
    original_message_id = str(headers.get("Message-ID") or "").strip()
    if original_message_id:
        message["In-Reply-To"] = original_message_id
        references = str(headers.get("References") or "").strip()
        message["References"] = f"{references} {original_message_id}".strip()
    message.set_content(body_text)
    return message


def _send_gmail_reply(
    *,
    token_reference: GmailTokenReference,
    required_scopes: list[str],
    account_email: str,
    to_email: str,
    subject: str,
    body_text: str,
    gmail_thread_id: str | None,
    headers: dict[str, str],
) -> dict[str, Any]:
    service = build_service_from_token_reference(token_reference, scopes=required_scopes)
    message = _build_reply_message(
        account_email=account_email,
        to_email=to_email,
        subject=subject,
        body_text=body_text,
        headers=headers,
    )
    body = {
        "raw": base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8"),
    }
    if gmail_thread_id:
        body["threadId"] = gmail_thread_id
    return service.users().messages().send(userId="me", body=body).execute()


def _fetch_gmail_thread_history(
    *,
    token_reference: GmailTokenReference,
    required_scopes: list[str],
    gmail_thread_id: str,
    current_gmail_message_id: str,
) -> list[ThreadHistoryMessage]:
    max_messages = max(0, int(config.AUTO_RESPONSE_SEND_THREAD_HISTORY_MESSAGES))
    if max_messages <= 0:
        return []

    try:
        service = build_service_from_token_reference(token_reference, scopes=required_scopes)
        thread = (
            service.users()
            .threads()
            .get(userId="me", id=gmail_thread_id, format="full")
            .execute()
        )
    except Exception as error:
        logger.info("Gmail thread history fetch failed for thread %s: %s", gmail_thread_id, error)
        return []

    raw_messages = thread.get("messages", []) if isinstance(thread, dict) else []
    if not raw_messages:
        return []

    current_index = next(
        (
            index
            for index, message in enumerate(raw_messages)
            if str(message.get("id") or "") == current_gmail_message_id
        ),
        None,
    )
    eligible_messages = (
        raw_messages[: current_index + 1]
        if current_index is not None
        else raw_messages
    )

    history: list[ThreadHistoryMessage] = []
    for raw_message in eligible_messages[-max_messages:]:
        try:
            transformed = transform_gmail_message(raw_message)
        except Exception as error:
            logger.info("Skipping Gmail thread message during quote build: %s", error)
            continue
        body_text = str(transformed.get("body_preview") or transformed.get("snippet") or "").strip()
        if not body_text:
            continue
        history.append(
            ThreadHistoryMessage(
                gmail_message_id=str(transformed.get("gmail_message_id") or raw_message.get("id") or ""),
                sender=str(transformed.get("sender") or "the sender"),
                received_at=str(transformed.get("received_at") or ""),
                body_text=body_text,
            )
        )
    return history


def _send_result_from_row(row) -> AutoResponseSendResult:
    return AutoResponseSendResult(
        status=str(row["status"]),
        message_id=int(row["message_id"]),
        account_email=str(row["account_email"]),
        to_email=str(row["to_email"]),
        subject=str(row["subject"]),
        gmail_sent_message_id=row["gmail_sent_message_id"],
        gmail_thread_id=row["gmail_thread_id"],
        sent_at=row["sent_at"],
    )


def _validate_body_text(draft_body: str) -> str:
    body_text = draft_body.strip()
    if not body_text:
        raise AutoResponseSendValidationError("Reply body cannot be empty.")
    if len(body_text) > config.AUTO_RESPONSE_SEND_MAX_BODY_CHARS:
        raise AutoResponseSendValidationError(
            f"Reply body is too long. Keep it under {config.AUTO_RESPONSE_SEND_MAX_BODY_CHARS} characters."
        )
    return body_text


def _build_send_preview_from_message(
    message_id: int,
    *,
    user_id: int,
    draft_body: str,
    to_email_override: str | None = None,
    include_context: bool = True,
) -> AutoResponseSendPreview | None:
    body_text = _validate_body_text(draft_body)

    with get_connection() as conn:
        message_row = fetch_owned_message(conn, message_id, user_id)
        if message_row is None:
            return None

        gmail_message_id = str(_row_value(message_row, "provider_message_id") or _row_value(message_row, "gmail_message_id") or "")
        gmail_thread_id = str(_row_value(message_row, "provider_thread_id") or _row_value(message_row, "gmail_thread_id") or "")
        if not gmail_message_id or not gmail_thread_id:
            raise AutoResponseSendValidationError("This message is missing Gmail ids needed to preserve the thread.")

        account_email = str(message_row["account_email"]).strip().lower()
        to_email = _extract_recipient(message_row, to_email_override)
        subject = _normalize_subject(_row_value(message_row, "subject"))
        mail_account_id = _row_value(message_row, "mail_account_id")
        if mail_account_id is None:
            raise AutoResponseSendValidationError("This message is missing its owning Gmail account.")
        connection = _fetch_gmail_connection_for_mail_account(conn, int(mail_account_id))
        if connection is None:
            raise AutoResponseSendNotConfiguredError(
                "No Gmail OAuth connection is available for this account. Reconnect Gmail before sending a reply."
            )

        configured_scopes = json.loads(connection["scopes_json"] or "[]")
        required_scopes = _scopes_for_send(configured_scopes)
        token_reference = GmailTokenReference.from_row(connection)
        if (
            token_reference.token_path is None
            and token_reference.provider_connection_id is None
            and token_reference.token_json() is None
        ):
            raise AutoResponseSendNotConfiguredError(
                "No Gmail credentials are available for this account. Reconnect Gmail before sending a reply."
            )

        thread_history = (
            _fetch_gmail_thread_history(
                token_reference=token_reference,
                required_scopes=required_scopes,
                gmail_thread_id=gmail_thread_id,
                current_gmail_message_id=gmail_message_id,
            )
            if include_context
            else []
        )
        outbound_body_text = (
            _build_outbound_body(
                body_text,
                message_row,
                thread_history=thread_history,
            )
            if include_context
            else body_text
        )

    return AutoResponseSendPreview(
        message_id=message_id,
        account_email=account_email,
        to_email=to_email,
        subject=subject,
        body_text=outbound_body_text,
        gmail_thread_id=gmail_thread_id,
        context_source=_context_source_for_history(thread_history) if include_context else "none",
    )


def preview_auto_response_send(
    message_id: int,
    *,
    user_id: int,
    draft_body: str,
    to_email_override: str | None = None,
) -> AutoResponseSendPreview | None:
    return _build_send_preview_from_message(
        message_id,
        user_id=user_id,
        draft_body=draft_body,
        to_email_override=to_email_override,
        include_context=True,
    )


def send_auto_response(
    message_id: int,
    *,
    user_id: int,
    idempotency_key: str,
    draft_body: str,
    confirmed: bool,
    to_email_override: str | None = None,
    cc: list[str] | None = None,
    bcc: list[str] | None = None,
    include_context: bool = True,
) -> AutoResponseSendResult | None:
    if not confirmed:
        raise AutoResponseSendValidationError("Confirm the reply before sending.")

    body_text = _validate_body_text(draft_body)
    if not idempotency_key.strip():
        raise AutoResponseSendValidationError("A send idempotency key is required.")
    if cc or bcc:
        raise AutoResponseSendValidationError("CC and BCC are not supported for Auto-Respond sends yet.")

    with get_connection() as conn:
        existing = fetch_one(
            conn,
            """
            SELECT *
            FROM auto_response_sends
            WHERE user_id = :user_id AND idempotency_key = :idempotency_key
            """,
            {"user_id": user_id, "idempotency_key": idempotency_key},
        )
        if existing is not None:
            if int(existing["message_id"]) != int(message_id):
                raise AutoResponseSendValidationError(
                    "This send request key was already used for a different message."
                )
            return _send_result_from_row(existing)

        message_row = fetch_owned_message(conn, message_id, user_id)
        if message_row is None:
            return None

        gmail_message_id = str(_row_value(message_row, "provider_message_id") or _row_value(message_row, "gmail_message_id") or "")
        gmail_thread_id = str(_row_value(message_row, "provider_thread_id") or _row_value(message_row, "gmail_thread_id") or "")
        if not gmail_message_id or not gmail_thread_id:
            raise AutoResponseSendValidationError("This message is missing Gmail ids needed to preserve the thread.")

        account_email = str(message_row["account_email"]).strip().lower()
        to_email = _extract_recipient(message_row, to_email_override)
        subject = _normalize_subject(_row_value(message_row, "subject"))
        mail_account_id = _row_value(message_row, "mail_account_id")
        if mail_account_id is None:
            raise AutoResponseSendValidationError("This message is missing its owning Gmail account.")
        headers = _parse_headers(_row_value(message_row, "headers_json"))
        connection = _fetch_gmail_connection_for_mail_account(conn, int(mail_account_id))
        if connection is None:
            raise AutoResponseSendNotConfiguredError(
                "No Gmail OAuth connection is available for this account. Reconnect Gmail before sending a reply."
            )

        configured_scopes = json.loads(connection["scopes_json"] or "[]")
        required_scopes = _scopes_for_send(configured_scopes)
        token_reference = GmailTokenReference.from_row(connection)
        if (
            token_reference.token_path is None
            and token_reference.provider_connection_id is None
            and token_reference.token_json() is None
        ):
            raise AutoResponseSendNotConfiguredError(
                "No Gmail credentials are available for this account. Reconnect Gmail before sending a reply."
            )
        thread_history = _fetch_gmail_thread_history(
            token_reference=token_reference,
            required_scopes=required_scopes,
            gmail_thread_id=gmail_thread_id,
            current_gmail_message_id=gmail_message_id,
        ) if include_context else []
        outbound_body_text = _build_outbound_body(
            body_text,
            message_row,
            thread_history=thread_history,
        ) if include_context else body_text

        now = _now_iso()
        send_id = insert_and_return_id(
            conn,
            """
            INSERT INTO auto_response_sends (
                user_id, message_id, mail_account_id, idempotency_key, status, provider,
                account_email, to_email, cc_email, bcc_email, subject, body_text,
                gmail_thread_id, gmail_sent_message_id, gmail_response_json,
                error_message, created_at, sent_at
            ) VALUES (
                :user_id, :message_id, :mail_account_id, :idempotency_key, 'pending', 'gmail',
                :account_email, :to_email, NULL, NULL, :subject, :body_text,
                :gmail_thread_id, NULL, NULL, NULL, :created_at, NULL
            )
            """,
            {
                "user_id": user_id,
                "message_id": message_id,
                "mail_account_id": int(mail_account_id) if mail_account_id is not None else None,
                "idempotency_key": idempotency_key,
                "account_email": account_email,
                "to_email": to_email,
                "subject": subject,
                "body_text": outbound_body_text,
                "gmail_thread_id": gmail_thread_id,
                "created_at": now,
            },
        )

        try:
            response = _send_gmail_reply(
                token_reference=token_reference,
                required_scopes=required_scopes,
                account_email=account_email,
                to_email=to_email,
                subject=subject,
                body_text=outbound_body_text,
                gmail_thread_id=gmail_thread_id,
                headers=headers,
            )
        except GmailReadonlySyncError as error:
            execute_sql(
                conn,
                """
                UPDATE auto_response_sends
                SET status = 'failed', error_message = :error_message
                WHERE id = :send_id
                """,
                {"send_id": send_id, "error_message": str(error)},
            )
            raise AutoResponseSendNotConfiguredError(str(error)) from error
        except Exception as error:  # pragma: no cover - google client exceptions vary by transport
            logger.warning("Gmail auto-response send failed for message %s: %s", message_id, error)
            execute_sql(
                conn,
                """
                UPDATE auto_response_sends
                SET status = 'failed', error_message = :error_message
                WHERE id = :send_id
                """,
                {"send_id": send_id, "error_message": str(error)},
            )
            raise AutoResponseSendError("Gmail auto-response send failed.") from error

        sent_at = _now_iso()
        gmail_sent_message_id = response.get("id") if isinstance(response, dict) else None
        response_thread_id = response.get("threadId") if isinstance(response, dict) else None
        execute_sql(
            conn,
            """
            UPDATE auto_response_sends
            SET status = 'sent',
                gmail_sent_message_id = :gmail_sent_message_id,
                gmail_thread_id = :gmail_thread_id,
                gmail_response_json = :gmail_response_json,
                sent_at = :sent_at
            WHERE id = :send_id
            """,
            {
                "send_id": send_id,
                "gmail_sent_message_id": gmail_sent_message_id,
                "gmail_thread_id": response_thread_id or gmail_thread_id,
                "gmail_response_json": json.dumps(response, sort_keys=True) if isinstance(response, dict) else None,
                "sent_at": sent_at,
            },
        )

    return AutoResponseSendResult(
        status="sent",
        message_id=message_id,
        account_email=account_email,
        to_email=to_email,
        subject=subject,
        gmail_sent_message_id=gmail_sent_message_id,
        gmail_thread_id=response_thread_id or gmail_thread_id,
        sent_at=sent_at,
    )
