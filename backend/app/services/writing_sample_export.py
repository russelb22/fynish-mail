from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, timezone
from email.utils import getaddresses
from email.utils import parsedate_to_datetime
from typing import Any


DEFAULT_SAMPLE_YEARS = 10
DEFAULT_BUCKET_MODE = "year"
DEFAULT_PER_BUCKET = 12
DEFAULT_MAX_TOTAL = 160
DEFAULT_CANDIDATE_MULTIPLIER = 6
MIN_USEFUL_SAMPLE_CHARS = 140
MIN_USEFUL_SAMPLE_WORDS = 35
MIN_EXPRESSIVE_SHORT_WORDS = 30
IDEAL_MIN_WORDS = 45
IDEAL_MAX_WORDS = 550

QUOTE_MARKERS = (
    r"^On .+ wrote:$",
    r"^On .+ at .+, .+ wrote:$",
    r"^-{2,}\s*Original Message\s*-{2,}$",
    r"^From:\s.+$",
    r"^Sent from my iPhone$",
    r"^Begin forwarded message:$",
    r"^Forwarded message\s*-*$",
)
SIGNATURE_MARKERS = (
    "-- ",
    "Best,",
    "Best regards,",
    "Regards,",
    "Thanks,",
    "Thank you,",
    "Sincerely,",
    "Cheers,",
)
LOW_VALUE_SUBJECT_PREFIXES = (
    "fwd:",
    "fw:",
    "forward:",
    "automatic reply:",
    "out of office",
    "accepted:",
    "declined:",
    "tentative:",
    "canceled:",
    "cancelled:",
)
LOW_VALUE_BODY_PATTERNS = (
    r"\bthis message was sent automatically\b",
    r"\bdo not reply\b",
    r"\bunsubscribe\b",
    r"\bcalendar invitation\b",
    r"\binvitation from google calendar\b",
    r"\battached (is|are)\b",
)
EXPRESSIVE_SHORT_MARKERS = (
    "?",
    "!",
    "I think",
    "I wanted",
    "I can",
    "I would",
    "let me know",
    "sounds good",
    "makes sense",
)


@dataclass(frozen=True)
class SampleBucket:
    label: str
    after: date
    before: date

    @property
    def gmail_query(self) -> str:
        return (
            f"in:sent after:{self.after:%Y/%m/%d} "
            f"before:{self.before:%Y/%m/%d}"
        )


def utc_today() -> date:
    return datetime.now(timezone.utc).date()


def parse_date(value: str) -> date:
    return date.fromisoformat(value.strip())


def _add_years(value: date, years: int) -> date:
    try:
        return value.replace(year=value.year + years)
    except ValueError:
        return value.replace(month=2, day=28, year=value.year + years)


def _first_of_next_month(value: date) -> date:
    if value.month == 12:
        return date(value.year + 1, 1, 1)
    return date(value.year, value.month + 1, 1)


