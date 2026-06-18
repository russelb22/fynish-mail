from __future__ import annotations

import json
from dataclasses import dataclass


def _row_has_key(row, key: str) -> bool:
    if row is None:
        return False
    try:
        return key in row.keys()
    except AttributeError:
        try:
            row[key]
            return True
        except Exception:
            return False


def row_value(row, *names: str, default=None):
    for name in names:
        if _row_has_key(row, name):
            value = row[name]
            if value is not None:
                return value
    return default


def parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    return parsed if isinstance(parsed, list) else []


def parse_json_object(value: str | None) -> dict:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def mail_account_id_from_row(row) -> int | None:
    value = row_value(row, "mail_account_id", default=None)
    return int(value) if value is not None else None


def account_email_from_row(row) -> str:
    return str(
        row_value(
            row,
            "normalized_account_email",
            "account_email",
            "external_account_email",
            "email_address",
            default="",
        )
    )


def provider_message_id_from_row(row) -> str:
    return str(row_value(row, "provider_message_id", "gmail_message_id", default=""))


def provider_thread_id_from_row(row) -> str:
    return str(row_value(row, "provider_thread_id", "gmail_thread_id", default=""))


def provider_labels_from_row(row) -> list[str]:
    return parse_json_list(
        row_value(row, "provider_labels_json", "gmail_labels_json", default="[]")
    )


@dataclass(frozen=True)
class MailAccountRecord:
    account_email: str
    mail_account_id: int | None
    user_id: int | None
    provider: str
    display_name: str
    enabled: bool
    status: str
    last_sync_at: str | None
    oauth_scopes: list[str]
    auth_status: str
    auth_status_label: str
    auth_status_reason: str | None

    @classmethod
    def from_row(cls, row) -> "MailAccountRecord":
        account_email = account_email_from_row(row)
        enabled = bool(row_value(row, "enabled", default=1))
        provider = str(row_value(row, "provider", default="unknown"))
        metadata = parse_json_object(row_value(row, "metadata_json", default="{}"))
        oauth_scopes = parse_json_list(row_value(row, "scopes_json", default="[]"))
        auth_status = "not_applicable"
        auth_status_label = "Not applicable"
        auth_status_reason = None
        if provider == "gmail_readonly":
            if metadata.get("reconnect_required"):
                auth_status = "reconnect_required"
                auth_status_label = "Reconnect required"
                auth_status_reason = str(
                    metadata.get("last_sync_error")
                    or "Stored Gmail credentials need to be refreshed."
                )
            else:
                auth_status = "connected"
                auth_status_label = "Connected"
        display_name = str(
            row_value(
                row,
                "mail_account_display_name",
                "display_name",
                "external_account_email",
                "email_address",
                default=account_email,
            )
        )
        user_id = row_value(row, "user_id", default=None)
        return cls(
            account_email=account_email,
            mail_account_id=mail_account_id_from_row(row),
            user_id=int(user_id) if user_id is not None else None,
            provider=provider,
            display_name=display_name,
            enabled=enabled,
            status=str(
                row_value(
                    row,
                    "mail_account_status",
                    "status",
                    default="active" if enabled else "disabled",
                )
            ),
            last_sync_at=row_value(row, "last_sync_at", "mail_account_last_sync_at"),
            oauth_scopes=oauth_scopes,
            auth_status=auth_status,
            auth_status_label=auth_status_label,
            auth_status_reason=auth_status_reason,
        )

    def to_legacy_payload(self, legacy_id: int | None = None) -> dict:
        payload = {
            "email_address": self.account_email,
            "enabled": self.enabled,
            "provider": self.provider,
            "last_sync_at": self.last_sync_at,
            "oauth_scopes": self.oauth_scopes,
            "auth_status": self.auth_status,
            "auth_status_label": self.auth_status_label,
            "auth_status_reason": self.auth_status_reason,
        }
        if legacy_id is not None:
            payload["id"] = legacy_id
        return payload


@dataclass(frozen=True)
class ProviderMessageRecord:
    local_message_id: int
    account_email: str
    mail_account_id: int | None
    provider: str
    provider_message_id: str
    provider_thread_id: str
    provider_labels: list[str]
    sender: str | None
    sender_domain: str | None
    reply_to: str | None
    subject: str | None
    snippet: str | None
    body_preview: str | None
    received_at: str | None
    has_attachments: bool
    category: str | None
    confidence: float | None
    protected: bool

    @classmethod
    def from_row(cls, row) -> "ProviderMessageRecord":
        return cls(
            local_message_id=int(row_value(row, "id", default=0)),
            account_email=account_email_from_row(row),
            mail_account_id=mail_account_id_from_row(row),
            provider=str(row_value(row, "provider", default="unknown")),
            provider_message_id=provider_message_id_from_row(row),
            provider_thread_id=provider_thread_id_from_row(row),
            provider_labels=provider_labels_from_row(row),
            sender=row_value(row, "sender"),
            sender_domain=row_value(row, "sender_domain"),
            reply_to=row_value(row, "reply_to"),
            subject=row_value(row, "subject"),
            snippet=row_value(row, "snippet"),
            body_preview=row_value(row, "body_preview"),
            received_at=row_value(row, "received_at"),
            has_attachments=bool(row_value(row, "has_attachments", default=0)),
            category=row_value(row, "current_category"),
            confidence=row_value(row, "confidence"),
            protected=bool(row_value(row, "protected", default=0)),
        )
