from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.core.config import GMAIL_MODIFY_SCOPE
from app.services.gmail_readonly import (
    GmailReadonlySyncError,
    fetch_unread_inbox_messages as fetch_unread_inbox_messages_from_path,
    build_service_from_token_reference,
    fetch_unread_inbox_messages_from_reference,
    fetch_unread_spam_messages_from_reference,
)
from app.services.gmail_token_store import GmailTokenReference


class MailProviderAdapter(Protocol):
    provider_name: str

    def list_unread_inbox_messages(self, token_reference: GmailTokenReference, max_results: int) -> list[dict]:
        ...

    def list_unread_spam_messages(
        self,
        token_reference: GmailTokenReference,
        max_results: int,
        *,
        newer_than_days: int | None = None,
    ) -> list[dict]:
        ...

    def modify_message_labels(
        self,
        *,
        token_reference: GmailTokenReference,
        provider_message_id: str,
        labels_to_add: list[str],
        labels_to_remove: list[str],
    ) -> list[str]:
        ...

    def requires_modify_scope(self) -> str | None:
        ...


def fetch_unread_inbox_messages(
    token_reference: GmailTokenReference | str,
    max_results: int,
) -> list[dict]:
    if isinstance(token_reference, GmailTokenReference):
        return fetch_unread_inbox_messages_from_reference(
            token_reference,
            max_results=max_results,
        )
    return fetch_unread_inbox_messages_from_path(token_reference, max_results=max_results)


def fetch_unread_spam_messages(
    token_reference: GmailTokenReference,
    max_results: int,
    *,
    newer_than_days: int | None = None,
) -> list[dict]:
    return fetch_unread_spam_messages_from_reference(
        token_reference,
        max_results=max_results,
        newer_than_days=newer_than_days,
    )


def _label_id_map(service) -> dict[str, str]:
    response = service.users().labels().list(userId="me").execute()
    labels = response.get("labels", [])
    return {label["name"]: label["id"] for label in labels}


def _ensure_user_label(service, label_name: str) -> str:
    labels_by_name = _label_id_map(service)
    if label_name in labels_by_name:
        return labels_by_name[label_name]

    created = (
        service.users()
        .labels()
        .create(
            userId="me",
            body={
                "name": label_name,
                "labelListVisibility": "labelShow",
                "messageListVisibility": "show",
            },
        )
        .execute()
    )
    return created["id"]


def _system_label_id(label_name: str) -> str:
    return label_name


def _resolve_label_ids(service, labels_to_add: list[str], labels_to_remove: list[str]) -> tuple[list[str], list[str]]:
    add_ids = []
    remove_ids = []

    for label in labels_to_add:
        if label.startswith("Fynish/"):
            add_ids.append(_ensure_user_label(service, label))
        else:
            add_ids.append(_system_label_id(label))

    for label in labels_to_remove:
        remove_ids.append(_system_label_id(label))

    return add_ids, remove_ids


@dataclass(frozen=True)
class GmailProviderAdapter:
    provider_name: str = "gmail_readonly"

    def list_unread_inbox_messages(self, token_reference: GmailTokenReference, max_results: int) -> list[dict]:
        return fetch_unread_inbox_messages(token_reference, max_results=max_results)

    def list_unread_spam_messages(
        self,
        token_reference: GmailTokenReference,
        max_results: int,
        *,
        newer_than_days: int | None = None,
    ) -> list[dict]:
        return fetch_unread_spam_messages(
            token_reference,
            max_results=max_results,
            newer_than_days=newer_than_days,
        )

    def modify_message_labels(
        self,
        *,
        token_reference: GmailTokenReference,
        provider_message_id: str,
        labels_to_add: list[str],
        labels_to_remove: list[str],
    ) -> list[str]:
        try:
            service = build_service_from_token_reference(
                token_reference,
                scopes=[GMAIL_MODIFY_SCOPE],
            )
            add_label_ids, remove_label_ids = _resolve_label_ids(
                service,
                labels_to_add,
                labels_to_remove,
            )
            response = (
                service.users()
                .messages()
                .modify(
                    userId="me",
                    id=provider_message_id,
                    body={
                        "addLabelIds": add_label_ids,
                        "removeLabelIds": remove_label_ids,
                    },
                )
                .execute()
            )
            return response.get("labelIds", [])
        except Exception as error:
            raise GmailReadonlySyncError(
                f"Gmail modify operation failed: {error}"
            ) from error

    def requires_modify_scope(self) -> str | None:
        return GMAIL_MODIFY_SCOPE


_ADAPTERS: dict[str, MailProviderAdapter] = {
    "gmail_readonly": GmailProviderAdapter(),
}


def get_mail_provider_adapter(provider: str) -> MailProviderAdapter | None:
    return _ADAPTERS.get(provider)
