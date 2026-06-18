from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.config import GMAIL_MODIFY_SCOPE
from app.db.runtime import execute_sql, fetch_one, get_connection
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.gmail_write_executor import execute_message_action, log_executed_message_action
from app.services.review_queue import (
    UnsafeMessageActionError,
    apply_message_action,
    reclassify_pending_messages,
)
from app.services.rules import (
    RuleAccountUnavailableError,
    RuleSourceMessageUnavailableError,
    create_rule,
)
from app.services.runtime_user import require_explicit_user_id_in_cloud


logger = logging.getLogger(__name__)

STALE_MESSAGE = "stale_message"
DUPLICATE_STAGED_MESSAGE = "duplicate_staged_message"
GMAIL_RECONNECT_REQUIRED = "gmail_reconnect_required"
UNSAFE_MESSAGE_ACTION = "unsafe_message_action"
MESSAGE_ACTION_FAILED = "message_action_failed"
INTERNAL_ERROR = "internal_error"
RULE_CREATE_FAILED = "rule_create_failed"
MISSING_STATE_VERSION = "missing_state_version"


@dataclass(frozen=True)
class StagedCommitRule:
    scope: str
    rule_type: str
    pattern: str
    action: str
    account_email: str | None = None


@dataclass(frozen=True)
class StagedCommitAction:
    message_id: int
    action: str
    client_action_id: str | None = None
    expected_version: str | None = None
    rule: StagedCommitRule | None = None


def _result(
    item: StagedCommitAction,
    *,
    status: str,
    message: str,
    code: str | None = None,
    executed: bool = False,
    labels_added: list[str] | None = None,
    labels_removed: list[str] | None = None,
    rule_id: int | None = None,
    reclassified_messages: int = 0,
) -> dict:
    return {
        "client_action_id": item.client_action_id,
        "message_id": item.message_id,
        "action": item.action,
        "status": status,
        "code": code,
        "message": message,
        "executed": executed,
        "labels_added": labels_added or [],
        "labels_removed": labels_removed or [],
        "rule_id": rule_id,
        "reclassified_messages": reclassified_messages,
    }


def _message_row(conn, message_id: int, user_id: int | None):
    params: dict[str, object] = {"message_id": message_id}
    user_filter = ""
    if user_id is not None:
        user_filter = """
          AND (
                ma.user_id = :user_id
             OR (ma.id IS NULL AND legacy_ma.user_id = :user_id)
          )
        """
        params["user_id"] = user_id
    return fetch_one(
        conn,
        f"""
        SELECT
            m.id,
            m.reviewed,
            m.updated_at,
            m.account_email,
            m.mail_account_id,
            COALESCE(ma.provider, a.provider, 'unknown') AS provider,
            COALESCE(ma.external_account_email, m.account_email) AS normalized_account_email,
            pc.scopes_json,
            legacy_g.scopes_json AS legacy_scopes_json,
            c.created_at AS classification_created_at
        FROM messages m
        LEFT JOIN mail_accounts ma ON ma.id = m.mail_account_id
        LEFT JOIN mail_accounts legacy_ma
          ON legacy_ma.external_account_email = m.account_email
         AND m.mail_account_id IS NULL
        LEFT JOIN accounts a
          ON a.email_address = m.account_email
         AND (ma.id IS NULL OR a.provider = ma.provider)
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        LEFT JOIN gmail_account_connections legacy_g ON legacy_g.account_id = a.id
        LEFT JOIN classification_results c
          ON c.id = (
                SELECT latest_c.id
                FROM classification_results latest_c
                WHERE latest_c.message_id = m.id
                ORDER BY latest_c.id DESC
                LIMIT 1
             )
        WHERE m.id = :message_id
        {user_filter}
        LIMIT 1
        """,
        params,
    )


def _state_version(row) -> str | None:
    if row is None:
        return None
    return row["updated_at"] or row["classification_created_at"]


def _has_modify_scope(row) -> bool:
    if row is None or row["provider"] != "gmail_readonly":
        return False
    raw_scopes = row["scopes_json"] or row["legacy_scopes_json"] or "[]"
    try:
        scopes = json.loads(raw_scopes)
    except json.JSONDecodeError:
        return False
    return GMAIL_MODIFY_SCOPE in scopes


