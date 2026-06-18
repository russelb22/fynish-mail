from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from email.message import EmailMessage
from urllib import error, request

from app.core.config import GMAIL_SENDER_EMAIL, MAIL_API_KEY, MAIL_FROM_EMAIL, MAIL_PROVIDER
from app.services.digest_sender import (
    DigestSenderAuthError,
    DigestSenderNotConfiguredError,
    build_gmail_digest_sender_service,
)


class MailerNotConfiguredError(RuntimeError):
    pass


class MailDeliveryError(RuntimeError):
    pass


@dataclass(frozen=True)
class MailDeliveryResult:
    provider: str
    to_email: str
    subject: str
    message_id: str | None = None


def _require_mail_provider() -> str:
    provider = MAIL_PROVIDER.strip().lower()
    if provider in {"", "disabled", "none"}:
        raise MailerNotConfiguredError("Outbound mail delivery is not configured.")
    return provider


def _require_mail_config() -> tuple[str, str, str]:
    provider = _require_mail_provider()
    if not MAIL_FROM_EMAIL:
        raise MailerNotConfiguredError("FYNISH_MAIL_FROM_EMAIL is required for outbound mail delivery.")
    if not MAIL_API_KEY:
        raise MailerNotConfiguredError("FYNISH_MAIL_API_KEY is required for outbound mail delivery.")
    return provider, MAIL_FROM_EMAIL, MAIL_API_KEY


def _send_postmark(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    from_email: str,
    api_key: str,
    html_body: str | None = None,
) -> MailDeliveryResult:
    message_payload = {
        "From": from_email,
        "To": to_email,
        "Subject": subject,
        "TextBody": text_body,
        "MessageStream": "outbound",
    }
    if html_body:
        message_payload["HtmlBody"] = html_body
    payload = json.dumps(
        message_payload
    ).encode("utf-8")
    req = request.Request(
        "https://api.postmarkapp.com/email",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "X-Postmark-Server-Token": api_key,
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            response_body = response.read().decode("utf-8")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MailDeliveryError(f"Postmark delivery failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise MailDeliveryError(f"Postmark delivery failed: {exc.reason}") from exc

    parsed = json.loads(response_body or "{}")
    return MailDeliveryResult(
        provider="postmark",
        to_email=to_email,
        subject=subject,
        message_id=parsed.get("MessageID"),
    )


def _send_sendgrid(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    from_email: str,
    api_key: str,
    html_body: str | None = None,
) -> MailDeliveryResult:
    content = [{"type": "text/plain", "value": text_body}]
    if html_body:
        content.append({"type": "text/html", "value": html_body})
    payload = json.dumps(
        {
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email},
            "subject": subject,
            "content": content,
        }
    ).encode("utf-8")
    req = request.Request(
        "https://api.sendgrid.com/v3/mail/send",
        data=payload,
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=20) as response:
            message_id = response.headers.get("X-Message-Id")
    except error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise MailDeliveryError(f"SendGrid delivery failed: {exc.code} {detail}") from exc
    except error.URLError as exc:
        raise MailDeliveryError(f"SendGrid delivery failed: {exc.reason}") from exc

    return MailDeliveryResult(
        provider="sendgrid",
        to_email=to_email,
        subject=subject,
        message_id=message_id,
    )


def _send_gmail(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> MailDeliveryResult:
    sender_email = GMAIL_SENDER_EMAIL.strip().lower()
    try:
        service = build_gmail_digest_sender_service(sender_email or None)
    except (DigestSenderNotConfiguredError, DigestSenderAuthError) as error:
        raise MailerNotConfiguredError(str(error)) from error

    effective_sender = sender_email or "me"
    message = EmailMessage()
    message["To"] = to_email
    message["From"] = effective_sender
    message["Subject"] = subject
    message.set_content(text_body)
    if html_body:
        message.add_alternative(html_body, subtype="html")

    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode("utf-8")
    try:
        response = (
            service.users()
            .messages()
            .send(userId="me", body={"raw": raw_message})
            .execute()
        )
    except Exception as error:  # pragma: no cover - google client exceptions vary by transport
        raise MailDeliveryError(f"Gmail delivery failed: {error}") from error

    return MailDeliveryResult(
        provider="gmail",
        to_email=to_email,
        subject=subject,
        message_id=response.get("id") if isinstance(response, dict) else None,
    )


def send_email(
    *,
    to_email: str,
    subject: str,
    text_body: str,
    html_body: str | None = None,
) -> MailDeliveryResult:
    provider = _require_mail_provider()
    if provider == "gmail":
        return _send_gmail(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            html_body=html_body,
        )
    provider, from_email, api_key = _require_mail_config()
    if provider == "postmark":
        return _send_postmark(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            from_email=from_email,
            api_key=api_key,
            html_body=html_body,
        )
    if provider == "sendgrid":
        return _send_sendgrid(
            to_email=to_email,
            subject=subject,
            text_body=text_body,
            from_email=from_email,
            api_key=api_key,
            html_body=html_body,
        )
    raise MailerNotConfiguredError(f"Unsupported mail provider: {provider}")


def send_plain_text_email(*, to_email: str, subject: str, body: str) -> MailDeliveryResult:
    return send_email(to_email=to_email, subject=subject, text_body=body)
