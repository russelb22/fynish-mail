from __future__ import annotations

from _helpers import database
from app.db.foundation_migration import migrate_foundation_schema


def main() -> None:
    database.ensure_database()
    summary = migrate_foundation_schema()

    print("Foundation schema migration complete.")
    print(f"Database: {database.DATABASE_PATH}")
    print(f"Default user id: {summary['default_user_id']}")
    print(f"Mail accounts total: {summary['mail_accounts_total']}")
    print(f"Provider connections total: {summary['provider_connections_total']}")
    print(f"Messages total: {summary['messages_total']}")
    print(f"Rules total: {summary['rules_total']}")
    print(f"Actions log total: {summary['actions_log_total']}")
    print(
        f"Notification settings by user total: {summary['notification_settings_by_user_total']}"
    )
    print(f"Mail accounts backfilled: {summary['mail_accounts_backfilled']}")
    print(
        f"Provider connections backfilled: {summary['provider_connections_backfilled']}"
    )
    print(f"Messages updated: {summary['messages_updated']}")
    print(f"Rules updated: {summary['rules_updated']}")
    print(f"Actions updated: {summary['actions_updated']}")
    print(
        f"Notification settings backfilled: {summary['notification_settings_backfilled']}"
    )


if __name__ == "__main__":
    main()
