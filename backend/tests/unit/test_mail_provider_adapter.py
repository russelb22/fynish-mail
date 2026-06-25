from __future__ import annotations

from app.services.mail_provider_adapter import (
    GmailProviderAdapter,
    get_mail_provider_adapter,
)
from app.services.gmail_readonly import list_unread_spam_message_ids


def test_gmail_provider_adapter_is_registered():
    adapter = get_mail_provider_adapter("gmail_readonly")

    assert isinstance(adapter, GmailProviderAdapter)
    assert adapter.provider_name == "gmail_readonly"


def test_unknown_provider_has_no_adapter():
    assert get_mail_provider_adapter("outlook") is None


class _FakeMessages:
    def __init__(self):
        self.list_kwargs = None

    def list(self, **kwargs):
        self.list_kwargs = kwargs
        return self

    def execute(self):
        return {"messages": [{"id": "spam-1"}, {"id": "spam-2"}]}


class _FakeUsers:
    def __init__(self, messages):
        self._messages = messages

    def messages(self):
        return self._messages


class _FakeService:
    def __init__(self):
        self.messages_resource = _FakeMessages()

    def users(self):
        return _FakeUsers(self.messages_resource)


def test_list_unread_spam_message_ids_uses_spam_unread_labels_and_lookback():
    service = _FakeService()

    refs = list_unread_spam_message_ids(service, max_results=25, newer_than_days=14)

    assert refs == [{"id": "spam-1"}, {"id": "spam-2"}]
    assert service.messages_resource.list_kwargs == {
        "userId": "me",
        "labelIds": ["SPAM", "UNREAD"],
        "maxResults": 25,
        "q": "newer_than:14d",
    }
