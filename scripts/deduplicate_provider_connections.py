#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from app.db.provider_connection_cleanup import deduplicate_provider_connections  # noqa: E402


def main() -> int:
    result = deduplicate_provider_connections()
    print(
        "Provider connection deduplication complete: "
        f"{result['groups_processed']} group(s) processed, "
        f"{result['rows_deleted']} row(s) deleted, "
        f"{result['remaining_duplicate_groups']} duplicate group(s) remain."
    )
    return 0 if result["remaining_duplicate_groups"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