def _code_for_gmail_error(error: GmailReadonlySyncError) -> str:
    message = str(error).lower()
    if "credential" in message or "token" in message or "reconnect" in message:
        return GMAIL_RECONNECT_REQUIRED
    return MESSAGE_ACTION_FAILED


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _stale_result_for_item(item: StagedCommitAction, *, user_id: int | None) -> dict | None:
    with get_connection() as conn:
        row = _message_row(conn, item.message_id, user_id)
        if row is None or bool(row["reviewed"]):
            return _result(
                item,
                status="stale",
                code=STALE_MESSAGE,
                message="This message was already processed. The queue has been refreshed.",
            )

        current_version = _state_version(row)
        if not item.expected_version:
            return _result(
                item,
                status="stale",
                code=MISSING_STATE_VERSION,
                message="This message needs to be refreshed before committing.",
            )
        if not current_version or item.expected_version != current_version:
            return _result(
                item,
                status="stale",
                code=STALE_MESSAGE,
                message="This message changed after the queue loaded. Review it again.",
            )
    return None


def _rule_payload(rule: StagedCommitRule | None) -> dict | None:
    if rule is None:
        return None
    return {
        "scope": rule.scope,
        "account_email": rule.account_email,
        "rule_type": rule.rule_type,
        "pattern": rule.pattern,
        "action": rule.action,
    }


def _action_payload(item: StagedCommitAction) -> dict:
    return {
        "client_action_id": item.client_action_id,
        "message_id": item.message_id,
        "action": item.action,
        "expected_version": item.expected_version,
        "rule": _rule_payload(item.rule),
    }


