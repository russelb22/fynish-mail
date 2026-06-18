from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.writing_style_profile import analyze_style, load_jsonl


DEFAULT_SAMPLES_ROOT = BACKEND_DIR / "data" / "writing_samples"


def _safe_email_filename(email_address: str) -> str:
    return "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in email_address.strip().lower()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build a private local derived writing style profile from sent-mail samples."
    )
    parser.add_argument("--account", required=True, help="Gmail account email to profile")
    parser.add_argument(
        "--samples-jsonl",
        type=Path,
        help="Optional explicit sent_samples.jsonl path",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Optional output directory. Default: the account writing_samples directory.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account_dir = DEFAULT_SAMPLES_ROOT / _safe_email_filename(args.account)
    samples_path = args.samples_jsonl or account_dir / "sent_samples.jsonl"
    output_dir = args.out_dir or account_dir

    if not samples_path.exists():
        raise SystemExit(f"Samples file not found: {samples_path}")

    records = load_jsonl(samples_path)
    profile = analyze_style(records, account_email=args.account)

    output_dir.mkdir(parents=True, exist_ok=True)
    markdown_path = output_dir / "style_profile.md"
    json_path = output_dir / "style_profile.json"

    markdown_path.write_text(profile.markdown, encoding="utf-8")
    json_path.write_text(
        json.dumps(profile.summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    print("Writing Style Profile")
    print(f"Account: {args.account}")
    print(f"Samples read: {profile.summary['sample_count']}")
    print(f"Total words: {profile.summary['total_words']}")
    print(f"Average words/message: {profile.summary['avg_words']}")
    print(f"Length: {profile.summary['length_style']}")
    print(f"Directness: {profile.summary['directness_style']}")
    print(f"Warmth: {profile.summary['warmth_style']}")
    print(f"Markdown profile: {markdown_path}")
    print(f"JSON profile: {json_path}")


if __name__ == "__main__":
    main()
