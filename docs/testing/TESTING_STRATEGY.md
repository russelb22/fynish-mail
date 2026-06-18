# Testing Strategy

## Philosophy

Do not wait for real Gmail integration to start testing.

The mocked Gmail layer remains the controlled harness for:

- queue UX validation
- classifier validation
- rule engine validation
- action semantics
- reminder summary generation
- safety checks

The repo now also includes real Gmail read-only import, queue reconciliation, and controlled live Gmail write paths. Those should still be validated primarily with deterministic tests and then with live credentials on a local machine.

## Layers

### 1. Deterministic backend validation

Highest priority in V1.

- unit tests
- integration tests against services
- standalone validation scripts

### 2. API-level validation

Confirms the backend contract used by the frontend:

- `/api/health`
- `/api/sync/unread`
- `/api/review-queue`
- `/api/reminders/summary`
- `/api/settings/notifications`
- `/api/rules`
- `/api/accounts/connect-gmail`
- `/api/accounts/connect-gmail-modify`

### 3. Frontend / UI regression

Now started as a light smoke-test layer.

Recommended later tool:

- Playwright

Current first-pass coverage:

- queue page loads against mocked data
- accounts render separately
- zero-count categories appear as compact chips
- row action changes update quick-rule suggestion defaults
- applying selected rows removes processed items from the UI
- reminder preview page renders summary content and localhost link
- settings page persists reminder scheduling preferences locally
- live Gmail write UI endpoints are covered at the backend integration layer

Current backend Gmail read-only coverage:

- OAuth connect endpoint fails cleanly when the Google client JSON is missing
- Gmail provider sync can import unread Inbox data through the shared queue pipeline
- body extraction prefers plain text and falls back to HTML-to-text
- attachment presence is detected without downloading attachment bodies
- queue reconciliation removes local rows that are no longer unread Inbox messages

## Phases

### Phase 1: mocked V1 validation

Use:

- `pytest backend/tests`
- `python scripts/validate_v1.py`
- `python scripts/validate_safety_invariants.py`
- `python scripts/validate_rules_flow.py`
- `python scripts/validate_reminder_summary.py`

### Phase 2: Gmail read-only validation

Current live-read validation command:

- `scripts/validate_gmail_readonly.py`

Rules:

- no label writes
- no inbox removal
- no trash
- no delete
- no mark-read
- no attachment download

### Phase 3: Gmail write dry-run and live validation

Current dry-run validation command:

- `scripts/validate_gmail_write_dry_run.py`

- `scripts/validate_gmail_write_live.py`

Rules:

- use controlled test messages only
- preserve unread
- no permanent delete
- no Gmail Trash in V1 behavior
- `Soft Trash` means `Fynish/Trash` plus `INBOX` removal only
- block execution unless `gmail.modify` scope is present
- block execution unless live writes are explicitly enabled
- verify post-write Gmail labels directly after execution
- keep identical rules from multiplying by reusing or re-enabling exact matches

### Phase 4: UI regression coverage

Current first pass:

- review queue smoke tests
- reminder preview smoke tests
- reminder settings persistence smoke tests

Add later:

- broader Playwright coverage for rules page and accounts page
- broader Playwright coverage for category-level bulk create-rules flows

## Recommended next scripts

These would add the most value beyond the current suite.

### `scripts/validate_rule_autoprocess_live.py`

Focus:

- explicit sender/domain/list rules auto-apply during sync
- matching messages do not surface in the visible queue
- `Needs Review` still remains visible
- live Gmail accounts only execute those matches when modify scope and live-write gating are present

This is a good next script because rule-driven auto-processing now has meaningful product impact.

### `scripts/validate_gmail_reconciliation.py`

Focus:

- message is imported while unread and in Inbox
- message is removed from the queue after leaving unread Inbox outside Fynish
- message can reappear in the queue if it returns to unread Inbox later

This is useful because queue trust now depends heavily on reconciliation behaving predictably.

### `scripts/validate_multi_account_live.py`

Focus:

- sync counts across multiple real Gmail accounts
- queue sections stay separated by account
- rule auto-processing and live writes stay scoped to the correct account
- stale-message reconciliation does not leak across accounts

This script becomes more important now that live multi-account usage is real.

### `scripts/audit_rules_catalog.py`

Focus:

- duplicate rules
- conflicting rules for the same normalized pattern
- disabled but still relevant rules
- high-volume rules by match count
- rules with zero matches that may be stale

This would be more of an operator/audit tool than a pass/fail validator, but it would help keep the growing rule set clean.

### `scripts/validate_postwrite_audit.py`

Focus:

- execute or inspect a small batch of controlled live writes
- fetch post-write Gmail label state for each message
- verify expected labels added and removed
- summarize mismatches in one report

This would complement the current one-message live validation with a broader audit view.

### `scripts/validate_ui_density_smoke.py`

Focus:

- compact masthead is present
- no duplicate top-of-page actions
- preview clamping keeps cards short
- empty categories render as compact chips
- scroll position is preserved after queue actions

This could be implemented as Playwright rather than Python, but documenting it as a script target keeps the outcome clear.

## Immediate recommendation

For active development, treat these as the main confidence commands:

```bash
python scripts/validate_v1.py
pytest backend/tests
```

For live Gmail work, add:

```bash
python scripts/validate_gmail_readonly.py
python scripts/validate_gmail_write_dry_run.py
```

If we add only one new script next, it should be:

```bash
python scripts/validate_rule_autoprocess_live.py
```

That would give the best coverage for the newest rule-driven queue behavior.

## Outstanding manual tests

The next most useful non-automated tests are:

- protected-category review with live inserted messages
- borderline bulk vs junk vs soft-trash classification review
- multi-account live isolation review
- post-write Gmail label audit across multiple action types
- longer-session rule hygiene review after more real mail accumulates
