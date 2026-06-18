from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from statistics import median
from typing import Any

from app.services.writing_sample_export import sample_word_count


SOFTENERS = (
    "i think",
    "i believe",
    "i would",
    "i can",
    "i wanted",
    "if possible",
    "if that works",
    "let me know",
    "happy to",
    "probably",
    "maybe",
)
DIRECT_MARKERS = (
    "please",
    "we need",
    "i need",
    "the next step",
    "the short version",
    "let's",
)
WARM_MARKERS = (
    "thanks",
    "thank you",
    "appreciate",
    "sounds good",
    "great",
    "hope",
)
SIGNOFF_PATTERNS = (
    "best",
    "thanks",
    "thank you",
    "regards",
    "sincerely",
    "cheers",
)
STOPWORDS = {
    "about",
    "after",
    "again",
    "also",
    "and",
    "are",
    "because",
    "been",
    "but",
    "can",
    "could",
    "did",
    "for",
    "from",
    "had",
    "has",
    "have",
    "her",
    "him",
    "his",
    "how",
    "into",
    "just",
    "like",
    "more",
    "not",
    "now",
    "our",
    "out",
    "over",
    "she",
    "should",
    "that",
    "the",
    "their",
    "then",
    "there",
    "they",
    "this",
    "through",
    "was",
    "were",
    "what",
    "when",
    "where",
    "which",
    "who",
    "will",
    "with",
    "would",
    "you",
    "your",
}


@dataclass(frozen=True)
class StyleProfile:
    summary: dict[str, Any]
    markdown: str


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            records.append(json.loads(line))
    return records


def _sentences(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+", text) if part.strip()]


def _paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]


def _words(text: str) -> list[str]:
    return re.findall(r"\b[a-zA-Z][a-zA-Z']+\b", text.lower())


