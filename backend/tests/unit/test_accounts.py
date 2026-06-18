from __future__ import annotations

import json
from pathlib import Path

from app.db.database import get_connection
from app.services import accounts as accounts_service


class _FakeUsersResource:
    def __init__(self, email_address: str):
        self.email_address = email_address

    def getProfile(self, userId: str):
        assert userId == "me"
        return self

    def execute(self):
        return {"emailAddress": self.email_address}


class _FakeService:
    def __init__(self, email_address: str):
        self.email_address = email_address

    def users(self):
        return _FakeUsersResource(self.email_address)


def test_restore_gmail_accounts_from_saved_tokens_rehydrates_account_rows(
    isolated_db,
    monkeypatch,
    tmp_path: Path,
):
    token_dir = tmp_path / "google_tokens"
    token_dir.mkdir()
    token_path = token_dir / "owner_example.com.json"
    token_path.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.modify"]}))

    monkeypatch.setattr(accounts_service, "GOOGLE_TOKEN_DIR", token_dir)
    monkeypatch.setattr(
        accounts_service,
        "build_service_from_token_path",
        lambda token_path, scopes=None: _FakeService("owner@example.com"),
    )

    restored = accounts_service.restore_gmail_accounts_from_saved_tokens()

    assert len(restored) == 1
    assert restored[0]["email_address"] == "owner@example.com"
    assert restored[0]["provider"] == "gmail_readonly"

    with get_connection() as conn:
        account = conn.execute(
            "SELECT provider, enabled FROM accounts WHERE email_address = ?",
            ("owner@example.com",),
        ).fetchone()
        connection = conn.execute(
            """
            SELECT token_path, scopes_json
            FROM gmail_account_connections g
            JOIN accounts a ON a.id = g.account_id
            WHERE a.email_address = ?
            """,
            ("owner@example.com",),
        ).fetchone()
        mail_account = conn.execute(
            "SELECT provider, external_account_email FROM mail_accounts WHERE external_account_email = ?",
            ("owner@example.com",),
        ).fetchone()

    assert account["provider"] == "gmail_readonly"
    assert int(account["enabled"]) == 1
    assert connection["token_path"] == str(token_path)
    assert json.loads(connection["scopes_json"]) == ["https://www.googleapis.com/auth/gmail.modify"]
    assert mail_account["provider"] == "gmail_readonly"
    assert mail_account["external_account_email"] == "owner@example.com"
