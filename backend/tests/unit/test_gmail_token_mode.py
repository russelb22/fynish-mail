from __future__ import annotations

import json

import pytest

from app.services import gmail_readonly
from app.services.gmail_token_store import GmailTokenReference


class _FakeCredentials:
    valid = True
    expired = False
    refresh_token = "refresh-1"

    def has_scopes(self, scopes):
        return True

    def refresh(self, request):
        raise AssertionError("refresh should not be called in this unit test")

    def to_json(self):
        return '{"refresh_token":"refresh-1"}'


def test_database_mode_rejects_file_fallback(monkeypatch):
    monkeypatch.setattr(gmail_readonly, "GMAIL_TOKEN_STORAGE_MODE", "database")
    reference = GmailTokenReference(
        provider_connection_id=1,
        token_path="/tmp/fake-token.json",
        metadata_json="{}",
        account_email="owner@example.com",
    )

    with pytest.raises(gmail_readonly.GmailReadonlySyncError):
        gmail_readonly._load_credentials_from_reference(reference)


def test_auto_mode_uses_db_token_blob(monkeypatch):
    monkeypatch.setattr(gmail_readonly, "GMAIL_TOKEN_STORAGE_MODE", "auto")
    monkeypatch.setattr(
        gmail_readonly,
        "_credentials_from_token_json",
        lambda token_json, scopes=None: _FakeCredentials(),
    )
    reference = GmailTokenReference(
        provider_connection_id=1,
        token_path="/tmp/fake-token.json",
        metadata_json=json.dumps({"gmail_authorized_user_json": '{"refresh_token":"refresh-1"}'}),
        account_email="owner@example.com",
    )

    loaded = gmail_readonly._load_credentials_from_reference(reference)

    assert isinstance(loaded, _FakeCredentials)
    assert loaded.refresh_token == "refresh-1"


def test_file_mode_uses_legacy_token_path(monkeypatch):
    monkeypatch.setattr(gmail_readonly, "GMAIL_TOKEN_STORAGE_MODE", "file")
    monkeypatch.setattr(
        gmail_readonly,
        "_load_credentials",
        lambda token_path, scopes=None: ("loaded-from-file", token_path, scopes),
    )
    reference = GmailTokenReference(
        provider_connection_id=1,
        token_path="/tmp/fake-token.json",
        metadata_json="{}",
        account_email="owner@example.com",
    )

    loaded = gmail_readonly._load_credentials_from_reference(reference)

    assert loaded == ("loaded-from-file", "/tmp/fake-token.json", None)
