from __future__ import annotations

import json
import logging
from collections import Counter
from datetime import datetime, timezone

from app.core.config import (
    AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED,
    AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD,
    BODY_PREVIEW_LIMIT,
    MAX_SYNC_MESSAGES_PER_ACCOUNT,
)
from app.data.mock_messages import get_mock_messages
from app.db.runtime import execute_sql, fetch_all, fetch_one, get_connection, insert_and_return_id
from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, DEFAULT_LOCAL_OWNER_NAME
from app.services.action_logging import insert_action_log
from app.services.classifier import (
    ClassificationResult,
    classify_message,
    extract_domain,
    extract_email,
    serialize_headers,
)
from app.services.gmail_readonly import GmailReadonlySyncError, fetch_unread_inbox_messages
from app.services.gmail_write_executor import execute_message_action, log_executed_message_action
from app.services.gmail_write_planner import ACTION_TO_LABELS, plan_message_action
from app.services.mail_provider_adapter import get_mail_provider_adapter
from app.services.gmail_token_store import GmailTokenReference, update_connection_metadata
from app.services.ownership import fetch_owned_message
from app.services.provider_models import MailAccountRecord, ProviderMessageRecord
from app.services.rules import record_rule_matches
from app.services.runtime_user import require_explicit_user_id_in_cloud


CATEGORY_META = [
    ("trash", "Likely Trash"),
    ("junk_review", "Junk Review"),
    ("bulk_mail", "Bulk Mail"),
    ("needs_review", "Needs Review"),
    ("keep", "Keep in Inbox"),
]
AUTO_CLEAN_CATEGORIES = {"bulk_mail", "junk_review"}
QUEUE_SOURCE_LABELS = {
    "rule_keep": "Auto-Keep",
    "high_confidence_keep": "Auto-Keep",
    "recovered": "Recovered",
}

logger = logging.getLogger(__name__)


class UnsafeMessageActionError(ValueError):
    pass


def _existing_message_state_changed(
    existing_row,
    *,
    message: dict,
    account_email: str,
    mail_account_id: int | None,
    provider_labels_json: str,
    headers_json: str,
    sender_domain: str,
    stored_category: str,
    queue_source: str,
    queue_source_detail: str | None,
    classification: ClassificationResult,
    reset_reviewed: bool,
    preserve_reviewed: bool,
) -> bool:
    if existing_row is None:
        return True

    expected_reviewed = (
        0 if reset_reviewed and not preserve_reviewed else existing_row["reviewed"]
    )
    expected_recovery_pending = (
        1
        if existing_row["recovery_pending"] == 1 and stored_category == "needs_review"
        else 0
    )
    comparisons = {
        "gmail_message_id": message["gmail_message_id"],
        "gmail_thread_id": message["gmail_thread_id"],
        "account_email": account_email,
        "mail_account_id": mail_account_id,
        "provider_message_id": message["gmail_message_id"],
        "provider_thread_id": message["gmail_thread_id"],
        "sender": message["sender"],
        "sender_domain": sender_domain,
        "reply_to": message["reply_to"],
        "recipient_to": message["recipient_to"],
        "recipient_cc": message["recipient_cc"],
        "subject": message["subject"],
        "received_at": message["received_at"],
        "snippet": message["snippet"],
        "body_preview": message["body_preview"][:BODY_PREVIEW_LIMIT],
        "gmail_labels_json": provider_labels_json,
        "provider_labels_json": provider_labels_json,
        "headers_json": headers_json,
        "has_attachments": message["has_attachments"],
        "current_category": stored_category,
        "recovery_pending": expected_recovery_pending,
        "confidence": classification.confidence,
        "protected": 1 if classification.protected else 0,
        "reviewed": expected_reviewed,
        "queue_source": queue_source,
        "queue_source_detail": queue_source_detail,
    }
    for column, expected_value in comparisons.items():
        if existing_row[column] != expected_value:
            return True
    return False


def _history_counters(conn, user_id: int | None = None) -> tuple[Counter, Counter]:
    sender_counter: Counter = Counter()
    domain_counter: Counter = Counter()
    if user_id is None:
        rows = fetch_all(
            conn,
            """
            SELECT l.selected_action, m.sender, m.sender_domain
            FROM actions_log l
            JOIN messages m
              ON l.message_id = m.id
              OR (
                    l.message_id IS NULL
                AND l.gmail_message_id = m.gmail_message_id
                AND l.account_email = m.account_email
              )
            """
        )
    else:
        rows = fetch_all(
            conn,
            """
            SELECT l.selected_action, m.sender, m.sender_domain
            FROM actions_log l
            JOIN messages m
              ON l.message_id = m.id
              OR (
                    l.message_id IS NULL
                AND l.gmail_message_id = m.gmail_message_id
                AND l.account_email = m.account_email
              )
            JOIN mail_accounts ma ON ma.id = m.mail_account_id
            WHERE ma.user_id = :user_id
            """,
            {"user_id": user_id},
        )
    for row in rows:
        if row["sender"]:
            sender_email = extract_email(row["sender"])
            sender_counter[f"{sender_email}:{row['selected_action']}"] += 1
        if row["sender_domain"]:
            domain_counter[f"{row['sender_domain'].lower()}:{row['selected_action']}"] += 1
    return sender_counter, domain_counter


