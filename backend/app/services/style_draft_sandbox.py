from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


DEFAULT_SCENARIOS = [
    {
        "id": "schedule-follow-up",
        "from": "Maya <maya@example.com>",
        "subject": "Follow up on next week's review",
        "body": (
            "Hi Russel,\n\n"
            "Could you take a look at the latest notes before our review next week? "
            "I am especially curious whether the scope feels too broad and whether "
            "we should pull anything out before sharing it with the rest of the team.\n\n"
            "Thanks,\nMaya"
        ),
        "draft_goal": "Acknowledge the request, agree to review, and suggest a practical next step.",
    },
    {
        "id": "gentle-boundary",
        "from": "Daniel <daniel@example.com>",
        "subject": "Quick favor today?",
        "body": (
            "Hey Russel,\n\n"
            "I know this is short notice, but could you help me rewrite the whole "
            "proposal today? It is due tomorrow morning and I am worried it is not clear enough.\n\n"
            "Daniel"
        ),
        "draft_goal": "Be helpful but set a realistic boundary; offer a smaller useful contribution.",
    },
    {
        "id": "product-feedback",
        "from": "Ari <ari@example.com>",
        "subject": "Thoughts on the prototype",
        "body": (
            "Russel,\n\n"
            "I tried the prototype. The main workflow makes sense, but the setup still "
            "feels confusing. I think a new user might not understand what to do first. "
            "Do you want me to write up more detailed feedback?\n\n"
            "Ari"
        ),
        "draft_goal": "Thank them, ask for the most useful feedback, and keep the reply concise.",
    },
]


@dataclass(frozen=True)
class DraftSandboxResult:
    manifest: dict[str, Any]
    prompt_packets: list[tuple[str, str]]


def load_style_profile(path: Path) -> str:
    return path.read_text(encoding="utf-8").strip()


def load_scenarios(path: Path | None = None) -> list[dict[str, Any]]:
    if path is None:
        return DEFAULT_SCENARIOS
    return json.loads(path.read_text(encoding="utf-8"))


def render_prompt_packet(
    *,
    account_email: str,
    style_profile: str,
    scenario: dict[str, Any],
) -> str:
    return f"""# Draft Sandbox Packet: {scenario["id"]}

## Task

Draft a reply as Russel from {account_email}. Use the writing style profile below as private context. Do not quote or reveal the profile. Do not invent facts. Answer only the synthetic inbound email.

## Draft Goal

{scenario["draft_goal"]}

## Writing Style Profile

{style_profile}

## Synthetic Inbound Email

From: {scenario["from"]}
Subject: {scenario["subject"]}

```text
{scenario["body"]}
```

## Output

Return only the drafted email body.
"""


def build_draft_sandbox(
    *,
    account_email: str,
    style_profile_path: Path,
    scenarios_path: Path | None = None,
) -> DraftSandboxResult:
    style_profile = load_style_profile(style_profile_path)
    scenarios = load_scenarios(scenarios_path)
    packets = [
        (
            f"{scenario['id']}.md",
            render_prompt_packet(
                account_email=account_email,
                style_profile=style_profile,
                scenario=scenario,
            ),
        )
        for scenario in scenarios
    ]
    manifest = {
        "account_email": account_email,
        "style_profile_path": str(style_profile_path),
        "scenario_count": len(scenarios),
        "scenarios": [
            {
                "id": scenario["id"],
                "subject": scenario["subject"],
                "draft_goal": scenario["draft_goal"],
                "prompt_packet": f"{scenario['id']}.md",
            }
            for scenario in scenarios
        ],
    }
    return DraftSandboxResult(manifest=manifest, prompt_packets=packets)