def _request_hash(actions: Sequence[StagedCommitAction]) -> str:
    payload = [_action_payload(item) for item in actions]
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def _load_idempotent_response(
    *,
    user_id: int,
    idempotency_key: str,
    request_hash: str,
) -> dict | None:
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
            "Staged queue commit idempotency key reused with different payload user_id=%s idempotency_key=%s",
            user_id,
            idempotency_key,
        )

    try:
        response = json.loads(row["response_json"])
    except (TypeError, json.JSONDecodeError):
        logger.exception(
            "Stored staged queue idempotency response could not be decoded user_id=%s idempotency_key=%s",
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
    timestamp = _now_iso()
    stored_response = {**response, "idempotent_replay": False}
    with get_connection() as conn:
        execute_sql(
            conn,
            """
            INSERT INTO staged_commit_requests (
                user_id,
                idempotency_key,
                request_hash,
                response_json,
                created_at,
                updated_at
            )
            VALUES (
                :user_id,
                :idempotency_key,
                :request_hash,
                :response_json,
                :created_at,
                :updated_at
            )
            """,
            {
                "user_id": user_id,
                "idempotency_key": idempotency_key,
                "request_hash": request_hash,
                "response_json": json.dumps(stored_response, sort_keys=True),
                "created_at": timestamp,
                "updated_at": timestamp,
            },
        )


def _create_staged_rule(item: StagedCommitAction, *, user_id: int | None) -> tuple[dict, int] | dict:
    if item.rule is None:
        return ({}, 0)
    try:
        rule = create_rule(
            {
                "scope": item.rule.scope,
                "account_email": item.rule.account_email,
                "rule_type": item.rule.rule_type,
                "pattern": item.rule.pattern,
                "action": item.rule.action,
                "source_message_id": item.message_id,
                "apply_to_source": False,
            },
            user_id=user_id,
        )
        reclassified = reclassify_pending_messages(user_id=user_id)
        return rule, int(reclassified.get("reclassified_messages", 0))
    except (RuleAccountUnavailableError, RuleSourceMessageUnavailableError, ValueError) as error:
        return _result(
            item,
            status="failed",
            code=RULE_CREATE_FAILED,
            message=str(error) or "Rule could not be created.",
        )


def _commit_one(
    item: StagedCommitAction,
    *,
    user_id: int | None,
    version_prevalidated: bool = False,
) -> dict:
    with get_connection() as conn:
        row = _message_row(conn, item.message_id, user_id)
        if row is None or bool(row["reviewed"]):
            return _result(
                item,
                status="stale",
                code=STALE_MESSAGE,
                message="This message was already processed. The queue has been refreshed.",
            )

        if not version_prevalidated:
            current_version = _state_version(row)
            if not item.expected_version:
                return _result(
                    item,
                    status="stale",
                    code=MISSING_STATE_VERSION,
                    message="This message needs to be refreshed before committing.",
                )
            if not current_version or item.expected_version != current_version:
                return _result(
                    item,
                    status="stale",
                    code=STALE_MESSAGE,
                    message="This message changed after the queue loaded. Review it again.",
                )

        use_live_writes = _has_modify_scope(row)

    rule_context = _create_staged_rule(item, user_id=user_id)
    if isinstance(rule_context, dict):
        return rule_context
    rule, reclassified_messages = rule_context
    rule_id = int(rule["id"]) if rule else None

    try:
        if use_live_writes:
            live_result = execute_message_action(
                item.message_id,
                item.action,
                allow_live_writes=True,
                require_feature_flag=True,
                user_id=user_id,
            )
            if live_result is None:
                return _result(
                    item,
                    status="stale",
                    code=STALE_MESSAGE,
                    message="This message was already processed. The queue has been refreshed.",
                )
            if live_result.executed:
                log_executed_message_action(live_result, action_source="staged_commit")
                return _result(
                    item,
                    status="committed",
                    message="Committed.",
                    executed=True,
                    labels_added=list(live_result.labels_added),
                    labels_removed=list(live_result.labels_removed),
                    rule_id=rule_id,
                    reclassified_messages=reclassified_messages,
                )
            return _result(
                item,
                status="blocked",
                code=MESSAGE_ACTION_FAILED,
                message="Live Gmail execution was blocked. The message was left in the queue.",
                executed=False,
                labels_added=list(live_result.labels_added),
                labels_removed=list(live_result.labels_removed),
                rule_id=rule_id,
                reclassified_messages=reclassified_messages,
            )

        result = apply_message_action(
            item.message_id,
            item.action,
            user_id=user_id,
            action_source="staged_commit",
        )
        if result is None:
            return _result(
                item,
                status="stale",
                code=STALE_MESSAGE,
                message="This message was already processed. The queue has been refreshed.",
            )
        return _result(
            item,
            status="committed",
            message="Committed.",
            executed=True,
            labels_added=list(result["labels_added"]),
            labels_removed=list(result["labels_removed"]),
            rule_id=rule_id,
            reclassified_messages=reclassified_messages,
        )
    except GmailReadonlySyncError as error:
        logger.warning(
            "Staged commit Gmail action failed for message_id=%s user_id=%s action=%s: %s",
            item.message_id,
            user_id,
            item.action,
            error,
        )
        return _result(
            item,
            status="failed",
            code=_code_for_gmail_error(error),
            message=str(error) or "Gmail action failed.",
            rule_id=rule_id,
            reclassified_messages=reclassified_messages,
        )
    except UnsafeMessageActionError as error:
        return _result(
            item,
            status="failed",
            code=UNSAFE_MESSAGE_ACTION,
            message=str(error) or "Unsafe message action.",
            rule_id=rule_id,
            reclassified_messages=reclassified_messages,
        )
    except ValueError as error:
        return _result(
            item,
            status="failed",
            code=MESSAGE_ACTION_FAILED,
            message=str(error) or "Message action failed.",
            rule_id=rule_id,
            reclassified_messages=reclassified_messages,
        )


def commit_staged_actions(
    actions: Sequence[StagedCommitAction],
    *,
    idempotency_key: str,
    user_id: int | None = None,
) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="commit_staged_actions",
    )
    request_hash = _request_hash(actions)
    existing_response = _load_idempotent_response(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
    )
    if existing_response is not None:
        logger.info(
            "Staged queue commit replay user_id=%s idempotency_key=%s requested=%s",
            user_id,
            idempotency_key,
            len(actions),
        )
        return existing_response

    seen_message_ids: set[int] = set()
    result_slots: list[dict | None] = []
    prevalidated_items: list[StagedCommitAction] = []
    prevalidated_indexes: list[int] = []

    for item in actions:
        if item.message_id in seen_message_ids:
            result_slots.append(
                _result(
                    item,
                    status="failed",
                    code=DUPLICATE_STAGED_MESSAGE,
                    message="This message was included more than once in the commit.",
                )
            )
            continue
        seen_message_ids.add(item.message_id)
        stale_result = _stale_result_for_item(item, user_id=user_id)
        if stale_result is not None:
            result_slots.append(stale_result)
            continue
        prevalidated_indexes.append(len(result_slots))
        prevalidated_items.append(item)
        result_slots.append(None)

    for index, item in zip(prevalidated_indexes, prevalidated_items, strict=True):
        result_slots[index] = _commit_one(
            item,
            user_id=user_id,
            version_prevalidated=True,
        )

    results = [result for result in result_slots if result is not None]

    committed_count = sum(1 for result in results if result["status"] == "committed")
    failed_count = len(results) - committed_count
    stale_count = sum(1 for result in results if result["status"] == "stale")
    blocked_count = sum(1 for result in results if result["status"] == "blocked")
    logger.info(
        "Staged queue commit user_id=%s idempotency_key=%s requested=%s committed=%s failed=%s stale=%s blocked=%s",
        user_id,
        idempotency_key,
        len(actions),
        committed_count,
        failed_count,
        stale_count,
        blocked_count,
    )
    response = {
        "committed_count": committed_count,
        "failed_count": failed_count,
        "results": results,
    }
    _store_idempotent_response(
        user_id=user_id,
        idempotency_key=idempotency_key,
        request_hash=request_hash,
        response=response,
    )
    return response
