from __future__ import annotations

from app.services.writing_style_profile import analyze_style


def test_analyze_style_builds_derived_profile_without_source_dump():
    records = [
        {
            "bucket": "2025-01",
            "word_count": 48,
            "char_count": 260,
            "text": (
                "Thanks for sending this over. I think the next step is to test "
                "the workflow with one real example and see where it breaks. "
                "Let me know if Tuesday works."
            ),
        },
        {
            "bucket": "2025-02",
            "word_count": 57,
            "char_count": 310,
            "text": (
                "Sounds good. I would keep the first version pretty small, then "
                "expand once we know the shape of the problem. The short version "
                "is that we should make the review loop easy."
            ),
        },
    ]

    profile = analyze_style(records, account_email="owner@example.com")

    assert profile.summary["sample_count"] == 2
    assert profile.summary["total_words"] == 105
    assert profile.summary["length_style"] == "brief"
    assert "reply_shape" in profile.summary
    assert "Drafting Guidance" in profile.markdown
    assert "compress to 2-4 natural paragraphs" in profile.markdown
    assert "Use this profile to draft new email replies" in profile.markdown
