from __future__ import annotations

from _helpers import database
from app.db.foundation_validation import validate_foundation_migration


def main() -> int:
    database.ensure_database()
    payload = validate_foundation_migration()

    print("Fynish Foundation Migration Validation")
    print(f"Database: {database.DATABASE_PATH}")
    for _ok, line in payload["results"]:
        print(line)

    summary = payload["summary"]
    print(
        "Summary:"
        f" users/default={summary['default_user_id']},"
        f" accounts={summary['account_count']},"
        f" mail_accounts={summary['mail_account_count']},"
        f" gmail_connections={summary['gmail_connection_count']},"
        f" provider_connections={summary['provider_connection_count']},"
        f" queue_accounts={summary['queue_account_count']},"
        f" queue_messages={summary['queue_message_count']}"
    )
    print(f"Result: {payload['passed']} passed, {payload['failed']} failed")
    return 0 if payload["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
