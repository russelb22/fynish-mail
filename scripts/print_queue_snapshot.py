from __future__ import annotations

from _helpers import dump_json, queue_snapshot, reset_database, sync_mock_messages


def main() -> None:
    reset_database(remove_existing=True)
    sync_mock_messages()
    queue = queue_snapshot()

    for account in queue["accounts"]:
        print(f"Account: {account['account_email']}")
        for group in account["groups"]:
            print(f"  {group['display_name']}: {group['count']}")
            for message in group["messages"][:5]:
                print(
                    f"    {message['confidence']:.2f} | {message['sender_domain']} | {message['subject']}"
                )
    print("")
    print("Raw JSON")
    print(dump_json(queue))


if __name__ == "__main__":
    main()
