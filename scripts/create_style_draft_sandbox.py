from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.style_draft_sandbox import build_draft_sandbox


DEFAULT_SAMPLES_ROOT = BACKEND_DIR / "data" / "writing_samples"


def _safe_email_filename(email_address: str) -> str:
    return "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in email_address.strip().lower()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create local synthetic draft-evaluation prompt packets from a writing style profile."
    )
    parser.add_argument("--account", required=True, help="Gmail account email for the style profile")
    parser.add_argument(
        "--style-profile",
        type=Path,
        help="Optional explicit style_profile.md path",
    )
    parser.add_argument(
        "--scenarios-json",
        type=Path,
        help="Optional JSON file of synthetic scenarios",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Optional output directory. Default: account/draft_sandbox",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account_dir = DEFAULT_SAMPLES_ROOT / _safe_email_filename(args.account)
    style_profile_path = args.style_profile or account_dir / "style_profile.md"
    output_dir = args.out_dir or account_dir / "draft_sandbox"

    if not style_profile_path.exists():
        raise SystemExit(f"Style profile not found: {style_profile_path}")

    result = build_draft_sandbox(
        account_email=args.account,
        style_profile_path=style_profile_path,
        scenarios_path=args.scenarios_json,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(result.manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for filename, content in result.prompt_packets:
        (output_dir / filename).write_text(content, encoding="utf-8")

    print("Style Draft Sandbox")
    print(f"Account: {args.account}")
    print(f"Scenarios: {result.manifest['scenario_count']}")
    print(f"Output directory: {output_dir}")
    print(f"Manifest: {manifest_path}")
    for scenario in result.manifest["scenarios"]:
        print(f"Prompt packet: {output_dir / scenario['prompt_packet']}")


if __name__ == "__main__":
    main()
