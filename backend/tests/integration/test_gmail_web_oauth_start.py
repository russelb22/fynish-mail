from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

from app.core import config
from app.db.runtime import fetch_one, get_connection
from app.services.accounts import GmailAccountOwnershipError
from app.services.digest_sender import DigestSenderValidationError
from app.services import gmail_web_oauth


AUTH_HEADERS = {
    "X-Fynish-Authenticated-Email": "friend@example.com",
    "X-Fynish-Authenticated-Name": "Friend User",
    "X-Fynish-Authenticated-Sub": "google-oauth-subject-456",
}


def _write_web_client_config(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "web": {
                    "client_id": "test-client-id.apps.googleusercontent.com",
                    "project_id": "fynish-test",
                    "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                    "token_uri": "https://oauth2.googleapis.com/token",
                    "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
                    "client_secret": "test-client-secret",
                    "redirect_uris": [
                        "https://fynish-backend.example.com/api/accounts/connect-gmail/callback"
                    ],
                }
            }
        )
    )


def test_gmail_web_oauth_start_requires_web_client_config(
    api_client, isolated_db, monkeypatch, tmp_path
):
    missing_path = tmp_path / "missing-web-client.json"
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", missing_path)
    monkeypatch.setattr(
        config,
        "GOOGLE_WEB_OAUTH_CALLBACK_URL",
        "https://fynish-backend.example.com/api/accounts/connect-gmail/callback",
    )

    response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=readonly",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert "Hosted Gmail web OAuth client file not found" in response.json()["detail"]
    assert response.json()["code"] == "gmail_oauth_not_configured"


