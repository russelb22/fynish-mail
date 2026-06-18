from __future__ import annotations

import base64
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any

from google.auth.transport.requests import Request
from google.auth.exceptions import RefreshError
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.core.config import (
    BODY_PREVIEW_LIMIT,
    GMAIL_MODIFY_SCOPE,
    GMAIL_READONLY_SCOPE,
    GMAIL_TOKEN_STORAGE_MODE,
    GOOGLE_CLIENT_SECRETS_PATH,
    GOOGLE_TOKEN_DIR,
)
from app.services.gmail_token_store import (
    GmailTokenReference,
    load_connection_token_json,
    store_connection_token_json,
)


SCOPES = [GMAIL_READONLY_SCOPE]
MODIFY_SCOPES = [GMAIL_MODIFY_SCOPE]
INTERESTING_HEADERS = (
    "From",
    "Reply-To",
    "To",
    "Cc",
    "Subject",
    "Date",
    "Message-ID",
    "List-Unsubscribe",
    "List-ID",
    "Precedence",
    "Auto-Submitted",
    "Authentication-Results",
)


class GmailReadonlyNotConfiguredError(RuntimeError):
    pass


class GmailReadonlySyncError(RuntimeError):
    pass


@dataclass
class GmailConnection:
    email_address: str
    token_path: str
    scopes: list[str]


def oauth_client_configured() -> bool:
    return GOOGLE_CLIENT_SECRETS_PATH.exists()


def _ensure_google_credentials_available() -> None:
    if not oauth_client_configured():
        raise GmailReadonlyNotConfiguredError(
            f"Google OAuth client file not found at {GOOGLE_CLIENT_SECRETS_PATH}"
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_email_filename(email_address: str) -> str:
    return re.sub(r"[^a-zA-Z0-9._-]+", "_", email_address.strip().lower())


def _token_path_for_email(email_address: str) -> Path:
    GOOGLE_TOKEN_DIR.mkdir(parents=True, exist_ok=True)
    return GOOGLE_TOKEN_DIR / f"{_safe_email_filename(email_address)}.json"


def _write_credentials(token_path: Path, credentials: Credentials) -> None:
    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(credentials.to_json())


def _credentials_from_token_json(token_json: str, scopes: list[str] | None = None) -> Credentials:
    payload = json.loads(token_json)
    return Credentials.from_authorized_user_info(payload, scopes)


def _load_credentials(token_path: str, scopes: list[str] | None = None) -> Credentials:
    # Preserve whatever scopes were actually granted to the stored token unless a caller
    # explicitly requires a narrower or broader scope set for validation.
    creds = Credentials.from_authorized_user_file(token_path, scopes)
    if scopes and not creds.has_scopes(scopes):
        raise GmailReadonlySyncError(
            "Stored Gmail credentials do not include the required scopes. Reconnect the account with broader access."
        )
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _write_credentials(Path(token_path), creds)
        else:
            raise GmailReadonlySyncError(
                "Stored Gmail credentials are no longer valid. Reconnect the account."
            )
    return creds


def _load_credentials_from_reference(
    reference: GmailTokenReference,
    scopes: list[str] | None = None,
) -> Credentials:
    if GMAIL_TOKEN_STORAGE_MODE not in {"auto", "file", "database"}:
        raise GmailReadonlySyncError(
            f"Unsupported Gmail token storage mode: {GMAIL_TOKEN_STORAGE_MODE}"
        )

    token_json = load_connection_token_json(reference)
    use_database = GMAIL_TOKEN_STORAGE_MODE in {"auto", "database"}
    use_file = GMAIL_TOKEN_STORAGE_MODE in {"auto", "file"}

    if use_database and token_json:
        creds = _credentials_from_token_json(token_json, scopes)
        if scopes and not creds.has_scopes(scopes):
            raise GmailReadonlySyncError(
                "Stored Gmail credentials do not include the required scopes. Reconnect the account with broader access."
            )
        if not creds.valid:
            if creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                except RefreshError as error:
                    raise GmailReadonlySyncError(
                        "Stored Gmail credentials were expired or revoked. Reconnect the account."
                    ) from error
                if reference.provider_connection_id is None:
                    raise GmailReadonlySyncError(
                        "DB-backed Gmail credentials refreshed, but no provider connection id was available to persist them."
                    )
                store_connection_token_json(
                    reference.provider_connection_id,
                    creds.to_json(),
                    token_source="database_refreshed",
                )
            else:
                raise GmailReadonlySyncError(
                    "Stored Gmail credentials are no longer valid. Reconnect the account."
                )
        return creds

    if GMAIL_TOKEN_STORAGE_MODE == "database":
        raise GmailReadonlySyncError(
            "Gmail token storage mode is 'database', but no DB-backed token blob is available for this connection."
        )

    if use_file and reference.token_path:
        return _load_credentials(reference.token_path, scopes=scopes)

    raise GmailReadonlySyncError(
        "No Gmail credentials are available for this connection. Reconnect the account."
    )


def build_service_from_token_path(token_path: str, scopes: list[str] | None = None):
    credentials = _load_credentials(token_path, scopes=scopes)
    return build("gmail", "v1", credentials=credentials)


def build_service_from_token_reference(
    reference: GmailTokenReference,
    scopes: list[str] | None = None,
):
    credentials = _load_credentials_from_reference(reference, scopes=scopes)
    return build("gmail", "v1", credentials=credentials)


def start_oauth_connection(scopes: list[str] | None = None) -> GmailConnection:
    _ensure_google_credentials_available()
    requested_scopes = scopes or SCOPES

    flow = InstalledAppFlow.from_client_secrets_file(
        str(GOOGLE_CLIENT_SECRETS_PATH), requested_scopes
    )
    credentials = flow.run_local_server(port=0)
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    email_address = profile["emailAddress"].strip().lower()
    token_path = _token_path_for_email(email_address)
    _write_credentials(token_path, credentials)
    return GmailConnection(
        email_address=email_address,
        token_path=str(token_path),
        scopes=list(credentials.scopes or requested_scopes),
    )


def list_unread_inbox_message_ids(service, max_results: int) -> list[dict[str, str]]:
    response = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX", "UNREAD"], maxResults=max_results)
        .execute()
    )
    return response.get("messages", [])


