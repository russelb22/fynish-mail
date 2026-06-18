from __future__ import annotations

from fastapi import HTTPException

from app.services.accounts import GmailAccountOwnershipError
from app.services.digest_sender import DigestSenderValidationError
from app.services.digests import DigestUserNotFoundError
from app.services.gmail_readonly import (
    GmailReadonlyNotConfiguredError,
    GmailReadonlySyncError,
)
from app.services.gmail_web_oauth import (
    GmailWebOAuthModeError,
    GmailWebOAuthNotConfiguredError,
    GmailWebOAuthStateError,
)
from app.services.notification_settings import NotificationSettingsValidationError
from app.services.review_queue import UnsafeMessageActionError
from app.services.rules import RuleAccountUnavailableError, RuleSourceMessageUnavailableError
from app.services.writing_style_cards import WritingStyleCardSamplingError

GMAIL_RECONNECT_REQUIRED = "gmail_reconnect_required"
GMAIL_OAUTH_NOT_CONFIGURED = "gmail_oauth_not_configured"
GOOGLE_OAUTH_STATE_INVALID = "google_oauth_state_invalid"
GMAIL_ACCOUNT_ALREADY_CONNECTED = "gmail_account_already_connected"
DIGEST_SENDER_VALIDATION_FAILED = "digest_sender_validation_failed"
RULE_ACCOUNT_UNAVAILABLE = "rule_account_unavailable"
RULE_SOURCE_MESSAGE_UNAVAILABLE = "rule_source_message_unavailable"
UNSAFE_MESSAGE_ACTION = "unsafe_message_action"
GMAIL_OAUTH_UNSUPPORTED_MODE = "gmail_oauth_unsupported_mode"
NOTIFICATION_SETTINGS_VALIDATION_FAILED = "notification_settings_validation_failed"
DIGEST_USER_NOT_FOUND = "digest_user_not_found"


def _detail_with_code(message: str, code: str) -> dict[str, str]:
    return {
        "message": message,
        "code": code,
    }


def error_code_for_error(error: Exception) -> str | None:
    if isinstance(error, GmailReadonlySyncError):
        message = str(error).lower()
        if "credential" in message or "token" in message or "reconnect" in message:
            return GMAIL_RECONNECT_REQUIRED
        return None
    if isinstance(error, GmailReadonlyNotConfiguredError):
        return GMAIL_OAUTH_NOT_CONFIGURED
    if isinstance(error, GmailWebOAuthNotConfiguredError):
        return GMAIL_OAUTH_NOT_CONFIGURED
    if isinstance(error, GmailWebOAuthStateError):
        return error.code or GOOGLE_OAUTH_STATE_INVALID
    if isinstance(error, GmailWebOAuthModeError):
        return GMAIL_OAUTH_UNSUPPORTED_MODE
    if isinstance(error, GmailAccountOwnershipError):
        return GMAIL_ACCOUNT_ALREADY_CONNECTED
    if isinstance(error, DigestSenderValidationError):
        return DIGEST_SENDER_VALIDATION_FAILED
    if isinstance(error, NotificationSettingsValidationError):
        return NOTIFICATION_SETTINGS_VALIDATION_FAILED
    if isinstance(error, DigestUserNotFoundError):
        return DIGEST_USER_NOT_FOUND
    if isinstance(error, RuleAccountUnavailableError):
        return RULE_ACCOUNT_UNAVAILABLE
    if isinstance(error, RuleSourceMessageUnavailableError):
        return RULE_SOURCE_MESSAGE_UNAVAILABLE
    if isinstance(error, UnsafeMessageActionError):
        return UNSAFE_MESSAGE_ACTION
    return None


def http_exception_for_error(
    error: Exception,
    *,
    status_code: int | None = None,
) -> HTTPException:
    if isinstance(error, HTTPException):
        return error
    if isinstance(
        error,
        (
            GmailReadonlyNotConfiguredError,
            GmailReadonlySyncError,
            GmailWebOAuthNotConfiguredError,
            GmailWebOAuthStateError,
            GmailWebOAuthModeError,
            GmailAccountOwnershipError,
            DigestSenderValidationError,
            NotificationSettingsValidationError,
            DigestUserNotFoundError,
            RuleAccountUnavailableError,
            RuleSourceMessageUnavailableError,
            UnsafeMessageActionError,
            WritingStyleCardSamplingError,
        ),
    ):
        message = str(error)
        code = error_code_for_error(error)
        detail = _detail_with_code(message, code) if code else message
        return HTTPException(status_code=status_code or 400, detail=detail)
    if isinstance(error, ValueError):
        return HTTPException(status_code=status_code or 400, detail=str(error))
    return HTTPException(status_code=status_code or 500, detail="Request failed.")
