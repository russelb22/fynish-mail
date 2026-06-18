from __future__ import annotations

from _helpers import count_accounts, count_messages, count_rules, reset_database, sync_mock_messages


def main() -> None:
    path = reset_database(remove_existing=True)
    sync_mock_messages()
    print(f"Reset database: {path}")
    print(f"Seeded accounts: {count_accounts()}")
    print(f"Seeded mock messages: {count_messages()}")
    print(f"Seeded rules: {count_rules()}")
    print("Done.")


if __name__ == "__main__":
    main()