def _count_markers(records: list[dict[str, Any]], markers: tuple[str, ...]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        text = str(record.get("text") or "").lower()
        for marker in markers:
            if marker in text:
                counts[marker] += 1
    return counts


def _common_terms(records: list[dict[str, Any]], *, limit: int = 12) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for record in records:
        for word in _words(str(record.get("text") or "")):
            if len(word) >= 4 and word not in STOPWORDS:
                counts[word] += 1
    return counts.most_common(limit)


def _common_openers(records: list[dict[str, Any]], *, limit: int = 8) -> list[tuple[str, int]]:
    counts: Counter[str] = Counter()
    for record in records:
        text = str(record.get("text") or "").strip()
        if not text:
            continue
        first_sentence = _sentences(text)
        opener = first_sentence[0] if first_sentence else text.splitlines()[0]
        opener = " ".join(opener.split())
        if 8 <= len(opener) <= 180:
            counts[opener] += 1
    return counts.most_common(limit)


def _common_signoffs(records: list[dict[str, Any]]) -> Counter[str]:
    counts: Counter[str] = Counter()
    for record in records:
        lines = [
            line.strip().strip(",").lower()
            for line in str(record.get("text") or "").splitlines()
            if line.strip()
        ]
        for line in lines[-4:]:
            if line in SIGNOFF_PATTERNS:
                counts[line] += 1
    return counts


def _describe_length(avg_words: float) -> str:
    if avg_words < 70:
        return "brief"
    if avg_words < 150:
        return "medium-length"
    return "expansive"


def _describe_warmth(warm_rate: float) -> str:
    if warm_rate >= 0.65:
        return "warm and appreciative"
    if warm_rate >= 0.35:
        return "polite and lightly warm"
    return "matter-of-fact"


def _describe_directness(direct_rate: float, softener_rate: float) -> str:
    if direct_rate >= 0.45 and softener_rate < 0.35:
        return "direct"
    if direct_rate >= 0.35 and softener_rate >= 0.35:
        return "direct but softened"
    if softener_rate >= 0.45:
        return "collaborative and softened"
    return "conversational"


def _describe_reply_shape(avg_words: float, avg_paragraphs: float) -> str:
    if avg_words < 150 and avg_paragraphs >= 5:
        return "compressed with short paragraph breaks"
    if avg_paragraphs <= 3:
        return "compact"
    return "paced with paragraph breaks"


def analyze_style(records: list[dict[str, Any]], *, account_email: str) -> StyleProfile:
    if not records:
        raise ValueError("cannot build a style profile without sample records")

    word_counts = [int(record.get("word_count") or sample_word_count(str(record.get("text") or ""))) for record in records]
    char_counts = [int(record.get("char_count") or len(str(record.get("text") or ""))) for record in records]
    sentence_counts = [len(_sentences(str(record.get("text") or ""))) for record in records]
    paragraph_counts = [len(_paragraphs(str(record.get("text") or ""))) for record in records]
    question_count = sum(1 for record in records if "?" in str(record.get("text") or ""))
    softener_counts = _count_markers(records, SOFTENERS)
    direct_counts = _count_markers(records, DIRECT_MARKERS)
    warm_counts = _count_markers(records, WARM_MARKERS)
    signoff_counts = _common_signoffs(records)
    common_terms = _common_terms(records)
    common_openers = _common_openers(records)
    sample_count = len(records)

    avg_words = sum(word_counts) / sample_count
    avg_sentences = sum(sentence_counts) / sample_count
    avg_paragraphs = sum(paragraph_counts) / sample_count
    avg_words_per_paragraph = avg_words / avg_paragraphs if avg_paragraphs else avg_words
    softener_rate = sum(softener_counts.values()) / sample_count
    direct_rate = sum(direct_counts.values()) / sample_count
    warm_rate = sum(warm_counts.values()) / sample_count

    summary = {
        "account_email": account_email,
        "sample_count": sample_count,
        "total_words": sum(word_counts),
        "avg_words": round(avg_words, 1),
        "median_words": median(word_counts),
        "min_words": min(word_counts),
        "max_words": max(word_counts),
        "avg_chars": round(sum(char_counts) / sample_count, 1),
        "avg_sentences": round(avg_sentences, 1),
        "avg_paragraphs": round(avg_paragraphs, 1),
        "avg_words_per_paragraph": round(avg_words_per_paragraph, 1),
        "question_rate": round(question_count / sample_count, 2),
        "softener_rate": round(softener_rate, 2),
        "direct_marker_rate": round(direct_rate, 2),
        "warm_marker_rate": round(warm_rate, 2),
        "length_style": _describe_length(avg_words),
        "directness_style": _describe_directness(direct_rate, softener_rate),
        "warmth_style": _describe_warmth(warm_rate),
        "reply_shape": _describe_reply_shape(avg_words, avg_paragraphs),
        "top_softeners": softener_counts.most_common(8),
        "top_direct_markers": direct_counts.most_common(8),
        "top_warm_markers": warm_counts.most_common(8),
        "top_signoffs": signoff_counts.most_common(6),
        "common_terms": common_terms,
        "common_openers": common_openers,
        "buckets": sorted({str(record.get("bucket") or "") for record in records if record.get("bucket")}),
    }

    return StyleProfile(summary=summary, markdown=style_profile_markdown(summary))


def _format_pairs(pairs: list[tuple[str, int]]) -> str:
    if not pairs:
        return "(not enough signal)"
    return ", ".join(f"{value} ({count})" for value, count in pairs)


def style_profile_markdown(summary: dict[str, Any]) -> str:
    lines = [
        f"# Writing Style Profile: {summary['account_email']}",
        "",
        "Private derived profile built from Gmail Sent Mail samples. Use this profile to draft new email replies in the user's style without quoting or revealing source samples.",
        "",
        "## Corpus",
        "",
        f"- Samples: {summary['sample_count']}",
        f"- Total words: {summary['total_words']}",
        f"- Average words per message: {summary['avg_words']}",
        f"- Median words per message: {summary['median_words']}",
        f"- Word range: {summary['min_words']} to {summary['max_words']}",
        f"- Buckets: {', '.join(summary['buckets'])}",
        "",
        "## Style Signals",
        "",
        f"- Length: {summary['length_style']}",
        f"- Directness: {summary['directness_style']}",
        f"- Warmth: {summary['warmth_style']}",
        f"- Reply shape: {summary['reply_shape']}",
        f"- Average paragraphs: {summary['avg_paragraphs']}",
        f"- Average words per paragraph: {summary['avg_words_per_paragraph']}",
        f"- Average sentences: {summary['avg_sentences']}",
        f"- Question rate: {summary['question_rate']}",
        "",
        "## Drafting Guidance",
        "",
        "- Be practical, clear, and conversational.",
        "- For simple replies, compress to 2-4 natural paragraphs rather than mechanically matching the average paragraph count.",
        "- Prefer concise paragraphs over dense blocks, but avoid making every sentence its own paragraph.",
        "- Keep the reply grounded in the actual message being answered.",
        "- Use gentle softeners when asking for action or proposing next steps.",
        "- Use casual, plain phrasing when the inbound message is casual.",
        "- Do not over-polish into corporate language.",
        "- Avoid importing domain-specific terms from the sample corpus unless they are relevant to the current message.",
        "- Do not quote or disclose the source samples.",
        "- Do not invent personal facts, commitments, or preferences not present in the current task.",
        "",
        "## Observed Markers",
        "",
        f"- Common softeners: {_format_pairs(summary['top_softeners'])}",
        f"- Direct markers: {_format_pairs(summary['top_direct_markers'])}",
        f"- Warmth markers: {_format_pairs(summary['top_warm_markers'])}",
        f"- Signoffs: {_format_pairs(summary['top_signoffs'])}",
        f"- Common terms: {_format_pairs(summary['common_terms'])}",
        "",
        "## Common Openers",
    ]

    openers = summary.get("common_openers") or []
    if openers:
        for opener, count in openers:
            lines.append(f"- {opener} ({count})")
    else:
        lines.append("- (not enough signal)")

    lines.extend(
        [
            "",
            "## Agent Instruction",
            "",
            "When drafting for this user, write in a practical, conversational email style. Aim for the observed medium length, but compress simple replies into a few natural paragraphs. Include warmth where appropriate, soften asks without becoming vague, and use casual plain language when the inbound message is casual. Prioritize the user's actual intent over mimicry. Avoid copying source language verbatim.",
        ]
    )
    return "\n".join(lines).strip() + "\n"
