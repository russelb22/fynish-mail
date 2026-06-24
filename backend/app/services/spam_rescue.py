from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.data.mock_messages import get_mock_spam_messages
from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.services.action_logging import insert_action_log
from app.services.classifier import (
    classify_spam_rescue_candidate,
    extract_domain,
)
from app.services.provider_models import MailAccountRecord
from app.services.review_queue import (
    _enabled_mail_accounts,
    _history_counters,
    _load_rules,
)
from app.services.runtime_user import require_explicit_user_id_in_cloud


logger = logging.getLogger(__name__)

SPAM_RESCUE_ACTIONS = {"restore_to_inbox", "leave_in_spam"}
SPAM_RESCUE_ACTION_SOURCE = "spam_rescue"
STALE_SPAM_RESCUE_MESSAGE = "stale_spam_rescue_message"
MISSING_STATE_VERSION = "missing_state_version"
DUPLICATE_SPAM_RESCUE_MESSAGE = "duplicate_spam_rescue_message"
MESSAGE_NOT_FOUND = "message_not_found"
INVALID_SPAM_RESCUE_ACTION = "invalid_spam_rescue_action"
SPAM_RESCUE_ACTION_LABELS = {
    "restore_to_inbox": {"add": ["INBOX"], "remove": ["SPAM"]},
    "leave_in_spam": {"add": [], "remove": []},
}


@dataclass(frozen=True)
class SpamRescueCommitAction:
    account_email: str
    gmail_message_id: str
    action: str
    client_action_id: str | None = None
    expected_version: str | None = None

    @property
    def candidate_id(self) -> str:
        return f"{self.account_email}:{self.gmail_message_id}"


def _build_candidate_payload(account_email: str, message: dict, result) -> dict:
    return {
        "id": f"{account_email}:{message['gmail_message_id']}",
        "gmail_message_id": message["gmail_message_id"],
        "thread_id": message["gmail_thread_id"],
        "account_email": account_email,
        "sender": message["sender"],
        "sender_domain": extract_domain(message["sender"]),
        "reply_to": message["reply_to"],
        "subject": message["subject"],
        "received_at": message["received_at"],
        "snippet": message["snippet"],
        "body_preview": message["body_preview"],
        "has_attachments": bool(message["has_attachments"]),
        "source_label": "spam",
        "review_surface": "spam_rescue",
        "state_version": message["received_at"],
        "confidence": result.confidence,
        "rescue_reasons": result.reasons,
        "protection_reasons": result.protection_reasons,
        "matched_rule_ids": result.matched_rule_ids,
    }


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _reviewed_candidate_keys(conn, user_id: int | None = None) -> set[tuple[str, str]]:
    params: dict[str, object] = {}
    ownership_filter = ""
    if user_id is not None:
        ownership_filter = "AND ma.user_id = :user_id"
        params["user_id"] = user_id
    rows = fetch_all(
        conn,
        f"""
        SELECT l.account_email, l.gmail_message_id
        FROM actions_log l
        JOIN mail_accounts ma ON ma.id = l.mail_account_id
        WHERE l.action_source = :action_source
          {ownership_filter}
        """,
        {"action_source": SPAM_RESCUE_ACTION_SOURCE, **params},
    )
    return {
        (str(row["account_email"]), str(row["gmail_message_id"]))
        for row in rows
    }


def _find_account(accounts: Sequence[Mapping], account_email: str):
    for account in accounts:
        if account["external_account_email"] == account_email:
            return account
    return None


def _find_candidate(
    *,
    account,
    gmail_message_id: str,
    rules: list[dict],
    history_by_sender,
    history_by_domain,
) -> tuple[dict, object] | None:
    for message in get_mock_spam_messages(account["external_account_email"]):
        if message["gmail_message_id"] != gmail_message_id:
            continue
        result = classify_spam_rescue_candidate(
            message=message,
            rules=rules,
            history_by_sender=history_by_sender,
            history_by_domain=history_by_domain,
        )
        if not result.should_surface:
            return None
        return message, result
    return None


