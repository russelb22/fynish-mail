from __future__ import annotations

from _helpers import count_accounts, reset_database, sync_mock_messages


def main() -> None:
    reset_database(remove_existing=False)
    result = sync_mock_messages()
    print("Mock sync complete.")
    print(f"Inserted: {result['inserted']}")
    print(f"Skipped duplicates: {result['skipped_duplicates']}")
    print(f"Accounts: {count_accounts()}")


if __name__ == "__main__":
    main()
