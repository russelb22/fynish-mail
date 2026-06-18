from __future__ import annotations

import json
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from app.core import config
from app.db.runtime import execute_sql, fetch_one, get_connection, insert_and_return_id


GMAIL_WEB_SCOPE_MODES = {
    "readonly": [
        config.GMAIL_READONLY_SCOPE,
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    "modify": [
        config.GMAIL_MODIFY_SCOPE,
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
    "send": [
        config.GMAIL_SEND_SCOPE,
        "openid",
        "https://www.googleapis.com/auth/userinfo.email",
        "https://www.googleapis.com/auth/userinfo.profile",
    ],
}
OAUTH_SESSION_TTL = timedelta(minutes=10)
GMAIL_OAUTH_DENIED = "google_oauth_denied"
GMAIL_OAUTH_MISSING_SCOPE = "gmail_oauth_missing_scope"
GMAIL_OAUTH_SESSION_INVALID = "google_oauth_session_invalid"
GMAIL_OAUTH_SESSION_EXPIRED = "google_oauth_session_expired"


class GmailWebOAuthNotConfiguredError(RuntimeError):
    pass


class GmailWebOAuthStateError(RuntimeError):
    def __init__(self, message: str, *, code: str | None = None):
        super().__init__(message)
        self.code = code


class GmailWebOAuthModeError(ValueError):
    pass


@dataclass(frozen=True)
class GmailWebOAuthStartResult:
    authorization_url: str
    oauth_state: str
    session_id: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _accounts_return_url() -> str:
    return config.FRONTEND_URL.rstrip("/") + "/?view=accounts"


def _settings_return_url() -> str:
    return config.FRONTEND_URL.rstrip("/") + "/?view=settings"


def _return_url_for_scope_mode(scope_mode: str) -> str:
    if scope_mode == "send":
        return _settings_return_url()
    return _accounts_return_url()


def _web_client_secrets_path() -> Path:
    return config.GOOGLE_WEB_CLIENT_SECRETS_PATH


def _load_web_client_config() -> dict:
    path = _web_client_secrets_path()
    if not path.exists():
        raise GmailWebOAuthNotConfiguredError(
            f"Hosted Gmail web OAuth client file not found at {path}"
        )

    try:
        payload = json.loads(path.read_text())
    except json.JSONDecodeError as error:
        raise GmailWebOAuthNotConfiguredError(
            f"Hosted Gmail web OAuth client file at {path} is not valid JSON"
        ) from error

    web_config = payload.get("web")
    if not isinstance(web_config, dict):
        raise GmailWebOAuthNotConfiguredError(
            "Hosted Gmail web OAuth requires a Google OAuth web client config under the 'web' key."
        )

    return payload


def _resolve_scopes(mode: str) -> list[str]:
    scopes = GMAIL_WEB_SCOPE_MODES.get(mode)
    if scopes is None:
        raise GmailWebOAuthModeError(f"Unsupported Gmail connect mode: {mode}")
    return scopes


def _required_scope_for_mode(mode: str) -> str | None:
    if mode == "send":
        return config.GMAIL_SEND_SCOPE
    if mode == "modify":
        return config.GMAIL_MODIFY_SCOPE
    if mode == "readonly":
        return config.GMAIL_READONLY_SCOPE
    return None


def _missing_scope_message(mode: str, required_scope: str) -> str:
    if mode == "send":
        return (
            "Gmail send permission was not granted. Reconnect the digest sender "
            "and approve Gmail send access."
        )
    return (
        f"Google OAuth did not grant the required scope {required_scope}. "
        "Reconnect the Gmail account and approve the requested access."
    )


def _serialize_redirect(
    *,
    redirect_after: str,
    status: str,
    message: str,
    email_address: str | None = None,
) -> str:
    from urllib.parse import urlencode, urlparse, parse_qsl, urlunparse

    parsed = urlparse(redirect_after)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["gmail_connect"] = status
    query["gmail_message"] = message
    if email_address:
        query["gmail_account"] = email_address
    return urlunparse(parsed._replace(query=urlencode(query)))


def _cleanup_expired_sessions(conn, *, now_iso: str) -> None:
    execute_sql(
        conn,
        """
        UPDATE oauth_connect_sessions
        SET status = 'expired'
        WHERE status = 'pending' AND expires_at < :now
        """,
        {"now": now_iso},
    )


def _mark_session_status(
    conn,
    *,
    oauth_state: str,
    status: str,
    metadata: dict | None = None,
    consumed: bool = False,
) -> None:
    params = {
        "oauth_state": oauth_state,
        "status": status,
        "metadata_json": json.dumps(metadata or {}, sort_keys=True),
        "consumed_at": _now().isoformat() if consumed else None,
    }
    execute_sql(
        conn,
        """
        UPDATE oauth_connect_sessions
        SET status = :status,
            metadata_json = :metadata_json,
            consumed_at = :consumed_at
        WHERE oauth_state = :oauth_state
        """,
        params,
    )


def _create_oauth_connect_session(
    *,
    user_id: int,
    scope_mode: str,
    redirect_after: str,
) -> tuple[int, str]:
    now = _now()
    now_iso = now.isoformat()
    expires_at = (now + OAUTH_SESSION_TTL).isoformat()
    oauth_state = secrets.token_urlsafe(32)

    with get_connection() as conn:
        _cleanup_expired_sessions(conn, now_iso=now_iso)
        session_id = insert_and_return_id(
            conn,
            """
            INSERT INTO oauth_connect_sessions (
                user_id,
                provider,
                scope_mode,
                oauth_state,
                redirect_after,
                status,
                metadata_json,
                created_at,
                expires_at,
                consumed_at
            ) VALUES (
                :user_id,
                'gmail',
                :scope_mode,
                :oauth_state,
                :redirect_after,
                'pending',
                '{}',
                :created_at,
                :expires_at,
                NULL
            )
            """,
            {
                "user_id": user_id,
                "scope_mode": scope_mode,
                "oauth_state": oauth_state,
                "redirect_after": redirect_after,
                "created_at": now_iso,
                "expires_at": expires_at,
            },
        )

    return session_id, oauth_state


def start_gmail_web_oauth(
    *,
    user_id: int,
    scope_mode: str,
    login_hint: str | None = None,
) -> GmailWebOAuthStartResult:
    web_client_config = _load_web_client_config()
    scopes = _resolve_scopes(scope_mode)

    callback_url = config.GOOGLE_WEB_OAUTH_CALLBACK_URL.strip()
    if not callback_url:
        raise GmailWebOAuthNotConfiguredError(
            "Hosted Gmail web OAuth callback URL is not configured."
        )

    redirect_after = _return_url_for_scope_mode(scope_mode)
    session_id, oauth_state = _create_oauth_connect_session(
        user_id=user_id,
        scope_mode=scope_mode,
        redirect_after=redirect_after,
    )

    flow = Flow.from_client_config(web_client_config, scopes=scopes)
    flow.redirect_uri = callback_url
    authorization_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        login_hint=login_hint.strip().lower() if login_hint else None,
        prompt="consent select_account",
        state=oauth_state,
    )

    return GmailWebOAuthStartResult(
        authorization_url=authorization_url,
        oauth_state=oauth_state,
        session_id=session_id,
    )


def get_oauth_connect_session(oauth_state: str) -> dict | None:
    with get_connection() as conn:
        row = fetch_one(
            conn,
            """
            SELECT id, user_id, provider, scope_mode, oauth_state, redirect_after, status,
                   metadata_json, created_at, expires_at, consumed_at
            FROM oauth_connect_sessions
            WHERE oauth_state = :oauth_state
            """,
            {"oauth_state": oauth_state},
        )
    return dict(row) if row is not None else None


def _load_pending_session(
    oauth_state: str,
    *,
    expected_user_id: int | None = None,
) -> dict:
    session = get_oauth_connect_session(oauth_state)
    if session is None:
        raise GmailWebOAuthStateError(
            "OAuth session was not found or has already expired.",
            code=GMAIL_OAUTH_SESSION_INVALID,
        )

    if expected_user_id is not None and int(session["user_id"]) != expected_user_id:
        raise GmailWebOAuthStateError(
            "OAuth session does not belong to the currently signed-in Fynish user.",
            code=GMAIL_OAUTH_SESSION_INVALID,
        )

    if session["status"] != "pending":
        raise GmailWebOAuthStateError(
            "OAuth session is no longer pending.",
            code=GMAIL_OAUTH_SESSION_INVALID,
        )

    expires_at = datetime.fromisoformat(str(session["expires_at"]))
    if expires_at < _now():
        with get_connection() as conn:
            _mark_session_status(
                conn,
                oauth_state=oauth_state,
                status="expired",
                metadata={"reason": "expired_before_callback"},
                consumed=False,
            )
        raise GmailWebOAuthStateError(
            "OAuth session expired before Google returned.",
            code=GMAIL_OAUTH_SESSION_EXPIRED,
        )

    return session


def _exchange_code_for_credentials(
    *,
    web_client_config: dict,
    scopes: list[str],
    callback_url: str,
    oauth_state: str,
    authorization_code: str,
):
    flow = Flow.from_client_config(web_client_config, scopes=scopes, state=oauth_state)
    flow.redirect_uri = callback_url
    flow.fetch_token(code=authorization_code)
    return flow.credentials


def _fetch_gmail_profile_email(credentials) -> str:
    service = build("gmail", "v1", credentials=credentials)
    profile = service.users().getProfile(userId="me").execute()
    return str(profile["emailAddress"]).strip().lower()


def _fetch_google_userinfo_email(credentials) -> str:
    service = build("oauth2", "v2", credentials=credentials)
    profile = service.userinfo().get().execute()
    email = profile.get("email")
    if not email:
        raise GmailWebOAuthStateError(
            "Google OAuth profile did not include an email address.",
            code=GMAIL_OAUTH_SESSION_INVALID,
        )
    return str(email).strip().lower()


def _fetch_connected_email(credentials, *, scope_mode: str) -> str:
    if scope_mode == "send":
        return _fetch_google_userinfo_email(credentials)
    return _fetch_gmail_profile_email(credentials)


@dataclass(frozen=True)
class GmailWebOAuthCompletionResult:
    user_id: int
    email_address: str
    scopes: list[str]
    token_json: str
    redirect_url: str
    oauth_state: str
    scope_mode: str


def complete_gmail_web_oauth(
    *,
    oauth_state: str,
    authorization_code: str | None,
    oauth_error: str | None,
    expected_user_id: int | None = None,
) -> GmailWebOAuthCompletionResult:
    session = _load_pending_session(oauth_state, expected_user_id=expected_user_id)
    scope_mode = str(session["scope_mode"])
    redirect_after = str(session["redirect_after"])

    if oauth_error:
        with get_connection() as conn:
            _mark_session_status(
                conn,
                oauth_state=oauth_state,
                status="failed",
                metadata={"reason": "google_error", "oauth_error": oauth_error},
                consumed=True,
            )
        raise GmailWebOAuthStateError(
            f"Google OAuth returned an error: {oauth_error}",
            code=GMAIL_OAUTH_DENIED if oauth_error == "access_denied" else GMAIL_OAUTH_SESSION_INVALID,
        )

    if not authorization_code:
        raise GmailWebOAuthStateError(
            "Google OAuth callback did not include an authorization code.",
            code=GMAIL_OAUTH_SESSION_INVALID,
        )

    web_client_config = _load_web_client_config()
    scopes = _resolve_scopes(scope_mode)
    callback_url = config.GOOGLE_WEB_OAUTH_CALLBACK_URL.strip()
    try:
        credentials = _exchange_code_for_credentials(
            web_client_config=web_client_config,
            scopes=scopes,
            callback_url=callback_url,
            oauth_state=oauth_state,
            authorization_code=authorization_code,
        )
    except Warning as error:
        required_scope = _required_scope_for_mode(scope_mode)
        message = (
            _missing_scope_message(scope_mode, required_scope)
            if required_scope
            else "Google OAuth did not grant the requested permissions."
        )
        with get_connection() as conn:
            _mark_session_status(
                conn,
                oauth_state=oauth_state,
                status="failed",
                metadata={
                    "reason": "missing_required_scope",
                    "scope_mode": scope_mode,
                    "oauth_warning": str(error),
                },
                consumed=True,
            )
        raise GmailWebOAuthStateError(message, code=GMAIL_OAUTH_MISSING_SCOPE) from error

    granted_scopes = list(credentials.scopes or [])
    required_scope = _required_scope_for_mode(scope_mode)
    if required_scope and required_scope not in granted_scopes:
        message = _missing_scope_message(scope_mode, required_scope)
        with get_connection() as conn:
            _mark_session_status(
                conn,
                oauth_state=oauth_state,
                status="failed",
                metadata={
                    "reason": "missing_required_scope",
                    "scope_mode": scope_mode,
                    "required_scope": required_scope,
                    "granted_scopes": granted_scopes,
                },
                consumed=True,
            )
        raise GmailWebOAuthStateError(message, code=GMAIL_OAUTH_MISSING_SCOPE)

    email_address = _fetch_connected_email(credentials, scope_mode=scope_mode)
    token_json = credentials.to_json()

    with get_connection() as conn:
        _mark_session_status(
            conn,
            oauth_state=oauth_state,
            status="completed",
            metadata={"connected_email": email_address, "scope_mode": scope_mode},
            consumed=True,
        )

    return GmailWebOAuthCompletionResult(
        user_id=int(session["user_id"]),
        email_address=email_address,
        scopes=granted_scopes or scopes,
        token_json=token_json,
        redirect_url=_serialize_redirect(
            redirect_after=redirect_after,
            status="success",
            message=f"Connected {email_address} to Fynish.",
            email_address=email_address,
        ),
        oauth_state=oauth_state,
        scope_mode=scope_mode,
    )