def _candidate_result(
    item: SpamRescueCommitAction,
    *,
    status: str,
    message: str,
    code: str | None = None,
    executed: bool = False,
    labels_added: list[str] | None = None,
    labels_removed: list[str] | None = None,
) -> dict:
    return {
        "client_action_id": item.client_action_id,
        "candidate_id": item.candidate_id,
        "account_email": item.account_email,
        "gmail_message_id": item.gmail_message_id,
        "action": item.action,
        "status": status,
        "code": code,
        "message": message,
        "executed": executed,
        "labels_added": labels_added or [],
        "labels_removed": labels_removed or [],
    }


def _request_hash(actions: Sequence[SpamRescueCommitAction]) -> str:
    payload = [
        {
            "client_action_id": item.client_action_id,
            "account_email": item.account_email,
            "gmail_message_id": item.gmail_message_id,
            "action": item.action,
            "expected_version": item.expected_version,
        }
        for item in actions
    ]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_idempotent_response(*, user_id: int, idempotency_key: str, request_hash: str) -> dict | None:
    with get_connection() as conn:
        row = fetch_one(
            conn,
            """
            SELECT request_hash, response_json
            FROM staged_commit_requests
            WHERE user_id = :user_id AND idempotency_key = :idempotency_key
            LIMIT 1
            """,
            {"user_id": user_id, "idempotency_key": idempotency_key},
        )
    if row is None:
        return None

    if row["request_hash"] != request_hash:
        logger.warning(
            "Spam Rescue commit idempotency key reused with different payload user_id=%s idempotency_key=%s",
            user_id,
            idempotency_key,
        )

    try:
        response = json.loads(row["response_json"])
    except (TypeError, json.JSONDecodeError):
        logger.exception(
            "Stored Spam Rescue idempotency response could not be decoded user_id=%s idempotency_key=%s",
            user_id,
            idempotency_key,
        )
        return None
    response["idempotent_replay"] = True
    return response