def test_gmail_web_oauth_start_creates_user_scoped_session(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-backend.example.com/api/accounts/connect-gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=modify",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["session_id"] > 0
    assert payload["state"]
    assert payload["authorization_url"].startswith("https://accounts.google.com/")

    parsed_url = urlparse(payload["authorization_url"])
    query = parse_qs(parsed_url.query)
    assert query["state"] == [payload["state"]]
    assert query["redirect_uri"] == [callback_url]
    assert query["access_type"] == ["offline"]

    with get_connection() as conn:
        session_row = fetch_one(
            conn,
            """
            SELECT s.user_id, s.scope_mode, s.provider, s.status, s.redirect_after, u.email
            FROM oauth_connect_sessions s
            JOIN users u ON u.id = s.user_id
            WHERE s.id = :session_id
            """,
            {"session_id": payload["session_id"]},
        )

    assert session_row is not None
    assert session_row["email"] == "friend@example.com"
    assert session_row["scope_mode"] == "modify"
    assert session_row["provider"] == "gmail"
    assert session_row["status"] == "pending"
    assert session_row["redirect_after"] == "https://fynish-frontend.example.com/?view=accounts"


def test_gmail_web_oauth_start_supports_digest_sender_scope(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-backend.example.com/api/accounts/connect-gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")
    monkeypatch.setattr(config, "GMAIL_SENDER_EMAIL", "digest.sender@example.com")

    response = api_client.get(
        "/api/settings/digest-sender/connect-gmail/start",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    parsed_url = urlparse(payload["authorization_url"])
    query = parse_qs(parsed_url.query)
    assert "https://www.googleapis.com/auth/gmail.send" in query["scope"][0]
    assert query["login_hint"] == ["digest.sender@example.com"]

    with get_connection() as conn:
        session_row = fetch_one(
            conn,
            """
            SELECT scope_mode, redirect_after
            FROM oauth_connect_sessions
            WHERE id = :session_id
            """,
            {"session_id": payload["session_id"]},
        )

    assert session_row is not None
    assert session_row["scope_mode"] == "send"
    assert session_row["redirect_after"] == "https://fynish-frontend.example.com/?view=settings"


def test_gmail_web_oauth_start_rejects_unsupported_mode_with_code(
    api_client,
    isolated_db,
    monkeypatch,
    tmp_path,
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)

    response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=sideways",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unsupported Gmail connect mode: sideways"
    assert response.json()["code"] == "gmail_oauth_unsupported_mode"


def test_gmail_web_oauth_callback_completes_connection_and_stores_db_token(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-frontend.example.com/auth/gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    class _FakeCredentials:
        scopes = ["https://www.googleapis.com/auth/gmail.modify"]

        def to_json(self):
            return json.dumps({"refresh_token": "refresh-123", "token": "token-xyz"})

    monkeypatch.setattr(
        gmail_web_oauth,
        "_exchange_code_for_credentials",
        lambda **kwargs: _FakeCredentials(),
    )
    monkeypatch.setattr(
        gmail_web_oauth,
        "_fetch_gmail_profile_email",
        lambda credentials: "connected@example.com",
    )

    start_response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=modify",
        headers=AUTH_HEADERS,
    )
    state = start_response.json()["state"]

    response = api_client.get(
        f"/api/accounts/connect-gmail/callback?state={state}&code=auth-code-123",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["account"]["email_address"] == "connected@example.com"
    assert payload["account"]["provider"] == "gmail_readonly"
    assert "gmail_connect=success" in payload["redirect_url"]
    assert "connected%40example.com" in payload["redirect_url"]

    with get_connection() as conn:
        session_row = fetch_one(
            conn,
            "SELECT status, metadata_json, consumed_at FROM oauth_connect_sessions WHERE oauth_state = :state",
            {"state": state},
        )
        provider_row = fetch_one(
            conn,
            """
            SELECT pc.metadata_json, pc.scopes_json, ma.user_id, ma.external_account_email
            FROM provider_connections pc
            JOIN mail_accounts ma ON ma.id = pc.mail_account_id
            WHERE ma.external_account_email = :email
            ORDER BY pc.id DESC
            LIMIT 1
            """,
            {"email": "connected@example.com"},
        )

    assert session_row is not None
    assert session_row["status"] == "completed"
    assert session_row["consumed_at"] is not None
    assert json.loads(session_row["metadata_json"])["connected_email"] == "connected@example.com"

    assert provider_row is not None
    assert provider_row["user_id"] > 0
    assert provider_row["external_account_email"] == "connected@example.com"
    assert json.loads(provider_row["scopes_json"]) == ["https://www.googleapis.com/auth/gmail.modify"]
    provider_metadata = json.loads(provider_row["metadata_json"])
    stored_token = json.loads(provider_metadata["gmail_authorized_user_json"])
    assert stored_token["refresh_token"] == "refresh-123"


def test_gmail_web_oauth_callback_stores_digest_sender_without_mail_account(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-frontend.example.com/auth/gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    class _FakeCredentials:
        scopes = ["https://www.googleapis.com/auth/gmail.send"]

        def to_json(self):
            return json.dumps({"refresh_token": "refresh-send", "token": "token-send"})

    monkeypatch.setattr(
        gmail_web_oauth,
        "_exchange_code_for_credentials",
        lambda **kwargs: _FakeCredentials(),
    )
    monkeypatch.setattr(
        gmail_web_oauth,
        "_fetch_google_userinfo_email",
        lambda credentials: "digest.sender@example.com",
    )

    start_response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=send",
        headers=AUTH_HEADERS,
    )
    state = start_response.json()["state"]

    response = api_client.get(
        f"/api/accounts/connect-gmail/callback?state={state}&code=auth-code-123",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 200
    payload = response.json()
    assert "account" not in payload
    assert payload["digest_sender"]["email_address"] == "digest.sender@example.com"
    assert payload["digest_sender"]["has_send_scope"] is True

    with get_connection() as conn:
        mail_account_row = fetch_one(
            conn,
            "SELECT id FROM mail_accounts WHERE external_account_email = :email",
            {"email": "digest.sender@example.com"},
        )
        sender_row = fetch_one(
            conn,
            """
            SELECT scopes_json, metadata_json
            FROM digest_sender_connections
            WHERE email_address = :email
            """,
            {"email": "digest.sender@example.com"},
        )

    assert mail_account_row is None
    assert sender_row is not None
    assert json.loads(sender_row["scopes_json"]) == ["https://www.googleapis.com/auth/gmail.send"]
    stored_token = json.loads(json.loads(sender_row["metadata_json"])["gmail_authorized_user_json"])
    assert stored_token["refresh_token"] == "refresh-send"


def test_gmail_web_oauth_callback_reports_missing_digest_sender_send_scope(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-frontend.example.com/auth/gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    def raise_scope_warning(**kwargs):
        raise Warning(
            "Scope has changed from gmail.send userinfo.email openid to userinfo.email openid."
        )

    monkeypatch.setattr(
        gmail_web_oauth,
        "_exchange_code_for_credentials",
        raise_scope_warning,
    )

    start_response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=send",
        headers=AUTH_HEADERS,
    )
    state = start_response.json()["state"]

    response = api_client.get(
        f"/api/accounts/connect-gmail/callback?state={state}&code=auth-code-123",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Gmail send permission was not granted. Reconnect the digest sender "
        "and approve Gmail send access."
    )
    assert response.json()["code"] == "gmail_oauth_missing_scope"

    with get_connection() as conn:
        session_row = fetch_one(
            conn,
            "SELECT status, metadata_json, consumed_at FROM oauth_connect_sessions WHERE oauth_state = :state",
            {"state": state},
        )
        sender_row = fetch_one(
            conn,
            "SELECT id FROM digest_sender_connections WHERE email_address = :email",
            {"email": "digest.sender@example.com"},
        )

    assert session_row is not None
    assert session_row["status"] == "failed"
    assert session_row["consumed_at"] is not None
    assert json.loads(session_row["metadata_json"])["reason"] == "missing_required_scope"
    assert sender_row is None


def test_gmail_web_oauth_callback_rejects_mismatched_signed_in_user(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-frontend.example.com/auth/gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    start_response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=readonly",
        headers=AUTH_HEADERS,
    )
    state = start_response.json()["state"]

    response = api_client.get(
        f"/api/accounts/connect-gmail/callback?state={state}&code=auth-code-123",
        headers={
            "X-Fynish-Authenticated-Email": "other@example.com",
            "X-Fynish-Authenticated-Name": "Other User",
            "X-Fynish-Authenticated-Sub": "google-oauth-subject-999",
        },
    )

    assert response.status_code == 400
    assert "does not belong to the currently signed-in Fynish user" in response.json()["detail"]
    assert response.json()["code"] == "google_oauth_session_invalid"


def test_gmail_web_oauth_callback_reports_account_already_connected_code(
    api_client,
    isolated_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.routes.complete_gmail_web_oauth",
        lambda **kwargs: SimpleNamespace(
            scope_mode="modify",
            email_address="owner@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.modify"],
            token_json="{}",
            user_id=1,
            redirect_url="https://fynish-frontend.example.com/?view=accounts",
        ),
    )

    def fail_connect(**kwargs):
        raise GmailAccountOwnershipError(
            "This Gmail account is already connected to a different Fynish user."
        )

    monkeypatch.setattr("app.api.routes.connect_gmail_account_from_web_oauth", fail_connect)

    response = api_client.get(
        "/api/accounts/connect-gmail/callback?state=test-state&code=auth-code-123",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "This Gmail account is already connected to a different Fynish user."
    )
    assert response.json()["code"] == "gmail_account_already_connected"


def test_gmail_web_oauth_callback_reports_digest_sender_validation_code(
    api_client,
    isolated_db,
    monkeypatch,
):
    monkeypatch.setattr(
        "app.api.routes.complete_gmail_web_oauth",
        lambda **kwargs: SimpleNamespace(
            scope_mode="send",
            email_address="digest.sender@example.com",
            scopes=["https://www.googleapis.com/auth/gmail.send"],
            token_json="{}",
            user_id=1,
            redirect_url="https://fynish-frontend.example.com/?view=settings",
        ),
    )

    def fail_persist(**kwargs):
        raise DigestSenderValidationError(
            "Digest sender OAuth credentials must include Gmail send access."
        )

    monkeypatch.setattr("app.api.routes.persist_gmail_digest_sender", fail_persist)

    response = api_client.get(
        "/api/accounts/connect-gmail/callback?state=test-state&code=auth-code-123",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == (
        "Digest sender OAuth credentials must include Gmail send access."
    )
    assert response.json()["code"] == "digest_sender_validation_failed"


def test_gmail_web_oauth_callback_reports_google_error(
    api_client, isolated_db, monkeypatch, tmp_path
):
    web_client_path = tmp_path / "google-web-client.json"
    _write_web_client_config(web_client_path)
    callback_url = "https://fynish-frontend.example.com/auth/gmail/callback"

    monkeypatch.setattr(config, "APP_ENV", "cloud")
    monkeypatch.setattr(config, "GOOGLE_WEB_CLIENT_SECRETS_PATH", web_client_path)
    monkeypatch.setattr(config, "GOOGLE_WEB_OAUTH_CALLBACK_URL", callback_url)
    monkeypatch.setattr(config, "FRONTEND_URL", "https://fynish-frontend.example.com")

    start_response = api_client.get(
        "/api/accounts/connect-gmail/start?mode=readonly",
        headers=AUTH_HEADERS,
    )
    state = start_response.json()["state"]

    response = api_client.get(
        f"/api/accounts/connect-gmail/callback?state={state}&error=access_denied",
        headers=AUTH_HEADERS,
    )

    assert response.status_code == 400
    assert "Google OAuth returned an error: access_denied" in response.json()["detail"]
    assert response.json()["code"] == "google_oauth_denied"
