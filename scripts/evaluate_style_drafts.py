from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.style_draft_evaluation import (
    evaluate_sandbox,
    render_evaluation_markdown,
)


DEFAULT_SAMPLES_ROOT = BACKEND_DIR / "data" / "writing_samples"


def _safe_email_filename(email_address: str) -> str:
    return "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in email_address.strip().lower()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate local synthetic style draft outputs against a simple rubric."
    )
    parser.add_argument("--account", required=True, help="Gmail account email for the sandbox")
    parser.add_argument(
        "--sandbox-dir",
        type=Path,
        help="Optional explicit draft sandbox directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account_dir = DEFAULT_SAMPLES_ROOT / _safe_email_filename(args.account)
    sandbox_dir = args.sandbox_dir or account_dir / "draft_sandbox"

    if not (sandbox_dir / "manifest.json").exists():
        raise SystemExit(f"Draft sandbox manifest not found: {sandbox_dir / 'manifest.json'}")

    evaluations = evaluate_sandbox(sandbox_dir)
    markdown = render_evaluation_markdown(evaluations)
    markdown_path = sandbox_dir / "draft_evaluation.md"
    json_path = sandbox_dir / "draft_evaluation.json"

    markdown_path.write_text(markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps([asdict(item) for item in evaluations], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    avg_score = sum(item.score for item in evaluations) / len(evaluations) if evaluations else 0
    print("Style Draft Evaluation")
    print(f"Account: {args.account}")
    print(f"Drafts evaluated: {len(evaluations)}")
    print(f"Average score: {avg_score:.1f}/100")
    print(f"Markdown evaluation: {markdown_path}")
    print(f"JSON evaluation: {json_path}")


if __name__ == "__main__":
    main()
