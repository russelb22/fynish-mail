from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass


PROTECTED_KEYWORDS = {
    "account recovery",
    "bank",
    "benefits",
    "contractor",
    "family",
    "government",
    "healthcare",
    "insurance",
    "invoice",
    "irs",
    "job",
    "legal",
    "mortgage",
    "payroll",
    "receipt",
    "recruit",
    "rental",
    "repairs",
    "school",
    "security alert",
    "tax",
    "utilities",
    "utility",
}

BULK_KEYWORDS = {
    "deal",
    "digest",
    "discount",
    "limited time",
    "newsletter",
    "promotion",
    "register now",
    "sale",
    "save",
    "sponsor",
    "subscribe",
    "unsubscribe",
    "weekly",
}

TRASH_KEYWORDS = {
    "claim",
    "click",
    "confirm your payment",
    "final notice",
    "today",
    "urgent",
}

KEEP_KEYWORDS = {
    "family",
    "photos",
    "project",
    "schedule",
    "thanks",
}

SUSPICIOUS_DOMAIN_HINTS = ("biz", "ru", "top", "help")


@dataclass
class ClassificationResult:
    category: str
    confidence: float
    reasons: list[str]
    protected: bool
    protection_reasons: list[str]
    matched_rule_ids: list[int]


def extract_email(value: str | None) -> str:
    if not value:
        return ""
    match = re.search(r"<([^>]+)>", value)
    return (match.group(1) if match else value).strip().lower()


def extract_domain(value: str | None) -> str:
    email = extract_email(value)
    if "@" not in email:
        return ""
    return email.split("@", 1)[1]


def _normalize(text: str | None) -> str:
    return (text or "").strip().lower()


def _contains_any(text: str, needles: set[str]) -> list[str]:
    found = []
    for needle in needles:
        if needle in text:
            found.append(needle)
    return sorted(found)


