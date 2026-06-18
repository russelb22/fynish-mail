# Review Queue Staged Commit Implementation Spec

Status: Batch 1, Slice 3, Slice 4, Slice 5, and Slice 6 implemented, deployed, and validated on the VM on 2026-06-04. Slice 1 added the backend commit API; Slice 2 added the frontend staged Review Queue for `This Message` actions; Slice 3 added staged `Always Keep Domain` / `Always Junk Domain` rule-teaching actions; Slice 4 added strict freshness checks and persisted idempotent commit replay; Slice 5 added account-grouped staged review polish and staged summary metrics; Slice 6 added keyboard shortcuts and current Playwright smoke coverage.

## Purpose

Implement client-side staged review plus a backend batch commit endpoint so the Review Queue feels immediate while Gmail and database writes remain explicit, server-side, and auditable.

The implementation target is not backend queue caching. The first version should use:

- a server-loaded Review Queue
- a browser-side staged working set
- an explicit `Commit Changes` button
- a backend batch commit endpoint
- per-message commit results

The user should be able to click through multiple Review Queue messages without waiting on Gmail or the backend after each click. Nothing should mutate Gmail or Fynish's database until the user commits.

## Product Decision

Proceed with explicit staging and manual commit.

Do not implement hidden write-behind behavior. Staged changes must be visible, undoable, and discardable.

## Current Baseline

Current Review Queue behavior:

- `GET /api/review-queue` loads grouped queue messages.
- `This Message` actions call the backend immediately.
- Modify-capable Gmail accounts execute live Gmail changes through `POST /api/messages/{message_id}/live-execute`.
- Non-live actions use `POST /api/messages/{message_id}/action`.
- Rule-teaching actions create a rule and immediately apply the action to the source message.
- The UI refreshes the queue after most actions.

Relevant current files:

- `frontend/src/App.tsx`
- `frontend/src/api.ts`
- `frontend/src/types.ts`
- `backend/app/api/routes.py`
- `backend/app/schemas/api.py`
- `backend/app/services/review_queue.py`
- `backend/app/services/gmail_write_executor.py`
- `backend/app/core/errors.py`

## Target UX

When a user clicks a `This Message` action:

1. The message is removed from the active queue immediately.
2. A compact staged toolbar appears.
3. The toolbar shows staged count, `Undo Last`, `Discard`, and `Commit Changes`.
4. A compact staged section lists staged messages and actions.
5. The user may keep reviewing more messages.
6. Gmail and database state remain unchanged until commit.
7. On commit, successful messages remain gone.
8. Failed messages return to the active queue with an actionable error.

Initial staged toolbar copy:

`3 changes staged`

Initial controls:

- `Undo Last`
- `Discard`
- `Commit Changes`

The active queue should not show staged messages as if they are still pending normal review. The staged section should be visible enough that the user understands those messages are pending commit.

Current staged polish:

- staged messages are grouped by receiving account
- the app summary shows both active queued messages and staged messages
- the staged panel remains visible until all staged changes are committed, undone, or discarded

## Non-Goals For The First Deploy Batch

Do not include these in the first two slices:

- auto-commit thresholds
- keyboard shortcuts
- full backend queue/session cache
- offline behavior
- optimistic Gmail state labels beyond the staged section

## Data Model

### Queue Message Version

Add a per-message version token to queue responses.

Preferred field name:

```ts
state_version: string | null
```

Backend source:

- use `messages.updated_at` if available
- otherwise use `classification_results.created_at`
- otherwise return `null`

This token is used to detect stale browser state at commit time.

### Frontend Staged Action

```ts
type StagedQueueAction = {
  clientActionId: string
  messageId: number
  accountEmail: string
  sender: string
  senderEmail?: string
  senderDomain: string
  subject: string
  action: Category
  actionLabel: string
  expectedVersion: string | null
  stagedAt: string
}
```

Keep enough metadata in the staged action to render the staged section after removing the message from the active queue.

### Backend Request

Endpoint:

`POST /api/review-queue/staged-actions/commit`

Request schema:

```json
{
  "idempotency_key": "browser-generated-uuid",
  "actions": [
    {
      "client_action_id": "browser-action-uuid",
      "message_id": 123,
      "action": "junk_review",
      "expected_version": "2026-06-04T15:25:30.123456+00:00"
    }
  ]
}
```

Validation:

- `idempotency_key` is required and non-empty.
- `actions` must contain at least one item.
- each `message_id` must be positive.
- each `action` must be one of the existing `Category` values.
- duplicate `message_id` values in one request should return per-item duplicate failures, not crash the whole request.

