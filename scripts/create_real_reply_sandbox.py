from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.services.real_reply_sandbox import build_real_reply_sandbox


DEFAULT_SAMPLES_ROOT = BACKEND_DIR / "data" / "writing_samples"


def _safe_email_filename(email_address: str) -> str:
    return "".join(
        char if char.isalnum() or char in "._-" else "_"
        for char in email_address.strip().lower()
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create local draft prompt packets from likely reply-worthy Fynish messages."
    )
    parser.add_argument("--style-account", required=True, help="Gmail account with style_profile.md")
    parser.add_argument(
        "--message-account",
        help="Optional Fynish message account to filter inbound candidates",
    )
    parser.add_argument(
        "--style-profile",
        type=Path,
        help="Optional explicit style_profile.md path",
    )
    parser.add_argument("--limit", type=int, default=5, help="Maximum prompt packets to create")
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Optional output directory. Default: account/real_reply_sandbox",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    account_dir = DEFAULT_SAMPLES_ROOT / _safe_email_filename(args.style_account)
    style_profile_path = args.style_profile or account_dir / "style_profile.md"
    output_dir = args.out_dir or account_dir / "real_reply_sandbox"

    if args.limit < 1:
        raise SystemExit("--limit must be at least 1")
    if not style_profile_path.exists():
        raise SystemExit(f"Style profile not found: {style_profile_path}")

    manifest, packets = build_real_reply_sandbox(
        style_account=args.style_account,
        style_profile_path=style_profile_path,
        message_account=args.message_account,
        limit=args.limit,
    )

    output_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for filename, content in packets:
        (output_dir / filename).write_text(content, encoding="utf-8")

    print("Real Reply Sandbox")
    print(f"Style account: {args.style_account}")
    print(f"Message account: {args.message_account or '(all)'}")
    print(f"Candidates: {manifest['candidate_count']}")
    print(f"Output directory: {output_dir}")
    print(f"Manifest: {manifest_path}")
    for candidate in manifest["candidates"]:
        print(f"Prompt packet: {output_dir / candidate['prompt_packet']}")


if __name__ == "__main__":
    main()