def fetch_message(service, message_id: str) -> dict[str, Any]:
    return (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )


def _decode_body_data(value: str | None) -> str:
    if not value:
        return ""
    padding = "=" * (-len(value) % 4)
    decoded = base64.urlsafe_b64decode((value + padding).encode("utf-8"))
    return decoded.decode("utf-8", errors="replace")


def _html_to_text(html: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", html)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n", text)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"(?i)<https?://[^>\s]+>", "", text)
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(
        line for line in text.splitlines() if not re.match(r"^\s*(?:https?://|www\.)\S+\s*$", line)
    )
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _collect_payload_content(
    payload: dict[str, Any],
    plain_text_parts: list[str],
    html_parts: list[str],
) -> bool:
    has_attachments = False

    mime_type = payload.get("mimeType", "")
    filename = payload.get("filename", "")
    body = payload.get("body", {}) or {}
    data = body.get("data")
    attachment_id = body.get("attachmentId")

    if filename or attachment_id:
        has_attachments = True

    if mime_type == "text/plain" and data:
        plain_text_parts.append(_decode_body_data(data))
    elif mime_type == "text/html" and data:
        html_parts.append(_decode_body_data(data))

    for part in payload.get("parts", []) or []:
        if _collect_payload_content(part, plain_text_parts, html_parts):
            has_attachments = True

    return has_attachments


def extract_body_preview(payload: dict[str, Any]) -> tuple[str, bool]:
    plain_text_parts: list[str] = []
    html_parts: list[str] = []
    has_attachments = _collect_payload_content(payload, plain_text_parts, html_parts)

    if plain_text_parts:
        text = "\n\n".join(part.strip() for part in plain_text_parts if part.strip())
    elif html_parts:
        converted_html = [_html_to_text(part) for part in html_parts]
        text = "\n\n".join(part for part in converted_html if part)
    else:
        text = ""

    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:BODY_PREVIEW_LIMIT], has_attachments


def extract_headers_map(payload: dict[str, Any]) -> dict[str, str]:
    values = {}
    for header in payload.get("headers", []) or []:
        name = header.get("name", "")
        if name in INTERESTING_HEADERS:
            values[name] = header.get("value", "")
    return values


def _received_at_from_message(message: dict[str, Any], headers: dict[str, str]) -> str:
    internal_ms = message.get("internalDate")
    if internal_ms:
        try:
            return datetime.fromtimestamp(
                int(internal_ms) / 1000, tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError):
            pass
    return headers.get("Date", "")


def transform_gmail_message(message: dict[str, Any]) -> dict[str, Any]:
    payload = message.get("payload", {}) or {}
    headers = extract_headers_map(payload)
    body_preview, has_attachments = extract_body_preview(payload)

    return {
        "gmail_message_id": message["id"],
        "gmail_thread_id": message.get("threadId", ""),
        "sender": headers.get("From", ""),
        "reply_to": headers.get("Reply-To", ""),
        "recipient_to": headers.get("To", ""),
        "recipient_cc": headers.get("Cc", ""),
        "subject": headers.get("Subject", "(No subject)"),
        "received_at": _received_at_from_message(message, headers),
        "snippet": (message.get("snippet") or "")[:BODY_PREVIEW_LIMIT],
        "body_preview": body_preview,
        "gmail_labels": message.get("labelIds", []),
        "headers": headers,
        "has_attachments": int(bool(has_attachments)),
    }


def fetch_unread_inbox_messages(token_path: str, max_results: int) -> list[dict[str, Any]]:
    try:
        service = build_service_from_token_path(token_path)
        message_refs = list_unread_inbox_message_ids(service, max_results=max_results)
        messages = []
        for message_ref in message_refs:
            raw = fetch_message(service, message_ref["id"])
            messages.append(transform_gmail_message(raw))
        return messages
    except HttpError as error:
        raise GmailReadonlySyncError(f"Gmail read-only sync failed: {error}") from error


def fetch_unread_inbox_messages_from_reference(
    reference: GmailTokenReference,
    max_results: int,
) -> list[dict[str, Any]]:
    try:
        service = build_service_from_token_reference(reference)
        message_refs = list_unread_inbox_message_ids(service, max_results=max_results)
        messages = []
        for message_ref in message_refs:
            raw = fetch_message(service, message_ref["id"])
            messages.append(transform_gmail_message(raw))
        return messages
    except HttpError as error:
        raise GmailReadonlySyncError(f"Gmail read-only sync failed: {error}") from error