def _first_of_next_quarter(value: date) -> date:
    next_month = value.month + 3
    year = value.year + ((next_month - 1) // 12)
    month = ((next_month - 1) % 12) + 1
    return date(year, month, 1)


def build_sample_buckets(
    *,
    start: date,
    end: date,
    mode: str = DEFAULT_BUCKET_MODE,
) -> list[SampleBucket]:
    if start >= end:
        raise ValueError("sample start date must be before end date")

    buckets: list[SampleBucket] = []
    cursor = start
    while cursor < end:
        if mode == "year":
            next_start = _add_years(cursor, 1)
            label = str(cursor.year)
        elif mode == "quarter":
            next_start = _first_of_next_quarter(cursor)
            quarter = ((cursor.month - 1) // 3) + 1
            label = f"{cursor.year}-Q{quarter}"
        elif mode == "month":
            next_start = _first_of_next_month(cursor)
            label = f"{cursor.year}-{cursor.month:02d}"
        else:
            raise ValueError("bucket mode must be one of: year, quarter, month")

        bucket_end = min(next_start, end)
        buckets.append(SampleBucket(label=label, after=cursor, before=bucket_end))
        cursor = bucket_end

    return buckets


def default_start_date(today: date | None = None) -> date:
    today = today or utc_today()
    return _add_years(today, -DEFAULT_SAMPLE_YEARS)


def normalize_whitespace(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_quoted_replies(text: str) -> str:
    lines = normalize_whitespace(text).splitlines()
    kept: list[str] = []
    marker_patterns = [re.compile(pattern, re.IGNORECASE) for pattern in QUOTE_MARKERS]

    for line in lines:
        stripped = line.strip()
        if stripped.startswith(">"):
            break
        if any(pattern.match(stripped) for pattern in marker_patterns):
            break
        kept.append(line)

    return normalize_whitespace("\n".join(kept))


def strip_signature(text: str) -> str:
    lines = normalize_whitespace(text).splitlines()
    if len(lines) < 3:
        return normalize_whitespace(text)

    search_start = max(0, len(lines) - 8)
    for index in range(len(lines) - 1, search_start - 1, -1):
        stripped = lines[index].strip()
        if stripped in SIGNATURE_MARKERS:
            return normalize_whitespace("\n".join(lines[:index]))

    return normalize_whitespace(text)


def clean_authored_text(text: str) -> str:
    text = strip_quoted_replies(text)
    text = strip_signature(text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def sample_word_count(text: str) -> int:
    return len(re.findall(r"\b[\w']+\b", text))


def recipient_addresses(value: str) -> list[str]:
    return [address.lower() for _name, address in getaddresses([value]) if address]


def recipient_domains(value: str) -> list[str]:
    domains = []
    for address in recipient_addresses(value):
        if "@" in address:
            domains.append(address.rsplit("@", 1)[1])
    return domains


def style_sample_score(record: dict[str, Any]) -> int:
    text = str(record.get("text") or "")
    subject = str(record.get("subject") or "").strip().lower()
    word_count = int(record.get("word_count") or sample_word_count(text))
    char_count = int(record.get("char_count") or len(text))
    line_count = len([line for line in text.splitlines() if line.strip()])

    score = 0
    score += min(word_count, IDEAL_MAX_WORDS)
    score += min(char_count // 40, 30)

    if IDEAL_MIN_WORDS <= word_count <= IDEAL_MAX_WORDS:
        score += 80
    elif word_count < IDEAL_MIN_WORDS:
        score -= (IDEAL_MIN_WORDS - word_count) * 3
    else:
        score -= min((word_count - IDEAL_MAX_WORDS) // 10, 80)

    if line_count >= 2:
        score += 20
    if "?" in text:
        score += 10
    if any(subject.startswith(prefix) for prefix in LOW_VALUE_SUBJECT_PREFIXES):
        score -= 120
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in LOW_VALUE_BODY_PATTERNS):
        score -= 80
    if text.count("http://") + text.count("https://") > 2:
        score -= 50
    if any(marker.lower() in text.lower() for marker in EXPRESSIVE_SHORT_MARKERS):
        score += 15

    return score


def sample_rejection_reason(record: dict[str, Any]) -> str | None:
    text = str(record.get("text") or "")
    subject = str(record.get("subject") or "").strip().lower()
    word_count = int(record.get("word_count") or sample_word_count(text))
    char_count = int(record.get("char_count") or len(text))
    has_expressive_marker = any(
        marker.lower() in text.lower() for marker in EXPRESSIVE_SHORT_MARKERS
    )

    if char_count < MIN_USEFUL_SAMPLE_CHARS:
        return "too_few_chars"
    if (
        word_count < MIN_USEFUL_SAMPLE_WORDS
        and not (word_count >= MIN_EXPRESSIVE_SHORT_WORDS and has_expressive_marker)
    ):
        return "too_few_words"
    if any(subject.startswith(prefix) for prefix in LOW_VALUE_SUBJECT_PREFIXES):
        return "low_value_subject"
    if any(re.search(pattern, text, re.IGNORECASE) for pattern in LOW_VALUE_BODY_PATTERNS):
        return "low_value_body"
    if text.count("http://") + text.count("https://") > 4:
        return "too_many_links"
    return None


def is_useful_sample(record: dict[str, Any]) -> bool:
    return sample_rejection_reason(record) is None


def choose_bucket_samples(
    records: list[dict[str, Any]],
    *,
    limit: int,
) -> list[dict[str, Any]]:
    ranked = sorted(records, key=style_sample_score, reverse=True)
    chosen: list[dict[str, Any]] = []
    seen_threads: set[str] = set()
    seen_recipients: set[str] = set()
    seen_domains: set[str] = set()

    def is_diverse(record: dict[str, Any]) -> bool:
        thread_id = str(record.get("gmail_thread_id") or "")
        recipients = recipient_addresses(
            " ".join([str(record.get("to") or ""), str(record.get("cc") or "")])
        )
        domains = recipient_domains(
            " ".join([str(record.get("to") or ""), str(record.get("cc") or "")])
        )
        if thread_id and thread_id in seen_threads:
            return False
        if recipients and any(recipient in seen_recipients for recipient in recipients):
            return False
        if domains and any(domain in seen_domains for domain in domains):
            return False
        return True

    def mark_seen(record: dict[str, Any]) -> None:
        thread_id = str(record.get("gmail_thread_id") or "")
        if thread_id:
            seen_threads.add(thread_id)
        recipients = recipient_addresses(
            " ".join([str(record.get("to") or ""), str(record.get("cc") or "")])
        )
        domains = recipient_domains(
            " ".join([str(record.get("to") or ""), str(record.get("cc") or "")])
        )
        seen_recipients.update(recipients)
        seen_domains.update(domains)

    for record in ranked:
        if len(chosen) >= limit:
            break
        if is_diverse(record):
            chosen.append(record)
            mark_seen(record)

    if len(chosen) < limit:
        chosen_ids = {str(record.get("gmail_message_id") or "") for record in chosen}
        for record in ranked:
            if len(chosen) >= limit:
                break
            message_id = str(record.get("gmail_message_id") or "")
            if message_id not in chosen_ids:
                chosen.append(record)
                chosen_ids.add(message_id)

    return sorted(chosen, key=lambda record: str(record.get("sent_at") or ""))


def parse_message_date(message: dict[str, Any], headers: dict[str, str]) -> str:
    internal_ms = message.get("internalDate")
    if internal_ms:
        try:
            return datetime.fromtimestamp(
                int(internal_ms) / 1000, tz=timezone.utc
            ).isoformat()
        except (TypeError, ValueError):
            pass

    raw_date = headers.get("Date", "")
    if raw_date:
        try:
            parsed = parsedate_to_datetime(raw_date)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc).isoformat()
        except (TypeError, ValueError):
            pass

    return ""


def build_sample_record(
    *,
    account_email: str,
    bucket: SampleBucket,
    message: dict[str, Any],
    headers: dict[str, str],
    raw_body: str,
) -> dict[str, Any] | None:
    cleaned_body = clean_authored_text(raw_body)
    if not cleaned_body:
        return None

    record = build_candidate_record(
        account_email=account_email,
        bucket=bucket,
        message=message,
        headers=headers,
        cleaned_body=cleaned_body,
    )
    if sample_rejection_reason(record):
        return None
    return record


def extract_payload_text(payload: dict[str, Any]) -> str:
    from app.services.gmail_readonly import _collect_payload_content, _html_to_text

    plain_text_parts: list[str] = []
    html_parts: list[str] = []
    _collect_payload_content(payload, plain_text_parts, html_parts)

    if plain_text_parts:
        return "\n\n".join(part.strip() for part in plain_text_parts if part.strip())

    converted_html = [_html_to_text(part) for part in html_parts]
    return "\n\n".join(part for part in converted_html if part)


def build_candidate_record(
    *,
    account_email: str,
    bucket: SampleBucket,
    message: dict[str, Any],
    headers: dict[str, str],
    cleaned_body: str,
) -> dict[str, Any]:
    record = {
        "account_email": account_email,
        "bucket": bucket.label,
        "gmail_message_id": message.get("id", ""),
        "gmail_thread_id": message.get("threadId", ""),
        "sent_at": parse_message_date(message, headers),
        "subject": headers.get("Subject", ""),
        "to": headers.get("To", ""),
        "cc": headers.get("Cc", ""),
        "word_count": sample_word_count(cleaned_body),
        "char_count": len(cleaned_body),
        "text": cleaned_body,
    }
    record["style_sample_score"] = style_sample_score(record)
    return record


def style_context_markdown(
    *,
    account_email: str,
    records: list[dict[str, Any]],
    max_excerpt_chars: int = 1800,
) -> str:
    total_words = sum(int(record.get("word_count") or 0) for record in records)
    buckets = sorted({str(record.get("bucket", "")) for record in records if record.get("bucket")})

    lines = [
        f"# Gmail Sent Writing Style Context: {account_email}",
        "",
        "Use these samples to infer the user's email style. Preserve the practical substance of any future reply, but mirror the cadence, directness, formatting, sign-off habits, and level of warmth shown here.",
        "",
        "Do not quote these samples back to recipients. Do not invent personal facts from the samples. Treat this file as private local context.",
        "",
        "## Corpus Summary",
        "",
        f"- Messages: {len(records)}",
        f"- Approximate words: {total_words}",
        f"- Buckets: {', '.join(buckets) if buckets else '(none)'}",
        "",
        "## Samples",
    ]

    for index, record in enumerate(records, start=1):
        text = str(record.get("text", "")).strip()
        if len(text) > max_excerpt_chars:
            text = text[:max_excerpt_chars].rstrip() + "\n[excerpt truncated]"

        lines.extend(
            [
                "",
                f"### Sample {index}: {record.get('sent_at', '')} | {record.get('bucket', '')}",
                "",
                f"Subject: {record.get('subject', '')}",
                "",
                "```text",
                text,
                "```",
            ]
        )

    return "\n".join(lines).strip() + "\n"