def _store_idempotent_response(
    *,
    user_id: int,
    idempotency_key: str,
    request_hash: str,
    response: dict,
) -> None:
    now = _now_iso()
    stored_response = {**response, "idempotent_replay": False}
    with get_connection() as conn:
        execute_sql(
            conn,
            """
            INSERT INTO staged_commit_requests (
                user_id, idempotency_key, request_hash, response_json, created_at, updated_at
            )
            VALUES (
                :user_id, :idempotency_key, :request_hash, :response_json, :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "response_json": json.dumps(stored_response, sort_keys=True),
                "created_at": now,
                "updated_at": now,
            },
        )


def _upsert_spam_rescue_message(conn, *, account, message: dict, result, action: str, now: str) -> dict:
    account_email = account["external_account_email"]
    mail_account_id = account["mail_account_id"]
    provider_labels_json = json.dumps(message["gmail_labels"])
    existing = fetch_one(
        conn,
        """
        SELECT *
        FROM messages
        WHERE account_email = :account_email AND gmail_message_id = :gmail_message_id
        LIMIT 1
        """,
        {
            "account_email": account_email,
            "gmail_message_id": message["gmail_message_id"],
        },
    )
    values = {
        "gmail_message_id": message["gmail_message_id"],
        "gmail_thread_id": message["gmail_thread_id"],
        "account_email": account_email,
        "mail_account_id": mail_account_id,
        "provider_message_id": message["gmail_message_id"],
        "provider_thread_id": message["gmail_thread_id"],
        "sender": message["sender"],
        "sender_domain": extract_domain(message["sender"]),
        "reply_to": message["reply_to"],
        "recipient_to": message["recipient_to"],
        "recipient_cc": message["recipient_cc"],
        "subject": message["subject"],
        "received_at": message["received_at"],
        "snippet": message["snippet"],
        "body_preview": message["body_preview"],
        "gmail_labels_json": provider_labels_json,
        "provider_labels_json": provider_labels_json,
        "headers_json": json.dumps(message["headers"]),
        "has_attachments": 1 if message["has_attachments"] else 0,
        "current_category": "spam_rescue",
        "confidence": result.confidence,
        "protected": 1 if result.protection_reasons else 0,
        "reviewed": 1,
        "queue_source": SPAM_RESCUE_ACTION_SOURCE,
        "queue_source_detail": json.dumps(
            {
                "review_surface": "spam_rescue",
                "selected_action": action,
                "rescue_reasons": result.reasons,
                "protection_reasons": result.protection_reasons,
                "matched_rule_ids": result.matched_rule_ids,
            },
            sort_keys=True,
        ),
        "created_at": now,
        "updated_at": now,
    }
    if existing is None:
        message_id = insert_and_return_id(
            conn,
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain, reply_to,
                recipient_to, recipient_cc, subject, received_at, snippet, body_preview,
                gmail_labels_json, provider_labels_json, headers_json, has_attachments,
                current_category, confidence, protected, reviewed, queue_source,
                queue_source_detail, created_at, updated_at
            ) VALUES (
                :gmail_message_id, :gmail_thread_id, :account_email, :mail_account_id,
                :provider_message_id, :provider_thread_id, :sender, :sender_domain, :reply_to,
                :recipient_to, :recipient_cc, :subject, :received_at, :snippet, :body_preview,
                :gmail_labels_json, :provider_labels_json, :headers_json, :has_attachments,
                :current_category, :confidence, :protected, :reviewed, :queue_source,
                :queue_source_detail, :created_at, :updated_at
            )
            """,
            values,
        )
    else:
        message_id = int(existing["id"])
        execute_sql(
            conn,
            """
            UPDATE messages
            SET mail_account_id = :mail_account_id,
                provider_message_id = :provider_message_id,
                provider_thread_id = :provider_thread_id,
                provider_labels_json = :provider_labels_json,
                current_category = :current_category,
                confidence = :confidence,
                protected = :protected,
                reviewed = :reviewed,
                queue_source = :queue_source,
                queue_source_detail = :queue_source_detail,
                updated_at = :updated_at
            WHERE id = :message_id
            """,
            {**values, "message_id": message_id},
        )

    return {**values, "id": message_id}


def get_spam_rescue_queue(user_id: int | None = None) -> dict:
    with get_connection() as conn:
        accounts = _enabled_mail_accounts(conn, user_id=user_id)
        rules = _load_rules(conn)
        if user_id is not None:
            rules = [rule for rule in rules if rule.get("user_id") == user_id]
        history_by_sender, history_by_domain = _history_counters(conn, user_id=user_id)
        reviewed_keys = _reviewed_candidate_keys(conn, user_id=user_id)

        result_accounts = []
        total_count = 0
        for account in accounts:
            account_record = MailAccountRecord.from_row(account)
            messages = []
            for message in get_mock_spam_messages(account_record.account_email):
                if (account_record.account_email, message["gmail_message_id"]) in reviewed_keys:
                    continue
                result = classify_spam_rescue_candidate(
                    message=message,
                    rules=rules,
                    history_by_sender=history_by_sender,
                    history_by_domain=history_by_domain,
                )
                if not result.should_surface:
                    continue
                messages.append(
                    _build_candidate_payload(
                        account_record.account_email,
                        message,
                        result,
                    )
                )

            messages.sort(
                key=lambda item: (item["confidence"], item["received_at"]),
                reverse=True,
            )
            total_count += len(messages)
            result_accounts.append(
                {
                    "account_email": account_record.account_email,
                    "last_sync_at": account_record.last_sync_at,
                    "count": len(messages),
                    "messages": messages,
                }
            )

    return {"accounts": result_accounts, "count": total_count}


