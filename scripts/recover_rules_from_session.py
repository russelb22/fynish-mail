from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.review_queue import reclassify_pending_messages
from app.services.rules import create_rule, list_rules


RECOVERED_RULES: list[tuple[str, str]] = [
    ("example.net", "trash"),
    ("alpha.coldinvesting.com", "junk_review"),
    ("brief.profitstrategyalerts.com", "junk_review"),
    ("daily.futureslabresearch.com", "junk_review"),
    ("ddc.dividenddriveclub.com", "junk_review"),
    ("digest.northcapitaly.com", "junk_review"),
    ("e.dcsg.com", "junk_review"),
    ("e.majorgrossprofit.com", "junk_review"),
    ("e.zoro.com", "junk_review"),
    ("eaf.eliteassetforum.com", "junk_review"),
    ("email.cyberimpact.com", "junk_review"),
    ("email-motherearthnews.com", "junk_review"),
    ("em.activetraderdaily.com", "junk_review"),
    ("em.angi.com", "junk_review"),
    ("exct.stansberryresearch.com", "junk_review"),
    ("exclusive.premiumretiring.com", "junk_review"),
    ("gci.grandcryptoinsider.com", "junk_review"),
    ("global.metamail.com", "junk_review"),
    ("lg.behindthemarkets.com", "junk_review"),
    ("mail.beehiiv.com", "junk_review"),
    ("mind.profitadvisornation.com", "junk_review"),
    ("newsletter.theneurondaily.com", "junk_review"),
    ("news.markettechadvice.com", "junk_review"),
    ("news.thecapitalchronicle.com", "junk_review"),
    ("news.therisktolerance.com", "junk_review"),
    ("pg.profitglyph.com", "junk_review"),
    ("prime.financexpertnow.com", "junk_review"),
    ("recipe-box.co", "junk_review"),
    ("rorra.com", "junk_review"),
    ("s.kohls.com", "junk_review"),
    ("substack.com", "junk_review"),
    ("winner-promo.top", "junk_review"),
    ("your.bankstreetjournal.com", "junk_review"),
    ("your.moneyandwelfare.com", "junk_review"),
]


def main() -> int:
    before_ids = {rule["id"] for rule in list_rules()}
    for domain, action in RECOVERED_RULES:
        create_rule(
            {
                "scope": "global",
                "rule_type": "domain",
                "pattern": domain,
                "action": action,
            }
        )
    after_rules = list_rules()
    after_ids = {rule["id"] for rule in after_rules}
    created_count = len(after_ids - before_ids)
    enabled_count = sum(1 for rule in after_rules if rule["enabled"])
    reclassified = reclassify_pending_messages()

    print("Recovered rules from prior session notes")
    print(f"Created or re-enabled target rules: {len(RECOVERED_RULES)}")
    print(f"New rule rows created: {created_count}")
    print(f"Enabled rules now present: {enabled_count}")
    print(f"Queue reclassified: {reclassified['reclassified_messages']} messages")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
