from __future__ import annotations

from app.db.database import get_connection
from app.services.review_queue import get_review_queue, sync_unread_messages
from app.services.rules import create_rule, delete_rule, list_rules, update_rule


def test_create_rule_normalizes_pattern_and_is_listed(isolated_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "Events-Example.COM",
            "action": "bulk_mail",
        }
    )
    assert rule["pattern"] == "events-example.com"
    rules = list_rules()
    assert rules[0]["id"] == rule["id"]


def test_create_rule_populates_user_and_mail_account_id_after_migration(seeded_db):
    from app.db.foundation_migration import DEFAULT_LOCAL_OWNER_EMAIL, migrate_foundation_schema

    migrate_foundation_schema()
    rule = create_rule(
        {
            "scope": "account",
            "account_email": "personal@example.com",
            "rule_type": "domain",
            "pattern": "substack.com",
            "action": "junk_review",
        }
    )

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT r.user_id, r.mail_account_id, u.email AS user_email, ma.external_account_email
            FROM rules r
            JOIN users u ON u.id = r.user_id
            LEFT JOIN mail_accounts ma ON ma.id = r.mail_account_id
            WHERE r.id = ?
            """,
            (rule["id"],),
        ).fetchone()

    assert row["user_email"] == DEFAULT_LOCAL_OWNER_EMAIL
    assert row["external_account_email"] == "personal@example.com"


def test_create_rule_populates_created_from_mail_account_id_from_source_message(seeded_db):
    from app.db.foundation_migration import migrate_foundation_schema

    migrate_foundation_schema()
    with get_connection() as conn:
        source_message = conn.execute(
            """
            SELECT id, mail_account_id
            FROM messages
            WHERE subject = ?
            """,
            ("Weekly digest: patio, paint, and repair ideas",),
        ).fetchone()

    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "fixer-mailer.com",
            "action": "bulk_mail",
            "source_message_id": int(source_message["id"]),
        }
    )

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT created_from_mail_account_id
            FROM rules
            WHERE id = ?
            """,
            (rule["id"],),
        ).fetchone()

    assert row["created_from_mail_account_id"] == source_message["mail_account_id"]


def test_create_rule_reuses_enabled_identical_rule(isolated_db):
    first = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "substack.com",
            "action": "junk_review",
        }
    )

    second = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": " Substack.com ",
            "action": "junk_review",
        }
    )

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM rules
            WHERE pattern = 'substack.com'
              AND rule_type = 'domain'
              AND action = 'junk_review'
            """
        ).fetchone()

    assert second["id"] == first["id"]
    assert row["count"] == 1


def test_create_rule_reenables_disabled_identical_rule(isolated_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "grubhub.com",
            "action": "junk_review",
        }
    )
    update_rule(rule["id"], {"enabled": False})

    restored = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": " GrubHub.com ",
            "action": "junk_review",
        }
    )

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT COUNT(*) AS count, SUM(enabled) AS enabled_count
            FROM rules
            WHERE pattern = 'grubhub.com'
              AND rule_type = 'domain'
              AND action = 'junk_review'
            """
        ).fetchone()

    assert restored["id"] == rule["id"]
    assert restored["enabled"] is True
    assert row["count"] == 1
    assert row["enabled_count"] == 1


def test_disabled_rule_no_longer_applies(isolated_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "events-example.com",
            "action": "bulk_mail",
        }
    )
    update_rule(rule["id"], {"enabled": False})
    sync_unread_messages()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT match_count FROM rules WHERE id = ?",
            (rule["id"],),
        ).fetchone()
    assert row["match_count"] == 0


def test_rule_match_count_increments_when_rule_matches(isolated_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "events-example.com",
            "action": "bulk_mail",
        }
    )
    sync_unread_messages()
    with get_connection() as conn:
        row = conn.execute(
            "SELECT match_count, last_matched_at FROM rules WHERE id = ?",
            (rule["id"],),
        ).fetchone()
    assert row["match_count"] >= 1
    assert row["last_matched_at"] is not None


def test_matched_bulk_rule_auto_applies_and_skips_queue(seeded_db):
    create_rule(
        {
            "scope": "global",
            "rule_type": "domain",
            "pattern": "events-example.com",
            "action": "bulk_mail",
        }
    )

    sync_unread_messages()
    queue = get_review_queue()

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT reviewed, current_category
            FROM messages
            WHERE sender_domain = 'events-example.com'
            LIMIT 1
            """
        ).fetchone()
        action_log_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM actions_log
            WHERE account_email = 'work@example.com'
              AND selected_action = 'bulk_mail'
            """
        ).fetchone()

    assert row["reviewed"] == 1
    assert row["current_category"] == "bulk_mail"
    assert action_log_count["count"] >= 1
    assert not any(
        message["sender_domain"] == "events-example.com"
        for account in queue["accounts"]
        for group in account["groups"]
        for message in group["messages"]
    )


def test_matched_keep_rule_remains_visible_without_relogging_on_repeat_sync(isolated_db):
    create_rule(
            {
                "scope": "global",
                "rule_type": "sender",
                "pattern": "alerts@example.net",
                "action": "keep",
            }
        )

    sync_unread_messages()
    sync_unread_messages()

    with get_connection() as conn:
        action_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM actions_log
            WHERE account_email = 'personal@example.com'
              AND selected_action = 'keep'
            """
        ).fetchone()
        message_row = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM messages
            WHERE account_email = 'personal@example.com'
              AND sender LIKE '%alerts@example.net%'
              AND current_category = 'keep'
              AND reviewed = 0
            """
        ).fetchone()

    assert action_row["count"] == 0
    assert message_row["count"] == 1


def test_delete_rule_removes_it(isolated_db):
    rule = create_rule(
        {
            "scope": "global",
            "rule_type": "sender",
            "pattern": "alerts@example.net",
            "action": "keep",
        }
    )
    assert delete_rule(rule["id"]) is True
    assert list_rules() == []
