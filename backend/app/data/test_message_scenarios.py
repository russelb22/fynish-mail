from __future__ import annotations

from copy import deepcopy


SCENARIOS = {
    "personal_keep": {
        "sender": "Aunt May <aunt.may@example.org>",
        "reply_to": "aunt.may@example.org",
        "subject": "Checking in before Sunday dinner",
        "snippet": "Can you bring dessert on Sunday?",
        "body_preview": "Checking in before Sunday dinner. Can you bring dessert, and do you still want the family photos?",
        "headers": {},
        "has_attachments": 0,
    },
    "newsletter_bulk": {
        "sender": "Kitchen Mailer <hello@recipe-box.co>",
        "reply_to": "hello@recipe-box.co",
        "subject": "This week's dinner newsletter",
        "snippet": "A fresh digest of weeknight recipes.",
        "body_preview": "This newsletter includes a weekly digest of recipes, grocery shortcuts, and unsubscribe options for future mailings.",
        "headers": {
            "List-Unsubscribe": "<mailto:leave@recipe-box.co>",
            "List-ID": "newsletter.recipe-box",
            "Precedence": "bulk",
        },
        "has_attachments": 0,
    },
    "suspicious_junk": {
        "sender": "Prize Center <claim@winner-promo.top>",
        "reply_to": "claim@winner-promo.top",
        "subject": "Claim your reward before midnight",
        "snippet": "Final notice for your pending reward.",
        "body_preview": "Claim your reward before midnight today. Final notice. Click now and confirm your payment details to release the prize.",
        "headers": {},
        "has_attachments": 0,
    },
    "security_keep": {
        "sender": "Security Alerts <alerts@example.net>",
        "reply_to": "alerts@example.net",
        "subject": "Security alert for your account",
        "snippet": "We noticed a sign-in from a new device.",
        "body_preview": "A new sign-in was detected for your account. If this was not you, review your account activity immediately.",
        "headers": {},
        "has_attachments": 0,
    },
    "tax_protected": {
        "sender": "Tax Filing Center <review@refund-release.ru>",
        "reply_to": "review@refund-release.ru",
        "subject": "Final notice about your tax refund",
        "snippet": "Review your tax refund status today.",
        "body_preview": "Final notice about your tax refund. Review the status and confirm details today to avoid processing delays.",
        "headers": {},
        "has_attachments": 0,
    },
    "alarm_notification": {
        "sender": "\"Example Security Service\" <notifications@example.net>",
        "reply_to": "notifications@example.net",
        "subject": "Bridgland: Panel was Armed Away by Russle Brunton at 7:42 am",
        "snippet": "Your security system reports a recent state change.",
        "body_preview": "Your security system reports a recent state change for the example property. Review the latest arming event details.",
        "headers": {},
        "has_attachments": 0,
    },
}


BUNDLES = {
    "mixed": [
        "personal_keep",
        "newsletter_bulk",
        "suspicious_junk",
        "security_keep",
        "tax_protected",
        "alarm_notification",
    ],
    "marketing": [
        "newsletter_bulk",
        "suspicious_junk",
    ],
    "protected": [
        "security_keep",
        "tax_protected",
        "alarm_notification",
    ],
}


def scenario_names() -> list[str]:
    return sorted(SCENARIOS.keys())


def bundle_names() -> list[str]:
    return sorted(BUNDLES.keys())


def build_scenario(name: str) -> dict:
    return deepcopy(SCENARIOS[name])


def build_bundle(name: str) -> list[dict]:
    return [build_scenario(item) for item in BUNDLES[name]]
