from __future__ import annotations

from app.services.reminders import get_reminder_summary


def test_reminder_summary_matches_unprocessed_queue(seeded_db):
    summary = get_reminder_summary()
    assert summary["total_unprocessed"] == 30
    assert summary["localhost_url"] == "http://127.0.0.1:5173/"
    assert len(summary["accounts"]) == 3
    assert "Open Fynish: http://127.0.0.1:5173/" in summary["plain_text_preview"]


def test_reminder_summary_category_totals_are_correct(seeded_db):
    summary = get_reminder_summary()
    by_account = {account["account_email"]: account for account in summary["accounts"]}
    assert by_account["family@example.net"]["total_unprocessed"] == 8
    assert by_account["personal@example.com"]["total_unprocessed"] == 12
    assert by_account["work@example.com"]["total_unprocessed"] == 10