### Backend Response

```json
{
  "committed_count": 1,
  "failed_count": 0,
  "results": [
    {
      "client_action_id": "browser-action-uuid",
      "message_id": 123,
      "action": "junk_review",
      "status": "committed",
      "code": null,
      "message": "Committed.",
      "executed": true,
      "labels_added": ["Fynish/Junk"],
      "labels_removed": ["INBOX"]
    }
  ]
}
```

Allowed result statuses:

- `committed`
- `failed`
- `stale`
- `blocked`

Stable result codes for the first deploy batch:

- `stale_message`
- `missing_state_version`
- `duplicate_staged_message`
- `gmail_reconnect_required`
- `unsafe_message_action`
- `message_action_failed`
- `internal_error`

Use existing error codes from `backend/app/core/errors.py` where possible.

## Backend Commit Behavior

For each staged action:

1. Verify current user is present.
2. Verify the message belongs to the current user.
3. Verify the message is still unreviewed.
4. Require `expected_version`; versionless actions return a per-item `stale` result with `missing_state_version`.
5. Compare `expected_version` with the current message version.
6. Determine whether the account should execute live Gmail writes.
7. If live writes are enabled and allowed, call `execute_message_action(..., allow_live_writes=True, require_feature_flag=True, user_id=current_user.id)`.
8. If the live result is executed, call `log_executed_message_action(...)`.
9. If live execution is blocked, return `blocked` and leave the message visible.
10. If live writes are not available, call `apply_message_action(..., user_id=current_user.id)`.
11. Return one result per requested action.

The commit endpoint persists one response per `(user_id, idempotency_key)` in `staged_commit_requests`. An unchanged retry with the same idempotency key returns the stored response with `idempotent_replay: true` and does not create duplicate action logs or duplicate rules.

The endpoint should never fail the whole batch because one message fails. Known per-message failures should be represented in `results`.

Unexpected endpoint-level failures are still handled by the global API exception handler.

## Live Gmail Semantics

The staged commit must preserve the current product semantics:

- modify-capable accounts should mutate Gmail on commit
- read-only or non-live accounts should only update Fynish state
- Gmail credentials remain server-side
- Gmail failures should leave affected messages uncommitted and visible

The backend, not the frontend, must make the final live-write decision. The frontend can include account metadata for rendering, but the commit endpoint should not trust a client-supplied live-mode flag.

## Error Handling

Follow `docs/ERROR_HANDLING_STRATEGY.md`.

User-facing messages should be short and actionable:

- `Stored Gmail credentials were expired or revoked. Reconnect the account.`
- `This message changed after the queue loaded. Review it again.`
- `This message was already processed. The queue has been refreshed.`
- `Fynish could not save this change. Please try again.`

Do not expose:

- OAuth codes
- access tokens
- refresh tokens
- OpenAI keys
- provider stack traces
- full email bodies

## Logging

The commit endpoint should log one structured summary per commit request:

- user id
- idempotency key
- requested count
- committed count
- failed count
- stale count
- blocked count

Known per-message failures should log at warning level only when useful for operations, such as Gmail credential failures.

Do not log full message body text or snippets.

## Implementation And Deployment Cadence

Work locally for two slices, validate both slices together, then deploy the validated pair to the VM.

Batch 1:

- Slice 1: backend commit API for `This Message` actions
- Slice 2: frontend staged Review Queue for `This Message` actions
- Local validation
- Deploy Batch 1 to the VM
- VM validation

After Batch 1 is deployed, continue with later slices in the same pattern unless a slice is small and safe enough to deploy alone.

## Slice Advancement Rule

After starting implementation, do not pause for approval between slices when the current slice meets its "Good Enough To Advance" definition.

Pause only if:

- the implementation requires a product decision listed as an open question
- a validation gate fails and the failure changes the planned behavior
- credentials, secrets, or VM configuration changes are required
- the codebase reveals that the planned approach would risk data loss

## Slice 1: Backend Commit API For `This Message`

### Scope

Add backend support for committing staged one-message actions.

Files likely touched:

- `backend/app/schemas/api.py`
- `backend/app/api/routes.py`
- `backend/app/services/review_queue.py` or a new `backend/app/services/staged_commit.py`
- `backend/app/core/errors.py` only if a new stable code is necessary
- backend tests

### Requirements

Add queue `state_version`:

- include `state_version` in each Review Queue message returned by `GET /api/review-queue`
- derive from `messages.updated_at` first, then classification timestamp

Add schemas:

- `StagedActionCommitItem`
- `StagedActionsCommitRequest`
- `StagedActionCommitResult`
- `StagedActionsCommitResponse`

Add route:

- `POST /api/review-queue/staged-actions/commit`

Implement commit behavior:

- support only plain message actions in Slice 1
- reject or fail any rule payload if accidentally provided
- preserve current live Gmail behavior
- return per-message results
- keep known failures item-scoped
- require current user
- enforce message ownership
- detect already-reviewed or missing messages as stale
- compare `expected_version` when present

### Good Enough To Advance

Slice 1 is good enough when:

- `GET /api/review-queue` includes `state_version` on every message.
- `POST /api/review-queue/staged-actions/commit` exists.
- The endpoint commits a valid non-live message action.
- The endpoint commits a valid live message action through the existing live executor path when live writes are available.
- Missing, already-reviewed, duplicate, stale-version, and unsafe-action cases return per-item failures.
- Gmail reconnect-required failures return per-item failures with `gmail_reconnect_required`.
- The endpoint returns a summary with committed and failed counts.
- Backend tests cover success, stale message, duplicate message, and credential failure.

### Local Validation

Run focused tests:

```bash
.venv/bin/pytest backend/tests/unit/test_review_queue.py backend/tests/unit/test_gmail_write_executor.py backend/tests/integration/test_staged_commit_api.py
```

If the new tests live elsewhere, include them in this focused set.

## Slice 2: Frontend Staged Review For `This Message`

### Scope

Wire the Review Queue UI so `This Message` actions stage locally and commit through the new backend endpoint.

Files likely touched:

- `frontend/src/types.ts`
- `frontend/src/api.ts`
- `frontend/src/App.tsx`
- `frontend/src/App.css`
- frontend tests if practical

### Requirements

Add API helper:

- `commitStagedQueueActions(payload)`

Add local state:

- `stagedActions`
- `stagedOrder`
- `commitBusy`
- `commitErrors`

Action click behavior:

- `Keep`, `Bulk`, `Junk`, and `Trash` stage locally
- staged messages disappear from the active queue
- staged messages appear in a compact staged section
- no backend action endpoint is called on stage
- user sees staged count

Toolbar behavior:

- `Undo Last` restores the most recent staged message to the active queue
- `Discard` restores all staged messages to the active queue
- `Commit Changes` calls the backend commit endpoint
- `Commit Changes` is disabled while commit is in progress or when no staged actions exist

Commit reconciliation:

- committed messages are removed from staged state
- failed/stale/blocked messages are restored to the active queue
- each restored failed message shows a concise error near the card or in the staged/notice area
- after commit, refresh queue with `loadAll({ preserveScroll: true })`
- show a summary notice such as `Committed 8 changes. 2 need attention.`

Rule-teaching buttons:

- keep current immediate behavior for Slice 2
- do not stage `Always Keep Domain` or `Always Junk Domain` yet
- make this visually unsurprising by only staging controls in the `This Message` panel

### Good Enough To Advance

Slice 2 is good enough when:

- Clicking a `This Message` action removes that message from the active queue immediately.
- No backend action call is made until `Commit Changes`.
- Staged toolbar appears with accurate count.
- Staged section lists staged message subject, account, and selected action.
- `Undo Last` works.
- `Discard` works.
- `Commit Changes` sends all staged actions to the new endpoint.
- Successful commit clears staged state.
- Failed commit results restore failed messages and show actionable copy.
- Rule-teaching buttons still behave exactly as before.
- The existing Review Queue layout remains recognizable.
- The frontend build passes.

### Local Validation

Run:

```bash
npm run build
```

If browser testing is available, manually verify locally:

1. Load Review Queue.
2. Stage one `This Message` action.
3. Confirm the message leaves the active queue.
4. Confirm the staged toolbar and staged section appear.
5. Undo it.
6. Stage two messages.
7. Discard them.
8. Stage messages again.
9. Commit.
10. Confirm committed messages leave the queue after refresh.

## Batch 1 Deployment Gate

Deploy slices 1 and 2 together only after:

- Slice 1 backend tests pass.
- Slice 2 frontend build passes.
- The app can start locally or existing focused import checks pass.
- No credentials or environment changes are required.
- No unrelated files are reverted.

Deploy to the VM using the normal project deployment path.

After deployment validate:

- backend service active
- frontend service active
- `GET /api/health` returns `{"status":"ok"}`
- public login endpoint returns `200`
- Review Queue loads for the signed-in user
- staged toolbar appears after a `This Message` click
- commit succeeds for at least one safe test message, or the endpoint is validated with a non-destructive API test if no safe queue item is available

