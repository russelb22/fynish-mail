from __future__ import annotations

import json

from app.services import review_queue
from app.db.database import get_connection
from app.db.foundation_migration import migrate_foundation_schema
from app.services.gmail_readonly import GmailReadonlySyncError
from app.services.gmail_write_executor import GmailExecutionResult
from app.services.classifier import ClassificationResult
from app.services.review_queue import get_review_queue


def _all_messages(queue: dict) -> list[dict]:
    messages = []
    for account in queue["accounts"]:
        for group in account["groups"]:
            messages.extend(group["messages"])
    return messages


def _message_by_subject(queue: dict, subject: str) -> dict:
    for message in _all_messages(queue):
        if message["subject"] == subject:
            return message
    raise AssertionError(f"Missing subject {subject}")


def test_queue_is_grouped_by_account_and_category_order(seeded_db):
    queue = get_review_queue()
    assert [account["account_email"] for account in queue["accounts"]] == [
        "family@example.net",
        "personal@example.com",
        "work@example.com",
    ]
    assert [group["category"] for group in queue["accounts"][0]["groups"]] == [
        "trash",
        "junk_review",
        "bulk_mail",
        "needs_review",
        "keep",
    ]


def test_default_selection_thresholds_are_enforced(seeded_db):
    queue = get_review_queue()
    assert _message_by_subject(queue, "Your daily digest")["default_selected"] is True
    assert (
        _message_by_subject(queue, "Urgent account reset requested")["default_selected"]
        is False
    )
    assert _message_by_subject(queue, "Photos from Sunday dinner")["default_selected"] is True
    assert (
        _message_by_subject(queue, "Final notice: claim your package today")[
            "default_selected"
        ]
        is False
    )


def test_within_category_messages_are_sorted_by_confidence_then_received_at(seeded_db):
    queue = get_review_queue()
    personal_bulk = next(
        group
        for account in queue["accounts"]
        if account["account_email"] == "personal@example.com"
        for group in account["groups"]
        if group["category"] == "bulk_mail"
    )
    confidences = [message["confidence"] for message in personal_bulk["messages"]]
    assert confidences == sorted(confidences, reverse=True)


