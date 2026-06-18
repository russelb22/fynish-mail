from __future__ import annotations

from datetime import date

from app.services.writing_sample_export import (
    SampleBucket,
    build_sample_buckets,
    build_sample_record,
    choose_bucket_samples,
    clean_authored_text,
    sample_rejection_reason,
    style_context_markdown,
    style_sample_score,
)


def test_build_sample_buckets_splits_yearly_range():
    buckets = build_sample_buckets(
        start=date(2024, 1, 1),
        end=date(2026, 1, 1),
        mode="year",
    )

    assert buckets == [
        SampleBucket(label="2024", after=date(2024, 1, 1), before=date(2025, 1, 1)),
        SampleBucket(label="2025", after=date(2025, 1, 1), before=date(2026, 1, 1)),
    ]
    assert buckets[0].gmail_query == "in:sent after:2024/01/01 before:2025/01/01"


def test_clean_authored_text_removes_reply_quote_and_signature():
    text = """Sounds good. I can do Tuesday afternoon.

Let me know if 2pm works.

Best,
Russel

On Mon, Jan 1, 2024 at 9:00 AM Someone <someone@example.com> wrote:
> Can you meet next week?
"""

    assert clean_authored_text(text) == (
        "Sounds good. I can do Tuesday afternoon.\n\nLet me know if 2pm works."
    )


def test_build_sample_record_skips_tiny_messages():
    record = build_sample_record(
        account_email="owner@example.com",
        bucket=SampleBucket("2026", date(2026, 1, 1), date(2027, 1, 1)),
        message={"id": "gmail-1", "threadId": "thread-1", "internalDate": "1770000000000"},
        headers={"Subject": "Quick", "To": "recipient@example.com"},
        raw_body="Thanks!",
    )

    assert record is None


def test_sample_rejection_reason_rejects_short_logistics_note():
    record = {
        "subject": "Re: meeting",
        "word_count": 11,
        "char_count": 74,
        "text": "Sounds good. I can do Tuesday afternoon if that still works.",
    }

    assert sample_rejection_reason(record) == "too_few_chars"


def test_sample_rejection_reason_keeps_expressive_shorter_note():
    text = (
        "Sounds good. I think Tuesday afternoon is probably the cleanest option "
        "because it gives us enough time to review the notes first. Does 2pm work? "
        "I can also move a couple things around if Thursday would make this easier."
    )
    record = {
        "subject": "Re: meeting",
        "word_count": 34,
        "char_count": len(text),
        "text": text,
    }
    record["style_sample_score"] = style_sample_score(record)

    assert sample_rejection_reason(record) is None


def test_style_context_markdown_includes_private_agent_guidance():
    record = build_sample_record(
        account_email="owner@example.com",
        bucket=SampleBucket("2026", date(2026, 1, 1), date(2027, 1, 1)),
        message={"id": "gmail-1", "threadId": "thread-1", "internalDate": "1770000000000"},
        headers={"Subject": "Follow up", "To": "recipient@example.com"},
        raw_body=(
            "I wanted to follow up on the project notes and make sure the next "
            "steps are clear. I think the highest leverage move is to keep the "
            "scope tight, test it with a real example, and then expand from there."
        ),
    )

    markdown = style_context_markdown(account_email="owner@example.com", records=[record])

    assert "Do not quote these samples back to recipients" in markdown
    assert "Subject: Follow up" in markdown
    assert "highest leverage move" in markdown


def test_style_sample_score_prefers_substantial_authored_prose():
    substantial = {
        "subject": "Project follow up",
        "word_count": 80,
        "char_count": 460,
        "text": (
            "I wanted to follow up with a clearer version of the plan.\n\n"
            "The short version is that we should test this with one real workflow, "
            "look at the results, and then decide whether it deserves more polish. "
            "Does that line up with what you were thinking?"
        ),
    }
    auto_generated = {
        "subject": "Fwd: automatic reply",
        "word_count": 80,
        "char_count": 460,
        "text": (
            "This message was sent automatically. Please do not reply. "
            "Unsubscribe using the link below. https://example.com https://example.org"
        ),
    }

    assert style_sample_score(substantial) > style_sample_score(auto_generated)


def test_choose_bucket_samples_diversifies_threads_and_recipients_first():
    records = [
        {
            "gmail_message_id": "1",
            "gmail_thread_id": "thread-1",
            "sent_at": "2026-01-01T00:00:00+00:00",
            "to": "same@example.com",
            "cc": "",
            "subject": "Best but duplicate",
            "word_count": 120,
            "char_count": 700,
            "text": "This is a strong long sample. " * 20,
        },
        {
            "gmail_message_id": "2",
            "gmail_thread_id": "thread-1",
            "sent_at": "2026-01-02T00:00:00+00:00",
            "to": "same@example.com",
            "cc": "",
            "subject": "Duplicate thread",
            "word_count": 110,
            "char_count": 660,
            "text": "This is another strong long sample. " * 18,
        },
        {
            "gmail_message_id": "3",
            "gmail_thread_id": "thread-3",
            "sent_at": "2026-01-03T00:00:00+00:00",
            "to": "other@example.org",
            "cc": "",
            "subject": "Different recipient",
            "word_count": 70,
            "char_count": 390,
            "text": "This is a useful different recipient sample. " * 12,
        },
    ]

    chosen = choose_bucket_samples(records, limit=2)

    assert [record["gmail_message_id"] for record in chosen] == ["1", "3"]
