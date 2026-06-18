from __future__ import annotations

import json
from datetime import datetime, timezone

from app.core.config import ENABLE_GMAIL_WRITES
from app.db.runtime import execute_sql, fetch_one, get_connection
from app.services.action_logging import insert_action_log
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.gmail_token_store import GmailTokenReference
from app.services.mail_provider_adapter import get_mail_provider_adapter
from app.services.ownership import fetch_owned_message
from app.services.runtime_accounts import (
    fetch_runtime_account_connection,
    fetch_runtime_message_with_provider,
)
from app.services.runtime_user import require_explicit_user_id_in_cloud


RECOVERY_LABELS_TO_REMOVE = [
    "Fynish/Bulk Mail",
    "Fynish/Junk Review",
    "Fynish/Trash",
    "Fynish/Needs Review",
]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connection_row_for_account(conn, account_email: str):
    return fetch_runtime_account_connection(conn, account_email, provider="gmail_readonly")


def _recover_gmail_message(conn, message_row: dict) -> tuple[list[str], list[str]]:
    connection = _connection_row_for_account(conn, message_row["account_email"])
    if connection is None or connection["provider"] != "gmail_readonly":
        raise GmailReadonlySyncError("No Gmail connection is available for this message")
    if not connection["token_path"]:
        raise GmailReadonlySyncError("No Gmail token is available for this message")
    if not ENABLE_GMAIL_WRITES:
        raise GmailReadonlySyncError("Live Gmail writes are disabled unless explicitly enabled")

    adapter = get_mail_provider_adapter(connection["provider"])
    if adapter is None:
        raise GmailReadonlySyncError("No provider adapter is available for this account")

    current_labels = json.loads(
        message_row.get("provider_labels_json")
        or message_row.get("gmail_labels_json")
        or "[]"
    )
    labels_to_add = ["INBOX"] if "INBOX" not in current_labels else []
    labels_to_remove = [label for label in RECOVERY_LABELS_TO_REMOVE if label in current_labels]

    if labels_to_add or labels_to_remove:
        response_label_ids = adapter.modify_message_labels(
            token_reference=GmailTokenReference.from_row(connection),
            provider_message_id=message_row["provider_message_id"] or message_row["gmail_message_id"],
            labels_to_add=labels_to_add,
            labels_to_remove=labels_to_remove,
        )
    else:
        # If the message is already back in Inbox with no Fynish routing labels,
        # Gmail has nothing to change and rejects an empty modify call.
        response_label_ids = current_labels

    labels_json = json.dumps(response_label_ids)
    execute_sql(
        conn,
        """
        UPDATE messages
        SET provider_labels_json = :provider_labels_json,
            gmail_labels_json = :gmail_labels_json,
            updated_at = :updated_at
        WHERE id = :message_id
        """,
        {
            "provider_labels_json": labels_json,
            "gmail_labels_json": labels_json,
            "updated_at": _now_iso(),
            "message_id": message_row["id"],
        },
    )
    return labels_to_add, labels_to_remove


def recover_processed_message(message_id: int, conn=None, user_id: int | None = None) -> dict | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="recover_processed_message",
    )
    now = _now_iso()
    if conn is None:
        with get_connection() as owned_conn:
            return recover_processed_message(message_id, conn=owned_conn, user_id=user_id)

    if user_id is not None and fetch_owned_message(conn, message_id, user_id) is None:
        return None

    message_row = fetch_runtime_message_with_provider(conn, message_id)
    if message_row is None:
        return None

    labels_added: list[str] = []
    labels_removed: list[str] = []
    if message_row["provider"] == "gmail_readonly":
        labels_added, labels_removed = _recover_gmail_message(conn, dict(message_row))

    insert_action_log(
        conn,
        message_row=message_row,
        selected_action="recover",
        recommended_action=message_row["current_category"],
        labels_added=labels_added,
        labels_removed=labels_removed,
        created_at=now,
        action_source="recovery",
    )
    execute_sql(
        conn,
        """
        UPDATE messages
        SET reviewed = 0,
            current_category = 'needs_review',
            recovery_pending = 1,
            updated_at = :updated_at
        WHERE id = :message_id
        """,
        {
            "updated_at": now,
            "message_id": message_id,
        },
    )
    return {
        "message_id": message_id,
        "selected_action": "recover",
        "labels_added": labels_added,
        "labels_removed": labels_removed,
        "current_category": "needs_review",
        "recovery_pending": True,
    }
