# V1 Test Plan

## Purpose

Validate the current Fynish prototype across mocked mail, live Gmail read-only import, and controlled live Gmail writes.

## Primary goals

- Prove queue generation works from mocked unread Inbox messages
- Prove real Gmail read-only import feeds the same queue safely
- Prove classification is deterministic and explainable
- Prove rules, auto-apply behavior, reclassification, and bulk-apply behavior work
- Protect the V1 safety model
- Validate reminder summary generation
- Validate reminder settings persistence for the future V2 scheduler

## Scope

### Backend unit tests

- `backend/tests/unit/test_classifier.py`
- `backend/tests/unit/test_rules.py`
- `backend/tests/unit/test_review_queue.py`
- `backend/tests/unit/test_reminders.py`
- `backend/tests/unit/test_notification_settings.py`
- `backend/tests/unit/test_gmail_readonly.py`
- `backend/tests/unit/test_gmail_write_planner.py`
- `backend/tests/unit/test_gmail_write_executor.py`

### Backend integration tests

- `backend/tests/integration/test_sync_and_queue.py`
- `backend/tests/integration/test_apply_actions.py`
- `backend/tests/integration/test_gmail_readonly_sync.py`
- `backend/tests/integration/test_notification_settings_api.py`
- `backend/tests/integration/test_gmail_live_actions_api.py`
- `backend/tests/integration/test_quick_rules.py`
- `backend/tests/integration/test_safety_invariants.py`

### Validation scripts

- `scripts/reset_dev_db.py`
- `scripts/seed_mock_data.py`
- `scripts/validate_v1.py`
- `scripts/smoke_test_api.py`
- `scripts/print_queue_snapshot.py`
- `scripts/compare_queue_snapshot.py`
- `scripts/validate_safety_invariants.py`
- `scripts/validate_rules_flow.py`
- `scripts/validate_reminder_summary.py`
- `scripts/validate_gmail_readonly.py`
- `scripts/validate_gmail_write_dry_run.py`
- `scripts/validate_gmail_write_live.py`
- `scripts/inject_test_messages.py`

### Proposed next validation scripts

These are not implemented yet, but they are the next most useful additions based on the current app shape.

- `scripts/validate_gmail_reconciliation.py`
  - purpose: prove that refresh removes stale local queue rows when messages leave unread Inbox outside Fynish, and restores them if they return later
  - why: this is now core to the live Gmail experience and deserves its own focused validation path

- `scripts/validate_rule_autoprocess_live.py`
  - purpose: validate that explicit matching rules auto-apply during sync and keep messages out of the visible queue
  - why: this is one of the most important new behaviors and currently only has unit/integration coverage, not a focused end-to-end script

- `scripts/audit_rules_catalog.py`
  - purpose: report duplicate, conflicting, disabled, and low-signal rules, plus summarize rule coverage by domain/sender
  - why: the real Inbox workflow is now generating a larger rule corpus, and periodic rule hygiene will help prevent drift

- `scripts/validate_multi_account_live.py`
  - purpose: validate that sync, queue grouping, actions, and rule effects stay isolated across multiple connected Gmail accounts
  - why: multi-account behavior is now a real product path, not just a spec item

- `scripts/validate_postwrite_audit.py`
  - purpose: re-fetch Gmail label state after a set of live writes and compare expected vs actual label outcomes in one batch report
  - why: the current live-write validation is message-oriented; a batch audit script would make broader live verification easier

- `scripts/validate_ui_density_smoke.py`
  - purpose: capture key queue-layout expectations like compact masthead, preview clamping, empty-category chips, and scroll preservation
  - why: the queue layout is being tuned actively, and a focused UI-density smoke layer would protect the improvements

### Convenience runner

- `Makefile`

Useful shortcuts:

- `make test`
- `make validate`
- `make check`
- `make foundation-check`
- `make compare-snapshot`
- `make test-e2e`
- `make gmail-readonly`
- `make gmail-write-dry-run`
- `make inject-test-mail`

### Foundation regression runner

- `scripts/validate_foundation_regression.py`
- `make foundation-check`

This bundle is meant for post-refactor stabilization. It runs:

- full backend pytest
- V1 validation
- safety validation
- rules-flow validation
- reminder validation
- queue snapshot comparison
- foundation migration validation
- Gmail read-only validation
- Gmail write dry-run validation
- Gmail live-write preflight when a connected Gmail message is available locally

It also restores saved Gmail account rows from local token files before the live Gmail checks, so the bundle can recover cleanly after a mock-only reset.

## Recommended run order

1. `python scripts/reset_dev_db.py`
2. `python scripts/validate_v1.py`
3. `pytest backend/tests`
4. `python scripts/smoke_test_api.py`
5. `python scripts/validate_gmail_readonly.py`

## What passing V1 means

- 30 mocked unread messages sync cleanly across 3 accounts
- queue grouping and category counts stay stable
- queue account/category ordering stays stable
- key message-level expectations stay stable
- checkbox default-selection thresholds stay correct
- rules are saved and reclassify the pending queue
- explicit matching rules can auto-apply during sync and keep messages out of the queue
- identical rules are reused or re-enabled instead of duplicated
- approved actions are logged and remove processed rows from the queue
- reminder summary matches the queue state
- reminder settings survive API updates and UI reloads
- Gmail read-only import keeps `INBOX`/`UNREAD` intact in stored state
- Gmail queue reconciliation removes stale local rows when messages leave Inbox outside Fynish
- controlled live Gmail writes verify the expected post-write labels directly from Gmail
- no V1 safety invariants are broken

## Suggested next implementation order

If more test scripts are added next, this is the recommended order:

1. `scripts/validate_rule_autoprocess_live.py`
2. `scripts/validate_gmail_reconciliation.py`
3. `scripts/validate_multi_account_live.py`
4. `scripts/audit_rules_catalog.py`
5. `scripts/validate_postwrite_audit.py`
6. `scripts/validate_ui_density_smoke.py`

## Next manual test session

When we return to live testing, the highest-value manual checks are:

1. Run another protected-category insert bundle and confirm:
   - protected messages stay visible
   - explicit `trash` rules still auto-process and skip the queue

2. Run a borderline marketing bundle and review:
   - `Bulk Mail` vs `Junk Review`
   - `Junk Review` vs `Soft Trash`
   - whether preview text and reasons are enough to make fast decisions

3. Run a multi-account live pass:
   - insert different synthetic bundles into both real Gmail accounts
   - confirm queue separation and rule scoping by account

4. Run a post-write audit pass:
   - process one message each as `Keep`, `Bulk`, `Junk`, and `Soft Trash`
   - verify Gmail labels and Inbox removal after refresh

5. Run rule hygiene after a larger session:
   - check for stale, duplicate, or conflicting rules
   - confirm exact duplicate prevention is still working