## Slice 3: Stage Rule-Teaching Actions

### Scope

Extend staged commit to support `Always Keep Domain` and `Always Junk Domain`.

Status: deployed and validated on the VM on 2026-06-04. Rule-teaching actions now stage rule metadata with the source-message action and commit through the same backend endpoint.

### Requirements

Add optional rule payload:

```json
{
  "scope": "global",
  "rule_type": "domain",
  "pattern": "example.com",
  "action": "junk_review"
}
```

Commit rule plus source-message action as one logical unit:

- if rule creation fails, do not apply the source-message action
- if rule creation succeeds but source-message action fails, return a warning-style result with clear final state
- reuse existing duplicate/re-enable rule behavior
- reclassify pending queue after rule commit

### Good Enough To Advance

- Domain rule staging works for Always Keep and Always Junk.
- Existing immediate rule-teaching behavior is removed or hidden only after staged behavior works.
- Duplicate enabled rules are reused.
- Disabled identical rules are re-enabled.
- Source-message failure produces clear partial-success copy.
- Tests cover rule success and rule/source-message partial failure.

## Slice 4: Freshness And Idempotency Hardening

### Scope

Make duplicate commit behavior safer and stale-state handling stricter.

### Requirements

- compare `expected_version` for all staged actions
- require `expected_version` so versionless requests cannot silently commit
- persist idempotency responses by user and idempotency key
- add tests for double-submit/replay behavior

### Good Enough To Advance

- stale queue items cannot be silently committed
- duplicate message ids in one request are handled deterministically
- double-clicking `Commit Changes` cannot create duplicate action logs from the frontend
- unchanged retries with the same idempotency key return the stored response without duplicating side effects

## Slice 5: UX Polish And Speed Enhancements

### Scope

Improve the staged workflow after core correctness is in place.

Candidates:

- keyboard shortcuts
- optional auto-commit threshold
- more compact staged section
- account-level staged grouping
- preserve scroll position more carefully after commit
- show staged changes in the page summary metrics

### Good Enough To Advance

- no polish change hides the staged/uncommitted state
- mobile and desktop layouts remain readable
- no text overflows in toolbar buttons or staged cards
- frontend build passes

### Implemented

- Grouped staged messages by account in the staged panel.
- Added an explicit masthead `Staged` metric next to active queue metrics.
- Tightened staged panel spacing and mobile wrapping so controls remain readable.

## Slice 6: Keyboard Shortcuts And Frontend Smoke Coverage

### Scope

Add fast keyboard handling for the staged Review Queue without weakening the explicit commit model.

### Implemented

- `1` stages `Keep` for the next visible queue message.
- `2` stages `Bulk` for the next visible queue message.
- `3` stages `Junk` for the next visible queue message.
- `4` stages `Trash` for the next visible queue message.
- `u` undoes the last staged action.
- `c` commits staged changes.
- Shortcuts are active only on the Review Queue, only when the app is not busy, and not while focus is in a text entry/select field.
- Current Playwright smoke tests cover queue loading, shortcut staging/undo, discard, and commit.

### Good Enough To Advance

- keyboard shortcuts do not fire while typing in forms
- shortcuts do not hide staged/uncommitted state
- smoke tests pass against a temp SQLite test database
- frontend build passes

## Test Plan

Backend tests should include:

- queue response includes `state_version`
- commit valid non-live action
- commit valid live action with mocked executor
- stale/missing/already-reviewed message
- duplicate message in same request
- Gmail credential failure maps to `gmail_reconnect_required`
- unsafe action maps to `unsafe_message_action`
- user cannot commit another user's message

Frontend tests or manual checks should include:

- stage one action
- stage multiple actions
- undo last
- discard all
- commit success
- commit partial failure
- rule buttons still immediate until Slice 3
- busy/disabled states
- empty queue monitored accounts still render correctly

## Documentation Updates During Implementation

Update these docs as behavior lands:

- `docs/REVIEW_QUEUE_STAGED_COMMIT_PLAN.md`
- `docs/FYNISH_FUNCTIONAL_GUIDE.md`
- `README.md` if current UI behavior changes materially

The staged commit implementation spec is the controlling implementation guide until Batch 1 is deployed.

## Open Questions Deferred Until After Batch 1

These should not block slices 1 and 2:

- whether to auto-commit after a threshold
- whether to add keyboard shortcuts
- whether to persist idempotency keys
- whether backend queue caching is needed after client-side staging
- whether preview body text should be prefetched more aggressively
