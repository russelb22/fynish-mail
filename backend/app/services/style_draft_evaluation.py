from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from app.services.writing_sample_export import sample_word_count


WARM_MARKERS = ("thanks", "thank you", "appreciate", "helpful", "great")
SOFTENER_MARKERS = ("i think", "i can", "i would", "if", "might", "should", "let me know")
CORPORATE_MARKERS = (
    "circle back",
    "touch base",
    "leverage",
    "synergy",
    "per my last email",
    "at your earliest convenience",
)
INVENTION_MARKERS = (
    "i already",
    "i have already",
    "i reviewed",
    "i finished",
    "i spoke with",
)
DOMAIN_LEAK_MARKERS = (
    "tatami",
    "pharma",
    "indochine",
    "spring rolls",
    "per person price",
)
GOAL_MARKERS = {
    "schedule-follow-up": ("take a look", "scope", "short list", "cut", "clarified", "clarify"),
    "gentle-boundary": ("not think i can", "realistically", "smaller", "current draft", "main edits"),
    "product-feedback": ("thanks", "more detail", "setup", "expected", "short list"),
}


@dataclass(frozen=True)
class DraftEvaluation:
    scenario_id: str
    draft_path: str
    score: int
    max_score: int
    metrics: dict[str, Any]
    flags: list[str]
    notes: list[str]


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def _contains_any(text: str, markers: tuple[str, ...]) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in markers)


def _count_any(text: str, markers: tuple[str, ...]) -> int:
    lowered = text.lower()
    return sum(1 for marker in markers if marker in lowered)


def _draft_path_for_scenario(sandbox_dir: Path, scenario_id: str) -> Path:
    return sandbox_dir / f"draft-{scenario_id}.md"


def evaluate_draft(
    *,
    scenario: dict[str, Any],
    draft_path: Path,
) -> DraftEvaluation:
    text = draft_path.read_text(encoding="utf-8").strip()
    words = sample_word_count(text)
    paragraphs = _paragraphs(text)
    paragraph_count = len(paragraphs)
    flags: list[str] = []
    notes: list[str] = []
    score = 0
    max_score = 100

    if 45 <= words <= 140:
        score += 20
        notes.append("word_count_in_target")
    elif words < 45:
        score += 8
        flags.append("possibly_too_short")
    else:
        score += 10
        flags.append("possibly_too_long")

    if 2 <= paragraph_count <= 4:
        score += 20
        notes.append("natural_paragraph_count")
    elif paragraph_count == 1:
        score += 8
        flags.append("possibly_too_dense")
    else:
        score += 10
        flags.append("possibly_over_sectioned")

    if _contains_any(text, WARM_MARKERS):
        score += 12
        notes.append("warmth_present")
    else:
        flags.append("missing_warmth_marker")

    if _contains_any(text, SOFTENER_MARKERS):
        score += 12
        notes.append("softening_present")
    else:
        flags.append("missing_softener")

    goal_hits = _count_any(text, GOAL_MARKERS.get(str(scenario.get("id")), ()))
    if goal_hits >= 2:
        score += 20
        notes.append("goal_coverage_present")
    elif goal_hits == 1:
        score += 10
        flags.append("thin_goal_coverage")
    else:
        flags.append("missing_goal_coverage")

    if _contains_any(text, CORPORATE_MARKERS):
        flags.append("corporate_language")
    else:
        score += 6

    if _contains_any(text, INVENTION_MARKERS):
        flags.append("possible_invented_completion")
    else:
        score += 5

    if _contains_any(text, DOMAIN_LEAK_MARKERS):
        flags.append("possible_domain_leak")
    else:
        score += 5

    metrics = {
        "word_count": words,
        "paragraph_count": paragraph_count,
        "warm_marker_count": _count_any(text, WARM_MARKERS),
        "softener_count": _count_any(text, SOFTENER_MARKERS),
        "goal_marker_hits": goal_hits,
    }

    return DraftEvaluation(
        scenario_id=str(scenario.get("id")),
        draft_path=str(draft_path),
        score=min(score, max_score),
        max_score=max_score,
        metrics=metrics,
        flags=flags,
        notes=notes,
    )


def evaluate_sandbox(sandbox_dir: Path) -> list[DraftEvaluation]:
    manifest = json.loads((sandbox_dir / "manifest.json").read_text(encoding="utf-8"))
    evaluations = []
    for scenario in manifest.get("scenarios", []):
        draft_path = _draft_path_for_scenario(sandbox_dir, str(scenario.get("id")))
        if not draft_path.exists():
            evaluations.append(
                DraftEvaluation(
                    scenario_id=str(scenario.get("id")),
                    draft_path=str(draft_path),
                    score=0,
                    max_score=100,
                    metrics={},
                    flags=["missing_draft_file"],
                    notes=[],
                )
            )
            continue
        evaluations.append(evaluate_draft(scenario=scenario, draft_path=draft_path))
    return evaluations


def render_evaluation_markdown(evaluations: list[DraftEvaluation]) -> str:
    if not evaluations:
        return "# Draft Evaluation\n\nNo drafts found.\n"

    avg_score = sum(item.score for item in evaluations) / len(evaluations)
    lines = [
        "# Draft Evaluation",
        "",
        f"Drafts evaluated: {len(evaluations)}",
        f"Average score: {avg_score:.1f}/100",
        "",
        "## Rubric",
        "",
        "- 45-140 words",
        "- 2-4 natural paragraphs",
        "- warmth marker present",
        "- softener present",
        "- scenario goal coverage",
        "- no corporate language",
        "- no invented completion claims",
        "- no sample-domain leakage",
    ]

    for item in evaluations:
        flags = ", ".join(item.flags) if item.flags else "none"
        notes = ", ".join(item.notes) if item.notes else "none"
        lines.extend(
            [
                "",
                f"## {item.scenario_id}",
                "",
                f"- Score: {item.score}/{item.max_score}",
                f"- Word count: {item.metrics.get('word_count', 'n/a')}",
                f"- Paragraphs: {item.metrics.get('paragraph_count', 'n/a')}",
                f"- Goal marker hits: {item.metrics.get('goal_marker_hits', 'n/a')}",
                f"- Flags: {flags}",
                f"- Notes: {notes}",
            ]
        )

    return "\n".join(lines).strip() + "\n"