def test_queue_reads_follow_mail_account_id_not_legacy_account_email(seeded_db):
    migrate_foundation_schema()
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT id, mail_account_id
            FROM messages
            WHERE subject = ?
            """,
            ("Your daily digest",),
        ).fetchone()
        conn.execute(
            """
            UPDATE messages
            SET account_email = ?
            WHERE id = ?
            """,
            ("stale-address@example.com", row["id"]),
        )

    queue = get_review_queue()
    message = _message_by_subject(queue, "Your daily digest")

    assert message["account_email"] == "personal@example.com"


def test_provider_messages_accept_db_backed_gmail_tokens(monkeypatch):
    captured = {}

    class _FakeAdapter:
        def list_unread_inbox_messages(self, reference, *, max_results):
            captured["reference"] = reference
            captured["max_results"] = max_results
            return [{"id": "msg-1"}]

    monkeypatch.setattr(review_queue, "get_mail_provider_adapter", lambda provider: _FakeAdapter())

    account = {
        "provider": "gmail_readonly",
        "provider_connection_id": 42,
        "token_path": None,
        "metadata_json": '{"gmail_authorized_user_json":"{\\"refresh_token\\":\\"abc\\"}"}',
        "external_account_email": "friend@example.com",
    }

    messages = review_queue._provider_messages_for_account(None, account)

    assert messages == [{"id": "msg-1"}]
    assert captured["reference"].provider_connection_id == 42
    assert captured["reference"].token_path is None


def test_sync_unread_messages_skips_revoked_gmail_account_and_records_failure(
    isolated_db, monkeypatch
):
    now = "2026-05-25T17:00:00+00:00"
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            ("beta.user@example.com", "Kim", now, now),
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            ("beta.user@example.com",),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, last_sync_at, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', NULL, ?, ?)
            """,
            (user_id, "beta.user@example.com", "Kim Gmail", now, now),
        )
        mail_account_id = conn.execute(
            "SELECT id FROM mail_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, NULL, '[]', '{}', ?, ?)
            """,
            (mail_account_id, now, now),
        )
        provider_connection_id = conn.execute(
            "SELECT id FROM provider_connections WHERE mail_account_id = ?",
            (mail_account_id,),
        ).fetchone()["id"]

    account = {
        "provider": "gmail_readonly",
        "provider_connection_id": provider_connection_id,
        "token_path": None,
        "metadata_json": "{}",
        "external_account_email": "beta.user@example.com",
        "mail_account_id": mail_account_id,
        "legacy_account_id": None,
    }

    monkeypatch.setattr(review_queue, "_enabled_mail_accounts", lambda conn, user_id=None: [account])
    monkeypatch.setattr(review_queue, "_load_rules", lambda conn: [])
    monkeypatch.setattr(review_queue, "_history_counters", lambda conn, user_id=None: ({}, {}))
    monkeypatch.setattr(review_queue, "_ensure_sync_account_provider_records", lambda conn, account, now: account)

    def fake_provider_messages(conn, account):
        raise GmailReadonlySyncError(
            "Stored Gmail credentials were expired or revoked. Reconnect the account."
        )

    monkeypatch.setattr(review_queue, "_provider_messages_for_account", fake_provider_messages)

    result = review_queue.sync_unread_messages(allow_global=True)

    assert result == {
        "synced_messages": 0,
        "reconciled_messages": 0,
        "auto_applied_messages": 0,
        "failed_accounts": [
            {
                "account_email": "beta.user@example.com",
                "provider": "gmail_readonly",
                "reason": "Stored Gmail credentials were expired or revoked. Reconnect the account.",
            }
        ],
    }

    with get_connection() as conn:
        row = conn.execute(
            "SELECT metadata_json FROM provider_connections WHERE id = ?",
            (provider_connection_id,),
        ).fetchone()

    metadata = json.loads(row["metadata_json"])
    assert metadata["reconnect_required"] == 1
    assert metadata["last_sync_error"] == (
        "Stored Gmail credentials were expired or revoked. Reconnect the account."
    )
    assert metadata["last_sync_error_at"]


def _seed_gmail_account_for_auto_clean(now: str = "2026-05-25T18:00:00+00:00") -> int:
    with get_connection() as conn:
        conn.execute(
            """
            INSERT INTO users (email, display_name, status, created_at, updated_at)
            VALUES (?, ?, 'active', ?, ?)
            """,
            ("owner@example.com", "Owner", now, now),
        )
        user_id = conn.execute(
            "SELECT id FROM users WHERE email = ?",
            ("owner@example.com",),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO accounts (email_address, enabled, provider, created_at, updated_at)
            VALUES (?, 1, 'gmail_readonly', ?, ?)
            """,
            ("owner@example.com", now, now),
        )
        conn.execute(
            """
            INSERT INTO mail_accounts (
                user_id, provider, external_account_email, display_name,
                enabled, status, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', ?, ?, 1, 'active', ?, ?)
            """,
            (user_id, "owner@example.com", "Owner Gmail", now, now),
        )
        mail_account_id = conn.execute(
            "SELECT id FROM mail_accounts WHERE user_id = ?",
            (user_id,),
        ).fetchone()["id"]
        conn.execute(
            """
            INSERT INTO provider_connections (
                mail_account_id, provider, connection_type, credentials_ref,
                token_path, scopes_json, metadata_json, created_at, updated_at
            ) VALUES (?, 'gmail_readonly', 'oauth', NULL, NULL, ?, ?, ?, ?)
            """,
            (
                mail_account_id,
                '["https://www.googleapis.com/auth/gmail.modify"]',
                '{"gmail_authorized_user_json":"{\\"refresh_token\\":\\"abc\\"}"}',
                now,
                now,
            ),
        )
    return int(user_id)


