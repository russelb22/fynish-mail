from __future__ import annotations

from app.services.mail_provider_adapter import (
    GmailProviderAdapter,
    get_mail_provider_adapter,
)


def test_gmail_provider_adapter_is_registered():
    adapter = get_mail_provider_adapter("gmail_readonly")

    assert isinstance(adapter, GmailProviderAdapter)
    assert adapter.provider_name == "gmail_readonly"


def test_unknown_provider_has_no_adapter():
    assert get_mail_provider_adapter("outlook") is None