def _load_rules(conn) -> list[dict]:
    rows = fetch_all(conn, "SELECT * FROM rules WHERE enabled = 1 ORDER BY id DESC")
    return [dict(row) | {"enabled": bool(row["enabled"])} for row in rows]


def _ensure_default_user(conn, now: str) -> int:
    row = fetch_one(
        conn,
        "SELECT id FROM users WHERE email = :email",
        {"email": DEFAULT_LOCAL_OWNER_EMAIL},
    )
    if row is not None:
        return int(row["id"])
    return insert_and_return_id(
        conn,
        """
        INSERT INTO users (email, display_name, status, created_at, updated_at)
        VALUES (:email, :display_name, 'active', :created_at, :updated_at)
        """,
        {
            "email": DEFAULT_LOCAL_OWNER_EMAIL,
            "display_name": DEFAULT_LOCAL_OWNER_NAME,
            "created_at": now,
            "updated_at": now,
        },
    )


def _ensure_sync_account_provider_records(conn, account, now: str):
    if account["mail_account_id"] is not None:
        return account

    user_id = _ensure_default_user(conn, now)
    existing_mail_account = fetch_one(
        conn,
        """
        SELECT id
        FROM mail_accounts
        WHERE user_id = :user_id AND provider = :provider AND external_account_email = :account_email
        ORDER BY id DESC
        LIMIT 1
        """,
        {
            "user_id": user_id,
            "provider": account["provider"],
            "account_email": account["external_account_email"],
        },
    )
    if existing_mail_account is None:
        mail_account_id = insert_and_return_id(
            conn,
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (
                :user_id, :provider, :account_email, :display_name,
                :enabled, :status, :last_sync_at, :created_at, :updated_at
            )
            """,
            {
                "user_id": user_id,
                "provider": account["provider"],
                "account_email": account["external_account_email"],
                "display_name": account["external_account_email"],
                "enabled": 1 if bool(account["enabled"]) else 0,
                "status": "active" if bool(account["enabled"]) else "disabled",
                "last_sync_at": account["last_sync_at"],
                "created_at": now,
                "updated_at": now,
            },
        )
    else:
        mail_account_id = int(existing_mail_account["id"])

    if account["provider"] == "gmail_readonly" and account["token_path"]:
        existing_provider_connection = fetch_one(
            conn,
            """
            SELECT id
            FROM provider_connections
            WHERE mail_account_id = :mail_account_id AND provider = :provider
            ORDER BY id DESC
            LIMIT 1
            """,
            {
                "mail_account_id": mail_account_id,
                "provider": account["provider"],
            },
        )
        if existing_provider_connection is None:
            execute_sql(
                conn,
                """
                INSERT INTO provider_connections (
                    mail_account_id, provider, connection_type, credentials_ref,
                    token_path, scopes_json, metadata_json, created_at, updated_at
                ) VALUES (
                    :mail_account_id, :provider, 'oauth', NULL,
                    :token_path, :scopes_json, '{}', :created_at, :updated_at
                )
                """,
                {
                    "mail_account_id": mail_account_id,
                    "provider": account["provider"],
                    "token_path": account["token_path"],
                    "scopes_json": account["scopes_json"] or "[]",
                    "created_at": now,
                    "updated_at": now,
                },
            )
        else:
            execute_sql(
                conn,
                """
                UPDATE provider_connections
                SET token_path = :token_path, scopes_json = :scopes_json, updated_at = :updated_at
                WHERE id = :provider_connection_id
                """,
                {
                    "token_path": account["token_path"],
                    "scopes_json": account["scopes_json"] or "[]",
                    "updated_at": now,
                    "provider_connection_id": existing_provider_connection["id"],
                },
            )

    updated = dict(account)
    updated["mail_account_id"] = mail_account_id
    return updated


def _enabled_mail_accounts(conn, user_id: int | None = None):
    params: dict[str, object] = {}
    primary_user_filter = ""
    if user_id is not None:
        primary_user_filter = "AND ma.user_id = :user_id"
        params["user_id"] = user_id

    primary_rows = fetch_all(
        conn,
        f"""
        SELECT
            a.id AS legacy_account_id,
            a.email_address AS legacy_email_address,
            a.last_sync_at AS legacy_last_sync_at,
            ma.id AS mail_account_id,
            ma.user_id,
            ma.provider,
            ma.external_account_email,
            ma.display_name AS mail_account_display_name,
            ma.enabled,
            ma.high_confidence_auto_clean_enabled,
            ma.status AS mail_account_status,
            ma.last_sync_at,
            pc.id AS provider_connection_id,
            pc.token_path,
            pc.scopes_json,
            pc.metadata_json
        FROM mail_accounts ma
        LEFT JOIN accounts a
          ON a.email_address = ma.external_account_email
         AND a.provider = ma.provider
        LEFT JOIN provider_connections pc
          ON pc.id = (
                SELECT latest_pc.id
                FROM provider_connections latest_pc
                WHERE latest_pc.mail_account_id = ma.id
                  AND latest_pc.provider = ma.provider
                ORDER BY latest_pc.id DESC
                LIMIT 1
             )
        WHERE ma.enabled = 1
          {primary_user_filter}
        ORDER BY ma.external_account_email ASC
        """,
        params,
    )
    if user_id is None:
        legacy_only_rows = fetch_all(
            conn,
            """
            SELECT
                a.id AS legacy_account_id,
                a.email_address AS legacy_email_address,
                a.last_sync_at AS legacy_last_sync_at,
                NULL AS mail_account_id,
                NULL AS user_id,
                a.provider,
                a.email_address AS external_account_email,
                a.email_address AS mail_account_display_name,
                a.enabled,
                1 AS high_confidence_auto_clean_enabled,
                CASE WHEN a.enabled = 1 THEN 'active' ELSE 'disabled' END AS mail_account_status,
                a.last_sync_at,
                NULL AS provider_connection_id,
                g.token_path,
                g.scopes_json,
                NULL AS metadata_json
            FROM accounts a
            LEFT JOIN mail_accounts ma
              ON ma.external_account_email = a.email_address
             AND ma.provider = a.provider
            LEFT JOIN gmail_account_connections g ON g.account_id = a.id
            WHERE a.enabled = 1
              AND ma.id IS NULL
            ORDER BY a.email_address ASC
            """
        )
    else:
        legacy_only_rows = []
    return list(primary_rows) + list(legacy_only_rows)


def _provider_messages_for_account(conn, account) -> list[dict]:
    if account["provider"] == "gmail_readonly":
        reference = GmailTokenReference.from_row(account)
        if (
            reference.token_path is None
            and reference.provider_connection_id is None
            and reference.token_json() is None
        ):
            return []
        adapter = get_mail_provider_adapter(account["provider"])
        if adapter is None:
            return []
        return adapter.list_unread_inbox_messages(
            reference,
            max_results=MAX_SYNC_MESSAGES_PER_ACCOUNT,
        )

    return get_mock_messages(account["external_account_email"])[:MAX_SYNC_MESSAGES_PER_ACCOUNT]


def _record_sync_failure(conn, account, now: str, error: Exception) -> None:
    provider_connection_id = account.get("provider_connection_id")
    if provider_connection_id is None:
        return

    update_connection_metadata(
        int(provider_connection_id),
        {
            "last_sync_error": str(error),
            "last_sync_error_at": now,
            "reconnect_required": 1,
        },
        conn=conn,
    )


def _clear_sync_failure(conn, account) -> None:
    provider_connection_id = account.get("provider_connection_id")
    if provider_connection_id is None:
        return

    update_connection_metadata(
        int(provider_connection_id),
        {
            "last_sync_error": None,
            "last_sync_error_at": None,
            "reconnect_required": 0,
        },
        conn=conn,
    )


def _upsert_classified_message(
    conn,
    account,
    message: dict,
    now: str,
    rules: list[dict],
    history_by_sender: Counter,
    history_by_domain: Counter,
    *,
    reset_reviewed: bool = False,
) -> tuple[int, ClassificationResult, bool]:
    sender_domain = extract_domain(message["sender"])
    classification = classify_message(
        message=message,
        rules=rules,
        history_by_sender=history_by_sender,
        history_by_domain=history_by_domain,
    )
    account_email = account["external_account_email"]
    mail_account_id = account["mail_account_id"]
    provider_message_id = message["gmail_message_id"]
    provider_thread_id = message["gmail_thread_id"]
    provider_labels_json = json.dumps(message["gmail_labels"])
    existing_row = (
        fetch_one(
            conn,
            """
            SELECT
                m.id,
                m.gmail_message_id,
                m.gmail_thread_id,
                m.account_email,
                m.mail_account_id,
                m.provider_message_id,
                m.provider_thread_id,
                m.sender,
                m.sender_domain,
                m.reply_to,
                m.recipient_to,
                m.recipient_cc,
                m.subject,
                m.received_at,
                m.snippet,
                m.body_preview,
                m.gmail_labels_json,
                m.provider_labels_json,
                m.headers_json,
                m.has_attachments,
                m.reviewed,
                m.current_category,
                m.recovery_pending,
                m.confidence,
                m.protected,
                m.queue_source,
                m.queue_source_detail,
                m.updated_at,
                EXISTS(
                    SELECT 1
                    FROM actions_log l
                    WHERE l.message_id = m.id
                      AND l.selected_action = 'keep'
                ) AS has_keep_action
            FROM messages m
            WHERE m.mail_account_id = :mail_account_id AND m.provider_message_id = :provider_message_id
            """,
            {
                "mail_account_id": mail_account_id,
                "provider_message_id": provider_message_id,
            },
        )
        if mail_account_id is not None
        else fetch_one(
            conn,
            """
            SELECT
                m.id,
                m.gmail_message_id,
                m.gmail_thread_id,
                m.account_email,
                m.mail_account_id,
                m.provider_message_id,
                m.provider_thread_id,
                m.sender,
                m.sender_domain,
                m.reply_to,
                m.recipient_to,
                m.recipient_cc,
                m.subject,
                m.received_at,
                m.snippet,
                m.body_preview,
                m.gmail_labels_json,
                m.provider_labels_json,
                m.headers_json,
                m.has_attachments,
                m.reviewed,
                m.current_category,
                m.recovery_pending,
                m.confidence,
                m.protected,
                m.queue_source,
                m.queue_source_detail,
                m.updated_at,
                EXISTS(
                    SELECT 1
                    FROM actions_log l
                    WHERE l.message_id = m.id
                      AND l.selected_action = 'keep'
                ) AS has_keep_action
            FROM messages m
            WHERE m.gmail_message_id = :gmail_message_id AND m.account_email = :account_email
            """,
            {
                "gmail_message_id": message["gmail_message_id"],
                "account_email": account_email,
            },
        )
    )
    record_rule_matches(classification.matched_rule_ids, conn=conn)
    preserve_manual_keep = bool(
        existing_row and existing_row["reviewed"] and existing_row["has_keep_action"]
    )
    preserve_rule_autoprocess = bool(
        existing_row
        and existing_row["reviewed"]
        and existing_row["current_category"] == classification.category
        and classification.matched_rule_ids
        and classification.category not in {"needs_review", "keep"}
    )
    preserve_reviewed = preserve_manual_keep or preserve_rule_autoprocess
    stored_category = (
        existing_row["current_category"]
        if preserve_manual_keep
        else classification.category
    )
    queue_source = "rule_keep" if (
        classification.category == "keep"
        and bool(classification.matched_rule_ids)
        and not preserve_reviewed
    ) else "classifier"
    queue_source_detail = (
        json.dumps({"matched_rule_ids": classification.matched_rule_ids})
        if queue_source == "rule_keep"
        else None
    )
    if preserve_reviewed and existing_row is not None:
        queue_source = existing_row["queue_source"] or "classifier"
        queue_source_detail = existing_row["queue_source_detail"]
    headers_json = serialize_headers(message["headers"])
    state_updated_at = (
        now
        if _existing_message_state_changed(
            existing_row,
            message=message,
            account_email=account_email,
            mail_account_id=mail_account_id,
            provider_labels_json=provider_labels_json,
            headers_json=headers_json,
            sender_domain=sender_domain,
            stored_category=stored_category,
            queue_source=queue_source,
            queue_source_detail=queue_source_detail,
            classification=classification,
            reset_reviewed=reset_reviewed,
            preserve_reviewed=preserve_reviewed,
        )
        else existing_row["updated_at"]
    )
    update_reviewed_sql = (
        ", reviewed = 0"
        if reset_reviewed and not preserve_reviewed
        else ""
    )
    if existing_row is not None:
        execute_sql(
            conn,
            f"""
            UPDATE messages
            SET
                gmail_message_id = :gmail_message_id,
                gmail_thread_id = :gmail_thread_id,
                account_email = :account_email,
                mail_account_id = :mail_account_id,
                provider_message_id = :provider_message_id,
                provider_thread_id = :provider_thread_id,
                sender = :sender,
                sender_domain = :sender_domain,
                reply_to = :reply_to,
                recipient_to = :recipient_to,
                recipient_cc = :recipient_cc,
                subject = :subject,
                received_at = :received_at,
                snippet = :snippet,
                body_preview = :body_preview,
                gmail_labels_json = :gmail_labels_json,
                provider_labels_json = :provider_labels_json,
                headers_json = :headers_json,
                has_attachments = :has_attachments,
                current_category = :current_category,
                recovery_pending = CASE
                    WHEN recovery_pending = 1 AND :current_category = 'needs_review' THEN 1
                    ELSE 0
                END,
                confidence = :confidence,
                protected = :protected,
                queue_source = :queue_source,
                queue_source_detail = :queue_source_detail,
                updated_at = :updated_at
                {update_reviewed_sql}
            WHERE id = :message_id
            """,
            {
                "gmail_message_id": message["gmail_message_id"],
                "gmail_thread_id": message["gmail_thread_id"],
                "account_email": account_email,
                "mail_account_id": mail_account_id,
                "provider_message_id": provider_message_id,
                "provider_thread_id": provider_thread_id,
                "sender": message["sender"],
                "sender_domain": sender_domain,
                "reply_to": message["reply_to"],
                "recipient_to": message["recipient_to"],
                "recipient_cc": message["recipient_cc"],
                "subject": message["subject"],
                "received_at": message["received_at"],
                "snippet": message["snippet"],
                "body_preview": message["body_preview"][:BODY_PREVIEW_LIMIT],
                "gmail_labels_json": provider_labels_json,
                "provider_labels_json": provider_labels_json,
                "headers_json": headers_json,
                "has_attachments": message["has_attachments"],
                "current_category": stored_category,
                "confidence": classification.confidence,
                "protected": 1 if classification.protected else 0,
                "queue_source": queue_source,
                "queue_source_detail": queue_source_detail,
                "updated_at": state_updated_at,
                "message_id": existing_row["id"],
            },
        )
        message_row = fetch_one(
            conn,
            "SELECT id, reviewed, current_category FROM messages WHERE id = :message_id",
            {"message_id": existing_row["id"]},
        )
    else:
        execute_sql(
            conn,
            """
            INSERT INTO messages (
                gmail_message_id, gmail_thread_id, account_email, mail_account_id,
                provider_message_id, provider_thread_id, sender, sender_domain,
                reply_to, recipient_to, recipient_cc, subject, received_at, snippet,
                body_preview, gmail_labels_json, provider_labels_json, headers_json,
                has_attachments, current_category, confidence, protected, reviewed,
                recovery_pending, queue_source, queue_source_detail, created_at, updated_at
            ) VALUES (
                :gmail_message_id, :gmail_thread_id, :account_email, :mail_account_id,
                :provider_message_id, :provider_thread_id, :sender, :sender_domain,
                :reply_to, :recipient_to, :recipient_cc, :subject, :received_at, :snippet,
                :body_preview, :gmail_labels_json, :provider_labels_json, :headers_json,
                :has_attachments, :current_category, :confidence, :protected, 0,
                0, :queue_source, :queue_source_detail,
                :created_at, :updated_at
            )
            """,
            {
                "gmail_message_id": message["gmail_message_id"],
                "gmail_thread_id": message["gmail_thread_id"],
                "account_email": account_email,
                "mail_account_id": mail_account_id,
                "provider_message_id": provider_message_id,
                "provider_thread_id": provider_thread_id,
                "sender": message["sender"],
                "sender_domain": sender_domain,
                "reply_to": message["reply_to"],
                "recipient_to": message["recipient_to"],
                "recipient_cc": message["recipient_cc"],
                "subject": message["subject"],
                "received_at": message["received_at"],
                "snippet": message["snippet"],
                "body_preview": message["body_preview"][:BODY_PREVIEW_LIMIT],
                "gmail_labels_json": provider_labels_json,
                "provider_labels_json": provider_labels_json,
                "headers_json": headers_json,
                "has_attachments": message["has_attachments"],
                "current_category": stored_category,
                "confidence": classification.confidence,
                "protected": 1 if classification.protected else 0,
                "queue_source": queue_source,
                "queue_source_detail": queue_source_detail,
                "created_at": now,
                "updated_at": now,
            },
        )
        message_row = fetch_one(
            conn,
            """
            SELECT id, reviewed, current_category FROM messages
            WHERE gmail_message_id = :gmail_message_id AND account_email = :account_email
            ORDER BY id DESC
            LIMIT 1
            """,
            {
                "gmail_message_id": message["gmail_message_id"],
                "account_email": account_email,
            },
        )
    execute_sql(
        conn,
        """
        INSERT INTO classification_results (
            message_id, category, confidence, reasons_json, protected,
            protection_reasons_json, created_at
        ) VALUES (
            :message_id, :category, :confidence, :reasons_json, :protected,
            :protection_reasons_json, :created_at
        )
        """,
        {
            "message_id": message_row["id"],
            "category": classification.category,
            "confidence": classification.confidence,
            "reasons_json": json.dumps(classification.reasons),
            "protected": 1 if classification.protected else 0,
            "protection_reasons_json": json.dumps(
                classification.protection_reasons
            ),
            "created_at": now,
        },
    )
    return int(message_row["id"]), classification, preserve_reviewed


def _reconcile_gmail_account_queue(
    conn,
    account_identifier: int | str,
    current_message_ids: set[str],
    now: str,
) -> int:
    identifier_column = (
        "mail_account_id" if isinstance(account_identifier, int) else "account_email"
    )
    if current_message_ids:
        message_id_params = {
            f"message_id_{index}": message_id
            for index, message_id in enumerate(sorted(current_message_ids))
        }
        placeholders = ", ".join(f":{name}" for name in message_id_params)
        result = execute_sql(
            conn,
            f"""
            UPDATE messages
            SET reviewed = 1, updated_at = :updated_at
            WHERE {identifier_column} = :account_identifier
              AND reviewed = 0
              AND recovery_pending = 0
              AND provider_message_id NOT IN ({placeholders})
            """,
            {
                "updated_at": now,
                "account_identifier": account_identifier,
                **message_id_params,
            },
        )
    else:
        result = execute_sql(
            conn,
            f"""
            UPDATE messages
            SET reviewed = 1, updated_at = :updated_at
            WHERE {identifier_column} = :account_identifier
              AND reviewed = 0
              AND recovery_pending = 0
            """,
            {"updated_at": now, "account_identifier": account_identifier},
        )
    return int(result.rowcount or 0)


def _should_auto_apply_rule_match(
    classification: ClassificationResult,
    preserve_reviewed: bool,
) -> bool:
    return (
        bool(classification.matched_rule_ids)
        and classification.category not in {"needs_review", "keep"}
        and not preserve_reviewed
    )


def _auto_apply_rule_match(
    account,
    message_id: int,
    classification: ClassificationResult,
    conn,
    *,
    user_id: int | None = None,
) -> bool:
    if account["provider"] == "gmail_readonly":
        result = execute_message_action(
            message_id,
            classification.category,
            allow_live_writes=True,
            require_feature_flag=True,
            conn=conn,
            user_id=user_id,
        )
        if result is None or not result.executed:
            return False
        log_executed_message_action(result, conn=conn, action_source="rule_auto_apply")
        return True

    applied = apply_message_action(
        message_id,
        classification.category,
        conn=conn,
        user_id=user_id,
        action_source="rule_auto_apply",
    )
    return applied is not None


def _should_auto_clean_high_confidence(
    account,
    classification: ClassificationResult,
    preserve_reviewed: bool,
) -> bool:
    return (
        AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED
        and account["provider"] == "gmail_readonly"
        and bool(account["high_confidence_auto_clean_enabled"])
        and classification.category in AUTO_CLEAN_CATEGORIES
        and classification.confidence >= AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD
        and not classification.protected
        and not preserve_reviewed
    )


def _auto_clean_high_confidence(
    message_id: int,
    classification: ClassificationResult,
    conn,
    *,
    user_id: int | None = None,
) -> bool:
    result = execute_message_action(
        message_id,
        classification.category,
        allow_live_writes=True,
        require_feature_flag=True,
        conn=conn,
        user_id=user_id,
    )
    if result is None or not result.executed:
        return False
    log_executed_message_action(result, conn=conn, action_source="high_confidence_auto_clean")
    return True


def sync_unread_messages(
    user_id: int | None = None,
    *,
    allow_global: bool = False,
) -> dict:
    if not allow_global:
        user_id = require_explicit_user_id_in_cloud(
            user_id,
            operation="sync_unread_messages",
        )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        accounts = _enabled_mail_accounts(conn, user_id=user_id)
        rules = _load_rules(conn)
        if user_id is not None:
            rules = [rule for rule in rules if rule.get("user_id") == user_id]
        history_by_sender, history_by_domain = _history_counters(conn, user_id=user_id)

        synced_count = 0
        reconciled_count = 0
        auto_applied_count = 0
        failed_accounts: list[dict] = []
        for account in accounts:
            account = _ensure_sync_account_provider_records(conn, account, now)
            try:
                messages = _provider_messages_for_account(conn, account)
            except GmailReadonlySyncError as error:
                logger.warning(
                    "Skipping sync for account %s due to Gmail sync error: %s",
                    account["external_account_email"],
                    error,
                )
                _record_sync_failure(conn, account, now, error)
                failed_accounts.append(
                    {
                        "account_email": account["external_account_email"],
                        "provider": account["provider"],
                        "reason": str(error),
                    }
                )
                continue

            _clear_sync_failure(conn, account)
            current_message_ids = {
                message["gmail_message_id"]
                for message in messages
                if message.get("gmail_message_id")
            }
            for message in messages:
                message_id, classification, preserve_reviewed = _upsert_classified_message(
                    conn=conn,
                    account=account,
                    message=message,
                    now=now,
                    rules=rules,
                    history_by_sender=history_by_sender,
                    history_by_domain=history_by_domain,
                    reset_reviewed=account["provider"] == "gmail_readonly",
                )
                if _should_auto_apply_rule_match(classification, preserve_reviewed):
                    if _auto_apply_rule_match(
                        account,
                        message_id,
                        classification,
                        conn,
                        user_id=user_id,
                    ):
                        auto_applied_count += 1
                elif _should_auto_clean_high_confidence(
                    account,
                    classification,
                    preserve_reviewed,
                ):
                    if _auto_clean_high_confidence(
                        message_id,
                        classification,
                        conn,
                        user_id=user_id,
                    ):
                        auto_applied_count += 1
                synced_count += 1
            if account["provider"] == "gmail_readonly":
                reconciled_count += _reconcile_gmail_account_queue(
                    conn,
                    int(account["mail_account_id"])
                    if account["mail_account_id"] is not None
                    else account["external_account_email"],
                    current_message_ids,
                    now,
                )
            if account["mail_account_id"] is not None:
                execute_sql(
                    conn,
                    "UPDATE mail_accounts SET last_sync_at = :last_sync_at, updated_at = :updated_at WHERE id = :mail_account_id",
                    {
                        "last_sync_at": now,
                        "updated_at": now,
                        "mail_account_id": account["mail_account_id"],
                    },
                )
            if account["legacy_account_id"] is not None:
                execute_sql(
                    conn,
                    "UPDATE accounts SET last_sync_at = :last_sync_at, updated_at = :updated_at WHERE id = :legacy_account_id",
                    {
                        "last_sync_at": now,
                        "updated_at": now,
                        "legacy_account_id": account["legacy_account_id"],
                    },
                )
    return {
        "synced_messages": synced_count,
        "reconciled_messages": reconciled_count,
        "auto_applied_messages": auto_applied_count,
        "failed_accounts": failed_accounts,
    }


def reclassify_pending_messages(user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="reclassify_pending_messages",
    )
    now = datetime.now(timezone.utc).isoformat()
    with get_connection() as conn:
        rules = _load_rules(conn)
        if user_id is not None:
            rules = [rule for rule in rules if rule.get("user_id") == user_id]
        history_by_sender, history_by_domain = _history_counters(conn, user_id=user_id)
        if user_id is None:
            rows = fetch_all(
                conn,
                """
                SELECT *
                FROM messages
                WHERE reviewed = 0
                ORDER BY mail_account_id ASC, received_at DESC
                """,
            )
        else:
            rows = fetch_all(
                conn,
                """
                SELECT m.*
                FROM messages m
                JOIN mail_accounts ma ON ma.id = m.mail_account_id
                WHERE m.reviewed = 0
                  AND ma.user_id = :user_id
                ORDER BY m.mail_account_id ASC, m.received_at DESC
                """,
                {"user_id": user_id},
            )

        updated_count = 0
        for row in rows:
            headers = json.loads(row["headers_json"] or "{}")
            message = {
                "sender": row["sender"],
                "reply_to": row["reply_to"],
                "subject": row["subject"],
                "body_preview": row["body_preview"],
                "headers": headers,
                "has_attachments": row["has_attachments"],
            }
            classification = classify_message(
                message=message,
                rules=rules,
                history_by_sender=history_by_sender,
                history_by_domain=history_by_domain,
            )
            record_rule_matches(classification.matched_rule_ids, conn=conn)
            execute_sql(
                conn,
                """
                UPDATE messages
                SET current_category = :current_category, confidence = :confidence, protected = :protected, updated_at = :updated_at
                WHERE id = :message_id
                """,
                {
                    "current_category": classification.category,
                    "confidence": classification.confidence,
                    "protected": 1 if classification.protected else 0,
                    "updated_at": now,
                    "message_id": row["id"],
                },
            )
            execute_sql(
                conn,
                """
                INSERT INTO classification_results (
                    message_id, category, confidence, reasons_json, protected,
                    protection_reasons_json, created_at
                ) VALUES (
                    :message_id, :category, :confidence, :reasons_json, :protected,
                    :protection_reasons_json, :created_at
                )
                """,
                {
                    "message_id": row["id"],
                    "category": classification.category,
                    "confidence": classification.confidence,
                    "reasons_json": json.dumps(classification.reasons),
                    "protected": 1 if classification.protected else 0,
                    "protection_reasons_json": json.dumps(
                        classification.protection_reasons
                    ),
                    "created_at": now,
                },
            )
            updated_count += 1

    return {"reclassified_messages": updated_count}


def _default_selected_with_confidence(category: str, confidence: float | None) -> bool:
    if confidence is None:
        return False
    if category in {"bulk_mail", "junk_review", "keep"}:
        return confidence >= 0.80
    if category == "trash":
        return confidence >= 0.95
    return False


def _queue_source_label(source: str | None) -> str | None:
    return QUEUE_SOURCE_LABELS.get(source or "classifier")


def _queue_source_detail_label(source: str | None) -> str | None:
    if source == "rule_keep":
        return "Matched a Keep rule. Left in Gmail Inbox and kept here for review."
    if source == "high_confidence_keep":
        return "Classified as high-confidence Keep. Left in Gmail Inbox and kept here for review."
    if source == "recovered":
        return "Recovered to the Queue for review."
    return None


def get_review_queue(user_id: int | None = None) -> dict:
    with get_connection() as conn:
        accounts = _enabled_mail_accounts(conn, user_id=user_id)

        result_accounts = []
        for account in accounts:
            account_record = MailAccountRecord.from_row(account)
            groups = []
            for category, display_name in CATEGORY_META:
                rows = fetch_all(
                    conn,
                    """
                    SELECT
                        m.*,
                        ma.external_account_email AS normalized_account_email,
                        ma.provider,
                        c.reasons_json,
                        c.protection_reasons_json,
                        c.created_at as classification_created_at
                    FROM messages m
                    JOIN mail_accounts ma ON ma.id = m.mail_account_id
                    LEFT JOIN classification_results c
                      ON c.message_id = m.id
                    WHERE m.mail_account_id = :mail_account_id
                      AND m.reviewed = 0
                      AND m.current_category = :category
                      AND c.id = (
                        SELECT id FROM classification_results
                        WHERE message_id = m.id
                        ORDER BY id DESC LIMIT 1
                    )
                    ORDER BY m.confidence DESC, m.received_at DESC
                    """,
                    {
                        "mail_account_id": account["mail_account_id"],
                        "category": category,
                    },
                ) if account["mail_account_id"] is not None else fetch_all(
                    conn,
                    """
                    SELECT
                        m.*,
                        a.email_address AS normalized_account_email,
                        a.provider,
                        c.reasons_json,
                        c.protection_reasons_json,
                        c.created_at as classification_created_at
                    FROM messages m
                    JOIN accounts a ON a.email_address = m.account_email
                    LEFT JOIN classification_results c
                      ON c.message_id = m.id
                    WHERE m.account_email = :account_email
                      AND m.reviewed = 0
                      AND m.current_category = :category
                      AND c.id = (
                        SELECT id FROM classification_results
                        WHERE message_id = m.id
                        ORDER BY id DESC LIMIT 1
                    )
                    ORDER BY m.confidence DESC, m.received_at DESC
                    """,
                    {
                        "account_email": account["external_account_email"],
                        "category": category,
                    },
                )

                messages = []
                for row in rows:
                    message = ProviderMessageRecord.from_row(row)
                    messages.append(
                        {
                            "id": message.local_message_id,
                            "gmail_message_id": message.provider_message_id,
                            "thread_id": message.provider_thread_id,
                            "account_email": message.account_email,
                            "sender": message.sender,
                            "sender_domain": message.sender_domain,
                            "reply_to": message.reply_to,
                            "subject": message.subject,
                            "received_at": message.received_at,
                            "snippet": message.snippet,
                            "body_preview": message.body_preview,
                            "has_attachments": message.has_attachments,
                            "state_version": row["updated_at"]
                            or row["classification_created_at"],
                            "category": message.category,
                            "confidence": message.confidence,
                            "recommended_action": message.category,
                            "queue_source": row["queue_source"] or "classifier",
                            "queue_source_label": _queue_source_label(row["queue_source"]),
                            "queue_source_detail": _queue_source_detail_label(row["queue_source"]),
                            "default_selected": _default_selected_with_confidence(
                                message.category, message.confidence
                            ),
                            "protected": message.protected,
                            "reasons": json.loads(row["reasons_json"] or "[]"),
                            "protection_reasons": json.loads(
                                row["protection_reasons_json"] or "[]"
                            ),
                        }
                    )
                groups.append(
                    {
                        "category": category,
                        "display_name": display_name,
                        "count": len(messages),
                        "messages": messages,
                    }
                )
            result_accounts.append(
                {
                    "account_email": account_record.account_email,
                    "last_sync_at": account_record.last_sync_at,
                    "groups": groups,
                }
            )
    return {"accounts": result_accounts}


def apply_message_action(
    message_id: int,
    action: str,
    conn=None,
    user_id: int | None = None,
    action_source: str = "manual",
) -> dict | None:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="apply_message_action",
    )
    now = datetime.now(timezone.utc).isoformat()
    if conn is None:
        with get_connection() as owned_conn:
            return apply_message_action(
                message_id,
                action,
                conn=owned_conn,
                user_id=user_id,
                action_source=action_source,
            )

    if user_id is not None and fetch_owned_message(conn, message_id, user_id) is None:
        return None

    plan = plan_message_action(message_id, action, conn=conn, user_id=user_id)
    if plan is None:
        return None
    if not plan.allowed:
        raise UnsafeMessageActionError(f"Unsafe Gmail action plan for message {message_id}")

    message = fetch_one(
        conn,
        "SELECT * FROM messages WHERE id = :message_id",
        {"message_id": message_id},
    )
    insert_action_log(
        conn,
        message_row=message,
        selected_action=action,
        recommended_action=message["current_category"],
        labels_added=plan.labels_to_add,
        labels_removed=plan.labels_to_remove,
        created_at=now,
        action_source=action_source,
    )
    execute_sql(
        conn,
        """
        UPDATE messages
        SET reviewed = 1,
            recovery_pending = 0,
            updated_at = :updated_at,
            current_category = :current_category,
            confidence = confidence
        WHERE id = :message_id
        """,
        {
            "updated_at": now,
            "current_category": action,
            "message_id": message_id,
        },
    )
    return {
        "message_id": message_id,
        "selected_action": action,
        "labels_added": plan.labels_to_add,
        "labels_removed": plan.labels_to_remove,
    }


def apply_selected_actions(items: list[dict], user_id: int | None = None) -> dict:
    user_id = require_explicit_user_id_in_cloud(
        user_id,
        operation="apply_selected_actions",
    )
    applied = []
    failed = []
    for item in items:
        message_id = item["message_id"]
        action = item["action"]
        try:
            result = apply_message_action(message_id, action, user_id=user_id)
        except (GmailReadonlySyncError, ValueError) as error:
            logger.warning(
                "Selected message apply failed for message_id=%s user_id=%s action=%s: %s",
                message_id,
                user_id,
                action,
                error,
            )
            failed.append(
                {
                    "message_id": message_id,
                    "action": action,
                    "reason": str(error) or "Message could not be applied.",
                }
            )
            continue
        if result is None:
            failed.append(
                {
                    "message_id": message_id,
                    "action": action,
                    "reason": "Message is no longer available.",
                }
            )
            continue
        applied.append(result)
    return {
        "applied": applied,
        "failed": failed,
        "applied_count": len(applied),
        "failed_count": len(failed),
    }