def commit_spam_rescue_actions(
    actions: Sequence[SpamRescueCommitAction],
    *,
    idempotency_key: str,
    user_id: int | None = None,
) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="commit_spam_rescue_actions",
    )
    request_hash = _request_hash(actions)
    existing_response = _load_idempotent_response(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if existing_response is not None:
        return existing_response

    results = []
    seen_keys: set[tuple[str, str]] = set()
    with get_connection() as conn:
        accounts = _enabled_mail_accounts(conn, user_id=user_id)
        rules = _load_rules(conn)
        rules = [rule for rule in rules if rule.get("user_id") == user_id]
        history_by_sender, history_by_domain = _history_counters(conn, user_id=user_id)
        reviewed_keys = _reviewed_candidate_keys(conn, user_id=user_id)

        for item in actions:
            key = (item.account_email, item.gmail_message_id)
            if key in seen_keys:
                results.append(
                    _candidate_result(
                        item,
                        status="failed",
                        code=DUPLICATE_SPAM_RESCUE_MESSAGE,
                        message="This Spam Rescue candidate was included more than once.",
                    )
                )
                continue
            seen_keys.add(key)

            if item.action not in SPAM_RESCUE_ACTIONS:
                results.append(
                    _candidate_result(
                        item,
                        status="failed",
                        code=INVALID_SPAM_RESCUE_ACTION,
                        message="This Spam Rescue action is not supported.",
                    )
                )
                continue

            if key in reviewed_keys:
                results.append(
                    _candidate_result(
                        item,
                        status="stale",
                        code=STALE_SPAM_RESCUE_MESSAGE,
                        message="This Spam Rescue candidate was already reviewed.",
                    )
                )
                continue

            account = _find_account(accounts, item.account_email)
            if account is None:
                results.append(
                    _candidate_result(
                        item,
                        status="stale",
                        code=MESSAGE_NOT_FOUND,
                        message="This Spam Rescue account is no longer available.",
                    )
                )
                continue

            candidate = _find_candidate(
                account=account,
                gmail_message_id=item.gmail_message_id,
                rules=rules,
                history_by_sender=history_by_sender,
                history_by_domain=history_by_domain,
            )
            if candidate is None:
                results.append(
                    _candidate_result(
                        item,
                        status="stale",
                        code=MESSAGE_NOT_FOUND,
                        message="This message is no longer a Spam Rescue candidate.",
                    )
                )
                continue

            message, result = candidate
            current_version = message["received_at"]
            if not item.expected_version:
                results.append(
                    _candidate_result(
                        item,
                        status="stale",
                        code=MISSING_STATE_VERSION,
                        message="This Spam Rescue candidate needs to be refreshed before committing.",
                    )
                )
                continue
            if item.expected_version != current_version:
                results.append(
                    _candidate_result(
                        item,
                        status="stale",
                        code=STALE_SPAM_RESCUE_MESSAGE,
                        message="This Spam Rescue candidate changed after the queue loaded. Review it again.",
                    )
                )
                continue

            labels = SPAM_RESCUE_ACTION_LABELS[item.action]
            now = _now_iso()
            message_row = _upsert_spam_rescue_message(
                conn,
                account=account,
                message=message,
                result=result,
                action=item.action,
                now=now,
            )
            insert_action_log(
                conn,
                message_row=message_row,
                selected_action=item.action,
                recommended_action="spam_rescue",
                labels_added=list(labels["add"]),
                labels_removed=list(labels["remove"]),
                created_at=now,
                action_source=SPAM_RESCUE_ACTION_SOURCE,
            )
            reviewed_keys.add(key)
            results.append(
                _candidate_result(
                    item,
                    status="committed",
                    message="Committed.",
                    executed=True,
                    labels_added=list(labels["add"]),
                    labels_removed=list(labels["remove"]),
                )
            )

    committed_count = sum(1 for result in results if result["status"] == "committed")
    response = {
        "committed_count": committed_count,
        "failed_count": len(results) - committed_count,
        "results": results,
    }
    _store_idempotent_response(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response=response,
    )
    return response
