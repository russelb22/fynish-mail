from __future__ import annotations

from pathlib import Path

from app.services.style_draft_evaluation import evaluate_draft


def test_evaluate_draft_scores_grounded_compressed_reply(tmp_path: Path):
    draft_path = tmp_path / "draft-schedule-follow-up.md"
    draft_path.write_text(
        (
            "Hi Maya,\n\n"
            "Thanks for sending this over. Yes, I can take a look before the review, "
            "especially with an eye toward whether the scope is too broad.\n\n"
            "I think the most useful thing would be for me to send back a short list "
            "of anything that feels like it should be cut or clarified."
        ),
        encoding="utf-8",
    )

    evaluation = evaluate_draft(
        scenario={"id": "schedule-follow-up"},
        draft_path=draft_path,
    )

    assert evaluation.score >= 80
    assert "natural_paragraph_count" in evaluation.notes
    assert "possible_invented_completion" not in evaluation.flags


def test_evaluate_draft_flags_corporate_and_invented_language(tmp_path: Path):
    draft_path = tmp_path / "draft-product-feedback.md"
    draft_path.write_text(
        (
            "Hi Ari,\n\n"
            "I already reviewed the detailed notes and wanted to circle back at your "
            "earliest convenience so we can leverage the feedback."
        ),
        encoding="utf-8",
    )

    evaluation = evaluate_draft(
        scenario={"id": "product-feedback"},
        draft_path=draft_path,
    )

    assert "corporate_language" in evaluation.flags
    assert "possible_invented_completion" in evaluation.flags
