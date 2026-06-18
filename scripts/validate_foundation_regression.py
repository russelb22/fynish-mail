from __future__ import annotations

import subprocess
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from shutil import copy2


ROOT_DIR = Path(__file__).resolve().parents[1]
BACKEND_DIR = ROOT_DIR / "backend"
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from _helpers import database
from app.services.accounts import restore_gmail_accounts_from_saved_tokens


PYTHON = ROOT_DIR / ".venv" / "bin" / "python"
PYTEST = ROOT_DIR / ".venv" / "bin" / "pytest"


def _run(command: list[str], label: str) -> tuple[bool, str]:
    print(f"$ {' '.join(command)}")
    completed = subprocess.run(
        command,
        cwd=ROOT_DIR,
        text=True,
        capture_output=True,
    )
    if completed.stdout:
        print(completed.stdout, end="" if completed.stdout.endswith("\n") else "\n")
    if completed.stderr:
        print(completed.stderr, end="" if completed.stderr.endswith("\n") else "\n")
    ok = completed.returncode == 0
    return ok, f"{'PASS' if ok else 'FAIL'} {label}"


def _live_preflight_command() -> tuple[list[str], str] | None:
    with database.get_connection() as conn:
        row = conn.execute(
            """
            SELECT m.id, m.account_email, m.current_category
            FROM messages m
            JOIN accounts a ON a.email_address = m.account_email
            WHERE a.provider = 'gmail_readonly'
              AND m.current_category IS NOT NULL
            ORDER BY m.reviewed ASC, m.received_at DESC, m.id DESC
            LIMIT 1
            """
        ).fetchone()
    if row is None:
        return None

    action = row["current_category"] or "keep"
    if action not in {"keep", "bulk_mail", "junk_review", "trash", "needs_review"}:
        action = "keep"
    return (
        [
            str(PYTHON),
            "scripts/validate_gmail_write_live.py",
            "--account",
            row["account_email"],
            "--message-id",
            str(int(row["id"])),
            "--action",
            action,
        ],
        "gmail write live preflight passes",
    )


def _ensure_live_gmail_accounts() -> None:
    with database.get_connection() as conn:
        count = int(
            conn.execute(
                "SELECT COUNT(*) FROM accounts WHERE provider = 'gmail_readonly'"
            ).fetchone()[0]
        )
    if count == 0:
        restore_gmail_accounts_from_saved_tokens()


@contextmanager
def _preserve_working_database():
    db_path = database.DATABASE_PATH
    backup_path: Path | None = None
    if db_path.exists():
        temp_dir = Path(tempfile.mkdtemp(prefix="fynish-db-backup-"))
        backup_path = temp_dir / db_path.name
        copy2(db_path, backup_path)
    try:
        yield
    finally:
        if backup_path is not None and backup_path.exists():
            copy2(backup_path, db_path)


def main() -> int:
    _ensure_live_gmail_accounts()
    checks: list[tuple[list[str], str]] = [
        ([str(PYTEST), "backend/tests"], "backend pytest suite passes"),
        ([str(PYTHON), "scripts/validate_foundation_migration.py"], "foundation migration validation passes"),
        ([str(PYTHON), "scripts/validate_gmail_readonly.py"], "gmail read-only validation passes"),
        ([str(PYTHON), "scripts/validate_gmail_write_dry_run.py"], "gmail write dry-run passes"),
        ([str(PYTHON), "scripts/validate_v1.py"], "core V1 validation passes"),
        ([str(PYTHON), "scripts/validate_safety_invariants.py"], "safety validation passes"),
        ([str(PYTHON), "scripts/validate_rules_flow.py"], "rules flow validation passes"),
        ([str(PYTHON), "scripts/validate_reminder_summary.py"], "reminder summary validation passes"),
        ([str(PYTHON), "scripts/compare_queue_snapshot.py"], "queue snapshot comparison passes"),
    ]

    print("Fynish Foundation Regression Validation")
    results: list[tuple[bool, str]] = []
    with _preserve_working_database():
        for command, label in checks:
            ok, line = _run(command, label)
            results.append((ok, line))
            if not ok:
                break
            if label == "gmail read-only validation passes":
                live_preflight = _live_preflight_command()
                if live_preflight is not None:
                    preflight_ok, preflight_line = _run(*live_preflight)
                    results.append((preflight_ok, preflight_line))
                    if not preflight_ok:
                        break

    passed = 0
    for ok, line in results:
        print(line)
        passed += 1 if ok else 0
    failed = len(results) - passed
    skipped = max(0, len(checks) - len(results))
    if skipped:
        print(f"SKIP {skipped} downstream checks not run after first failure")
    print(f"Result: {passed} passed, {failed} failed")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