def _provider_bulk_message() -> dict:
    return {
        "gmail_message_id": "bulk-100",
        "gmail_thread_id": "thread-bulk-100",
        "sender": "Deals <deals@example.com>",
        "reply_to": "deals@example.com",
        "recipient_to": "owner@example.com",
        "recipient_cc": "",
        "subject": "Weekly newsletter sale",
        "received_at": "2026-05-25T17:30:00+00:00",
        "snippet": "Save on this weekly newsletter promotion.",
        "body_preview": "Save on this weekly newsletter promotion. Unsubscribe here.",
        "gmail_labels": ["INBOX", "UNREAD"],
        "headers": {},
        "has_attachments": 0,
    }


def test_high_confidence_auto_clean_processes_bulk_when_enabled(
    isolated_db,
    monkeypatch,
):
    user_id = _seed_gmail_account_for_auto_clean()
    executed_message_ids: list[int] = []

    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED", True)
    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD", 0.85)
    monkeypatch.setattr(review_queue, "_provider_messages_for_account", lambda conn, account: [_provider_bulk_message()])
    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="bulk_mail",
            confidence=0.91,
            reasons=["High-confidence bulk test fixture"],
            protected=False,
            protection_reasons=[],
            matched_rule_ids=[],
        ),
    )

    def fake_execute_message_action(message_id, action, **_):
        executed_message_ids.append(message_id)
        return GmailExecutionResult(
            message_id=message_id,
            gmail_message_id="bulk-100",
            account_email="owner@example.com",
            selected_action=action,
            status="executed",
            executed=True,
            allowed=True,
            live_writes_enabled=True,
            oauth_scope_ready=True,
            labels_added=["Fynish/Bulk Mail"],
            labels_removed=["INBOX"],
            response_label_ids=["UNREAD", "Fynish/Bulk Mail"],
            notes=["test auto-clean"],
        )

    monkeypatch.setattr(review_queue, "execute_message_action", fake_execute_message_action)

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["synced_messages"] == 1
    assert result["auto_applied_messages"] == 1
    assert len(executed_message_ids) == 1
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed, current_category
            FROM messages
            WHERE provider_message_id = 'bulk-100'
            """
        ).fetchone()
        action_row = conn.execute(
            """
            SELECT selected_action, action_source, provider_labels_removed_json
            FROM actions_log
            WHERE provider_message_id = 'bulk-100'
            """
        ).fetchone()

    assert row["reviewed"] == 1
    assert row["current_category"] == "bulk_mail"
    assert action_row["selected_action"] == "bulk_mail"
    assert action_row["action_source"] == "high_confidence_auto_clean"
    assert json.loads(action_row["provider_labels_removed_json"]) == ["INBOX"]


def test_keep_rule_match_remains_visible_as_auto_keep(isolated_db, monkeypatch):
    user_id = _seed_gmail_account_for_auto_clean()
    executed_message_ids: list[int] = []

    monkeypatch.setattr(review_queue, "_provider_messages_for_account", lambda conn, account: [_provider_bulk_message()])
    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="keep",
            confidence=1.0,
            reasons=["Matched Always Keep rule"],
            protected=False,
            protection_reasons=[],
            matched_rule_ids=[123],
        ),
    )
    monkeypatch.setattr(
        review_queue,
        "execute_message_action",
        lambda message_id, action, **_: executed_message_ids.append(message_id),
    )

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["synced_messages"] == 1
    assert result["auto_applied_messages"] == 0
    assert executed_message_ids == []
    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed, current_category, queue_source, queue_source_detail
            FROM messages
            WHERE provider_message_id = 'bulk-100'
            """
        ).fetchone()
        action_row = conn.execute(
            """
            SELECT id
            FROM actions_log
            WHERE provider_message_id = 'bulk-100'
            """
        ).fetchone()

    assert row["reviewed"] == 0
    assert row["current_category"] == "keep"
    assert row["queue_source"] == "rule_keep"
    assert json.loads(row["queue_source_detail"]) == {"matched_rule_ids": [123]}
    assert action_row is None

    queue = get_review_queue(user_id=user_id)
    message = _message_by_subject(queue, "Weekly newsletter sale")
    assert message["recommended_action"] == "keep"
    assert message["queue_source"] == "rule_keep"
    assert message["queue_source_label"] == "Auto-Keep"


