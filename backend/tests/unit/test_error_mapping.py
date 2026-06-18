from __future__ import annotations

from fastapi import HTTPException

from app.core.errors import (
    DIGEST_SENDER_VALIDATION_FAILED,
    GMAIL_ACCOUNT_ALREADY_CONNECTED,
    GMAIL_RECONNECT_REQUIRED,
    http_exception_for_error,
)
from app.services.accounts import GmailAccountOwnershipError
from app.services.digest_sender import DigestSenderValidationError
from app.services.digests import DigestUserNotFoundError
from app.services.gmail_readonly import (
    GmailReadonlyNotConfiguredError,
    GmailReadonlySyncError,
)
from app.services.gmail_web_oauth import GmailWebOAuthModeError, GmailWebOAuthStateError
from app.services.notification_settings import NotificationSettingsValidationError
from app.services.review_queue import UnsafeMessageActionError
from app.services.rules import RuleAccountUnavailableError, RuleSourceMessageUnavailableError


def test_http_exception_for_gmail_sync_error_is_user_fixable():
    error = GmailReadonlySyncError(
        "Stored Gmail credentials were expired or revoked. Reconnect the account."
    )

    result = http_exception_for_error(error)

    assert result.status_code == 400
    assert result.detail == {
        "message": "Stored Gmail credentials were expired or revoked. Reconnect the account.",
        "code": GMAIL_RECONNECT_REQUIRED,
    }


def test_http_exception_for_configuration_and_oauth_errors_are_bad_request():
    config_error = GmailReadonlyNotConfiguredError("Google OAuth client file not found.")
    oauth_error = GmailWebOAuthStateError("OAuth session expired before Google returned.")

    assert http_exception_for_error(config_error).status_code == 400
    assert http_exception_for_error(oauth_error).status_code == 400


def test_http_exception_for_value_error_can_use_route_specific_status():
    result = http_exception_for_error(ValueError("Already connected."), status_code=409)

    assert result.status_code == 409
    assert result.detail == "Already connected."


def test_http_exception_for_account_ownership_error_has_stable_code():
    result = http_exception_for_error(
        GmailAccountOwnershipError(
            "This Gmail account is already connected to a different Fynish user."
        )
    )

    assert result.status_code == 400
    assert result.detail == {
        "message": "This Gmail account is already connected to a different Fynish user.",
        "code": GMAIL_ACCOUNT_ALREADY_CONNECTED,
    }


def test_http_exception_for_digest_sender_validation_error_has_stable_code():
    result = http_exception_for_error(
        DigestSenderValidationError(
            "Digest sender OAuth credentials must include Gmail send access."
        )
    )

    assert result.status_code == 400
    assert result.detail == {
        "message": "Digest sender OAuth credentials must include Gmail send access.",
        "code": DIGEST_SENDER_VALIDATION_FAILED,
    }


def test_http_exception_for_rule_validation_errors_have_stable_codes():
    account_result = http_exception_for_error(
        RuleAccountUnavailableError("Account is not available to the current user.")
    )
    source_result = http_exception_for_error(
        RuleSourceMessageUnavailableError("Source message is not available to the current user.")
    )

    assert account_result.detail == {
        "message": "Account is not available to the current user.",
        "code": "rule_account_unavailable",
    }
    assert source_result.detail == {
        "message": "Source message is not available to the current user.",
        "code": "rule_source_message_unavailable",
    }


def test_http_exception_for_unsafe_message_action_has_stable_code():
    result = http_exception_for_error(
        UnsafeMessageActionError("Unsafe Gmail action plan for message 123")
    )

    assert result.detail == {
        "message": "Unsafe Gmail action plan for message 123",
        "code": "unsafe_message_action",
    }


def test_http_exception_for_remaining_validation_errors_have_stable_codes():
    oauth_result = http_exception_for_error(
        GmailWebOAuthModeError("Unsupported Gmail connect mode: sideways")
    )
    settings_result = http_exception_for_error(
        NotificationSettingsValidationError("digest_time must use a valid 24-hour time")
    )
    digest_result = http_exception_for_error(DigestUserNotFoundError("User not found."))

    assert oauth_result.detail == {
        "message": "Unsupported Gmail connect mode: sideways",
        "code": "gmail_oauth_unsupported_mode",
    }
    assert settings_result.detail == {
        "message": "digest_time must use a valid 24-hour time",
        "code": "notification_settings_validation_failed",
    }
    assert digest_result.detail == {
        "message": "User not found.",
        "code": "digest_user_not_found",
    }


def test_http_exception_for_unknown_error_is_generic():
    result = http_exception_for_error(RuntimeError("sensitive internal detail"))

    assert result.status_code == 500
    assert result.detail == "Request failed."


def test_http_exception_passes_through_existing_http_exception():
    original = HTTPException(status_code=404, detail="Missing")

    result = http_exception_for_error(original)

    assert result is original
