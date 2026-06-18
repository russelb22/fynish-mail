#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.core.config import APP_ENV, GMAIL_TOKEN_STORAGE_MODE, GOOGLE_CLIENT_SECRETS_PATH  # noqa: E402


def _check(condition: bool, label: str) -> tuple[bool, str]:
    return condition, f"{'PASS' if condition else 'FAIL'} {label}"


def main() -> int:
    checks: list[tuple[bool, str]] = []

    checks.append(_check(GOOGLE_CLIENT_SECRETS_PATH.exists(), "Google OAuth client secret file exists"))
    checks.append(
        _check(
            GOOGLE_CLIENT_SECRETS_PATH.suffix.lower() == ".json",
            "Google OAuth client secret path uses a .json file",
        )
    )

    if GOOGLE_CLIENT_SECRETS_PATH.exists():
        try:
            payload = json.loads(GOOGLE_CLIENT_SECRETS_PATH.read_text(encoding="utf-8"))
            checks.append(
                _check(
                    isinstance(payload, dict) and ("installed" in payload or "web" in payload),
                    "Google OAuth client secret file contains installed or web client config",
                )
            )
        except json.JSONDecodeError:
            checks.append((False, "FAIL Google OAuth client secret file contains valid JSON"))

    if APP_ENV == "cloud":
        checks.append(
            _check(
                GMAIL_TOKEN_STORAGE_MODE == "database",
                "cloud mode uses database-backed Gmail token storage",
            )
        )

    failed = 0
    for ok, line in checks:
        print(line)
        if not ok:
            failed += 1

    if failed:
        print(f"\nGoogle OAuth config validation failed: {failed} check(s) failed.")
        return 1

    print("\nGoogle OAuth config validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