def test_high_confidence_auto_clean_respects_threshold_and_protection(
    isolated_db,
    monkeypatch,
):
    user_id = _seed_gmail_account_for_auto_clean()
    executed_message_ids: list[int] = []

    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED", True)
    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD", 0.85)
    monkeypatch.setattr(review_queue, "_provider_messages_for_account", lambda conn, account: [_provider_bulk_message()])
    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="bulk_mail",
            confidence=0.84,
            reasons=["Below auto-clean threshold"],
            protected=False,
            protection_reasons=[],
            matched_rule_ids=[],
        ),
    )
    monkeypatch.setattr(
        review_queue,
        "execute_message_action",
        lambda message_id, action, **_: executed_message_ids.append(message_id),
    )

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["auto_applied_messages"] == 0
    assert executed_message_ids == []
    with get_connection() as conn:
        row = conn.execute(
            "SELECT reviewed FROM messages WHERE provider_message_id = 'bulk-100'"
        ).fetchone()
    assert row["reviewed"] == 0

    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="junk_review",
            confidence=0.99,
            reasons=["High confidence but protected"],
            protected=True,
            protection_reasons=["Protected test fixture"],
            matched_rule_ids=[],
        ),
    )

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["auto_applied_messages"] == 0
    assert executed_message_ids == []


def test_high_confidence_auto_clean_respects_account_switch(
    isolated_db,
    monkeypatch,
):
    user_id = _seed_gmail_account_for_auto_clean()
    executed_message_ids: list[int] = []

    with get_connection() as conn:
        conn.execute(
            """
            UPDATE mail_accounts
            SET high_confidence_auto_clean_enabled = 0
            WHERE external_account_email = 'owner@example.com'
            """
        )

    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED", True)
    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_THRESHOLD", 0.85)
    monkeypatch.setattr(review_queue, "_provider_messages_for_account", lambda conn, account: [_provider_bulk_message()])
    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="bulk_mail",
            confidence=0.99,
            reasons=["High confidence but account disabled"],
            protected=False,
            protection_reasons=[],
            matched_rule_ids=[],
        ),
    )
    monkeypatch.setattr(
        review_queue,
        "execute_message_action",
        lambda message_id, action, **_: executed_message_ids.append(message_id),
    )

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["auto_applied_messages"] == 0
    assert executed_message_ids == []


def test_high_confidence_auto_clean_is_disabled_by_default(
    isolated_db,
    monkeypatch,
):
    user_id = _seed_gmail_account_for_auto_clean()
    executed_message_ids: list[int] = []

    monkeypatch.setattr(review_queue, "AUTO_CLEAN_HIGH_CONFIDENCE_ENABLED", False)
    monkeypatch.setattr(review_queue, "_provider_messages_for_account", lambda conn, account: [_provider_bulk_message()])
    monkeypatch.setattr(
        review_queue,
        "classify_message",
        lambda **_: ClassificationResult(
            category="junk_review",
            confidence=0.99,
            reasons=["High confidence junk"],
            protected=False,
            protection_reasons=[],
            matched_rule_ids=[],
        ),
    )
    monkeypatch.setattr(
        review_queue,
        "execute_message_action",
        lambda message_id, action, **_: executed_message_ids.append(message_id),
    )

    result = review_queue.sync_unread_messages(user_id=user_id)

    assert result["auto_applied_messages"] == 0
    assert executed_message_ids == []
