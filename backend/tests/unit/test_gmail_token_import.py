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


def test_import_local_gmail_tokens_to_provider_connections_seeds_metadata(
    isolated_db,
    monkeypatch,
    tmp_path: Path,
):
    token_dir = tmp_path / "google_tokens"
    token_dir.mkdir()
    token_path = token_dir / "owner_example.com.json"
    token_path.write_text(json.dumps({"scopes": ["https://www.googleapis.com/auth/gmail.modify"], "refresh_token": "r1"}))

    monkeypatch.setattr(accounts_service, "GOOGLE_TOKEN_DIR", token_dir)
    monkeypatch.setattr(
        accounts_service,
        "build_service_from_token_path",
        lambda token_path, scopes=None: _FakeService("owner@example.com"),
    )

    result = accounts_service.import_local_gmail_tokens_to_provider_connections()

    assert result == {"restored_accounts": 1, "imported_tokens": 1}

    with get_connection() as conn:
        row = conn.execute(
            """
            SELECT pc.metadata_json
            FROM provider_connections pc
            JOIN mail_accounts ma ON ma.id = pc.mail_account_id
            WHERE ma.external_account_email = ?
            """,
            ("owner@example.com",),
        ).fetchone()

    metadata = json.loads(row["metadata_json"])
    assert "gmail_authorized_user_json" in metadata
    stored_token = json.loads(metadata["gmail_authorized_user_json"])
    assert stored_token["refresh_token"] == "r1"