def classify_message(
    message: dict,
    rules: list[dict],
    history_by_sender: Counter,
    history_by_domain: Counter,
) -> ClassificationResult:
    sender_email = extract_email(message.get("sender"))
    sender_domain = extract_domain(message.get("sender"))
    subject = _normalize(message.get("subject"))
    body = _normalize(message.get("body_preview"))
    combined = f"{subject}\n{body}"
    headers = message.get("headers") or {}

    reasons: list[str] = []
    protection_reasons: list[str] = []
    scores = {
        "keep": 0.15,
        "bulk_mail": 0.05,
        "junk_review": 0.05,
        "trash": 0.0,
    }

    matching_rules = []
    for rule in rules:
        if not rule["enabled"]:
            continue
        pattern = _normalize(rule["pattern"])
        if rule["rule_type"] == "sender" and sender_email == pattern:
            matching_rules.append(rule)
        elif rule["rule_type"] == "domain" and sender_domain == pattern:
            matching_rules.append(rule)
        elif rule["rule_type"] == "subject_contains" and pattern in subject:
            matching_rules.append(rule)
        elif rule["rule_type"] == "body_contains" and pattern in body:
            matching_rules.append(rule)
        elif rule["rule_type"] == "list_id" and pattern in _normalize(headers.get("List-ID")):
            matching_rules.append(rule)

    keep_rules = [rule for rule in matching_rules if rule["action"] == "keep"]
    if keep_rules:
        reasons.append("Explicit Always Keep rule matched")
        return ClassificationResult(
            category="keep",
            confidence=0.99,
            reasons=reasons,
            protected=True,
            protection_reasons=["Always Keep rule overrides other signals"],
            matched_rule_ids=[rule["id"] for rule in keep_rules],
        )

    protected_hits = _contains_any(combined, PROTECTED_KEYWORDS)
    if protected_hits:
        protection_reasons.append(
            f"Protected keywords detected: {', '.join(protected_hits[:3])}"
        )
        scores["keep"] += 0.45
        scores["junk_review"] += 0.1

    action_rules = [rule for rule in matching_rules if rule["action"] != "keep"]
    if action_rules:
        action = action_rules[0]["action"]
        reasons.append(f"Explicit {action.replace('_', ' ')} rule matched")
        confidence = 0.98 if action != "needs_review" else 0.9
        if action == "trash" and protection_reasons:
            reasons.append("Protected detection blocked automatic trash")
            return ClassificationResult(
                category="needs_review",
                confidence=0.84,
                reasons=reasons,
                protected=True,
                protection_reasons=protection_reasons,
                matched_rule_ids=[rule["id"] for rule in action_rules],
            )
        return ClassificationResult(
            category=action,
            confidence=confidence,
            reasons=reasons,
            protected=bool(protection_reasons),
            protection_reasons=protection_reasons,
            matched_rule_ids=[rule["id"] for rule in action_rules],
        )

    sender_bulk_hits = history_by_sender.get(f"{sender_email}:bulk_mail", 0)
    sender_keep_hits = history_by_sender.get(f"{sender_email}:keep", 0)
    domain_bulk_hits = history_by_domain.get(f"{sender_domain}:bulk_mail", 0)
    if sender_bulk_hits or domain_bulk_hits:
        scores["bulk_mail"] += 0.35
        reasons.append("Sender/domain previously approved as Bulk Mail")
    if sender_keep_hits:
        scores["keep"] += 0.35
        reasons.append("Sender previously kept")

    if headers.get("List-Unsubscribe"):
        scores["bulk_mail"] += 0.35
        reasons.append("List-Unsubscribe header found")
    if headers.get("List-ID"):
        scores["bulk_mail"] += 0.2
        reasons.append("List-ID header found")
    if _normalize(headers.get("Precedence")) == "bulk":
        scores["bulk_mail"] += 0.25
        reasons.append("Precedence: bulk header found")

    bulk_hits = _contains_any(combined, BULK_KEYWORDS)
    if bulk_hits:
        scores["bulk_mail"] += min(0.35, 0.08 * len(bulk_hits))
        reasons.append(f"Promotional wording detected: {', '.join(bulk_hits[:3])}")

    trash_hits = _contains_any(combined, TRASH_KEYWORDS)
    if trash_hits:
        scores["trash"] += min(0.5, 0.1 * len(trash_hits))
        reasons.append(f"Spam-like urgency detected: {', '.join(trash_hits[:3])}")

    if message.get("reply_to") and extract_domain(message.get("reply_to")) != sender_domain:
        scores["junk_review"] += 0.35
        scores["trash"] += 0.1
        reasons.append("Reply-To domain does not match sender domain")

    if sender_domain and any(sender_domain.endswith(f".{hint}") for hint in SUSPICIOUS_DOMAIN_HINTS):
        scores["junk_review"] += 0.25
        reasons.append("Suspicious sender domain")

    if message.get("has_attachments") and not protection_reasons:
        scores["junk_review"] += 0.1
        reasons.append("Attachment present")

    keep_hits = _contains_any(combined, KEEP_KEYWORDS)
    if keep_hits:
        scores["keep"] += min(0.25, 0.05 * len(keep_hits))
        reasons.append(f"Personal or conversational wording detected: {', '.join(keep_hits[:2])}")

    if protection_reasons and scores["trash"] >= 0.45:
        reasons.append("Protected detection blocked Likely Trash recommendation")
        return ClassificationResult(
            category="needs_review",
            confidence=0.77,
            reasons=reasons,
            protected=True,
            protection_reasons=protection_reasons,
            matched_rule_ids=[],
        )

    ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)
    category, top_score = ranked[0]
    runner_up = ranked[1][1]
    confidence = max(0.5, min(0.99, 0.55 + (top_score - runner_up)))

    if protection_reasons and category == "junk_review":
        category = "needs_review"
        confidence = min(confidence, 0.8)
        reasons.append("Protected signals pushed message into Needs Review")

    if protection_reasons and category == "keep":
        confidence = max(confidence, 0.82)

    if not reasons:
        reasons.append("No strong bulk or risk signals found")

    return ClassificationResult(
        category=category,
        confidence=round(confidence, 2),
        reasons=reasons[:4],
        protected=bool(protection_reasons),
        protection_reasons=protection_reasons,
        matched_rule_ids=[],
    )


def serialize_headers(headers: dict) -> str:
    return json.dumps(headers)
